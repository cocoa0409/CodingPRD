"""Offer and OfferApprovalStep routes — the cyclic approval/renegotiation machine."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format, now, parse_iso
from ..common import (
    bump, check_occ, get_json_body, positive_int, require_enum,
    require_fields, require_str, stamp_new,
)
from ..errors import ApiError
from ..lookups import path_application, path_offer
from ..response import respond
from ..serializers import serialize_approval_step, serialize_offer
from ..services import (
    cascade_application_to_hired, cascade_offer_decline, cascade_offer_rescind,
    max_step_order, recompute_active_offer_count, recompute_offer_total,
    reset_approval_steps, steps_for_offer,
)
from ..store import store


offers_bp = Blueprint("offers", __name__)


APPROVER_ROLES = {"HIRING_MANAGER", "COMPENSATION", "EXECUTIVE"}


# ---------- create on application ----------

@offers_bp.post("/applications/<aid>/offers")
@require_auth("Recruiter")
def create_offer(aid):
    body = get_json_body()
    require_fields(body, "base_salary_cents", "approval_chain")
    base = positive_int(body["base_salary_cents"], "base_salary_cents", allow_zero=True)
    signon = body.get("sign_on_bonus_cents", 0)
    if signon is None:
        signon = 0
    signon = positive_int(signon, "sign_on_bonus_cents", allow_zero=True)
    equity = body.get("annual_equity_cents", 0)
    if equity is None:
        equity = 0
    equity = positive_int(equity, "annual_equity_cents", allow_zero=True)
    chain = body["approval_chain"]
    if not isinstance(chain, list) or not chain:
        raise ApiError("ERR_VALIDATION", "approval_chain must be a non-empty array")

    with store.lock:
        app = path_application(aid)
        req = store.requisitions.get(app["requisition_id"])
        if req is None:
            raise ApiError("ERR_NOT_FOUND", "Parent Requisition not found")
        if g.user_id != req["recruiter_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the owning recruiter may create offers")
        if app["stage"] != "OFFER_STAGE":
            raise ApiError("ERR_INVALID_STATE", "Application stage must be OFFER_STAGE")

        # Validate chain step orders form 1..N with no gaps.
        normalized_steps = []
        seen_orders = set()
        for entry in chain:
            if not isinstance(entry, dict):
                raise ApiError("ERR_VALIDATION", "approval_chain entries must be objects")
            order = entry.get("step_order")
            if not isinstance(order, int) or isinstance(order, bool) or order < 1:
                raise ApiError("ERR_VALIDATION", "step_order must be a positive integer")
            if order in seen_orders:
                raise ApiError("ERR_VALIDATION", "step_order must be unique within an offer")
            seen_orders.add(order)
            approver_role = require_enum(entry.get("approver_role"), "approver_role", APPROVER_ROLES)
            required_approver_id = entry.get("required_approver_id")
            if not isinstance(required_approver_id, str) or not required_approver_id:
                raise ApiError("ERR_VALIDATION", "required_approver_id must be a non-empty string")
            # PRD §2.6: "foreign-key fields supplied in the request
            # body are checked next — a missing referenced entity
            # produces `ERR_REFERENCE_NOT_FOUND`".
            # For a HIRING_MANAGER step the required_approver_id is
            # a foreign key (PRD §3.5: "the corresponding HiringManager.id").
            # PRD §3.5 also says the recruiter-id-as-approver case is
            # a segregation-of-duties violation "flagged at approve
            # time" — so we treat the FK gate as a pure existence
            # check (the id must reference some persisted entity);
            # the type / SoD checks are deferred to approve time.
            if approver_role == "HIRING_MANAGER":
                exists = (
                    required_approver_id in store.hiring_managers
                    or required_approver_id in store.recruiters
                    or required_approver_id in store.interviewers
                    or required_approver_id in store.candidates
                )
                if not exists:
                    raise ApiError(
                        "ERR_REFERENCE_NOT_FOUND",
                        "required_approver_id does not reference any existing entity",
                    )
            normalized_steps.append(
                {
                    "step_order": order,
                    "approver_role": approver_role,
                    "required_approver_id": required_approver_id,
                }
            )
        normalized_steps.sort(key=lambda s: s["step_order"])
        # Must start at 1 and be contiguous.
        for idx, s in enumerate(normalized_steps, start=1):
            if s["step_order"] != idx:
                raise ApiError("ERR_VALIDATION", "approval_chain step_order values must be 1..N contiguous")
        if normalized_steps[0]["step_order"] != 1:
            raise ApiError("ERR_VALIDATION", "approval_chain must include step_order=1")

        offer = stamp_new({
            "application_id": aid,
            "requisition_id": req["id"],
            "base_salary_cents": base,
            "sign_on_bonus_cents": signon,
            "annual_equity_cents": equity,
            "total_first_year_comp_cents": 0,
            "pinned_requisition_version": None,
            "status": "DRAFT",
            "expires_at": None,
            "negotiation_round": 0,
        })
        recompute_offer_total(offer)
        store.offers[offer["id"]] = offer
        store.offers_created_by[offer["id"]] = g.user_id

        for s in normalized_steps:
            step = stamp_new(
                {
                    "offer_id": offer["id"],
                    "step_order": s["step_order"],
                    "approver_role": s["approver_role"],
                    "required_approver_id": s["required_approver_id"],
                    "decision": "PENDING",
                    "decided_at": None,
                },
                with_common=False,
            )
            store.offer_approval_steps[step["id"]] = step

    return respond(serialize_offer(offer), 201)


@offers_bp.get("/offers/<oid>")
@require_auth("Recruiter", "HiringManager", "Candidate", "Compensation", "Executive", "PlatformAdmin")
def get_offer(oid):
    with store.lock:
        offer = path_offer(oid)
        if g.user_role == "Candidate":
            app = store.applications.get(offer["application_id"])
            if not app or g.user_id != app["candidate_id"]:
                raise ApiError("ERR_FORBIDDEN", "Candidate may only read own offers")
        return respond(serialize_offer(offer))


@offers_bp.patch("/offers/<oid>")
@require_auth("Recruiter")
def patch_offer(oid):
    body = get_json_body()
    with store.lock:
        offer = path_offer(oid)
        if g.user_id != store.offers_created_by.get(offer["id"]):
            raise ApiError("ERR_FORBIDDEN", "Only the creating recruiter may edit this offer")
        check_occ(offer, body.get("version"))

        # Mutability constraint.
        money_fields = {"base_salary_cents", "sign_on_bonus_cents", "annual_equity_cents"}
        attempted_money = [k for k in money_fields if k in body and body[k] is not None]
        if attempted_money and offer["status"] not in {"DRAFT", "NEGOTIATING"}:
            raise ApiError(
                "ERR_OFFER_FIELDS_IMMUTABLE",
                "Offer compensation fields are only mutable while DRAFT or NEGOTIATING",
            )

        if "base_salary_cents" in body and body["base_salary_cents"] is not None:
            offer["base_salary_cents"] = positive_int(
                body["base_salary_cents"], "base_salary_cents", allow_zero=True
            )
        if "sign_on_bonus_cents" in body and body["sign_on_bonus_cents"] is not None:
            offer["sign_on_bonus_cents"] = positive_int(
                body["sign_on_bonus_cents"], "sign_on_bonus_cents", allow_zero=True
            )
        if "annual_equity_cents" in body and body["annual_equity_cents"] is not None:
            offer["annual_equity_cents"] = positive_int(
                body["annual_equity_cents"], "annual_equity_cents", allow_zero=True
            )

        # If we were NEGOTIATING and money fields changed, drive back to PENDING_APPROVAL.
        if offer["status"] == "NEGOTIATING" and attempted_money:
            recompute_offer_total(offer)
            req = store.requisitions[offer["requisition_id"]]
            if offer["total_first_year_comp_cents"] > req["budget_cents"]:
                raise ApiError(
                    "ERR_OFFER_EXCEEDS_REQ_BUDGET",
                    "Offer total exceeds requisition budget after edit",
                )
            offer["status"] = "PENDING_APPROVAL"
            offer["negotiation_round"] = offer.get("negotiation_round", 0) + 1
            reset_approval_steps(offer["id"])
        else:
            recompute_offer_total(offer)
        bump(offer)
        return respond(serialize_offer(offer))


# ---------- submit ----------

@offers_bp.post("/offers/<oid>/submit")
@require_auth("Recruiter")
def submit_offer(oid):
    with store.lock:
        offer = path_offer(oid)
        if g.user_id != store.offers_created_by.get(offer["id"]):
            raise ApiError("ERR_FORBIDDEN", "Only the creating recruiter may submit this offer")
        if offer["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Offer must be in DRAFT to submit")
        app = store.applications[offer["application_id"]]
        req = store.requisitions[offer["requisition_id"]]
        if app["stage"] != "OFFER_STAGE":
            raise ApiError("ERR_INVALID_STATE", "Parent Application must be in OFFER_STAGE")
        if req["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Parent Requisition must be OPEN")

        recompute_offer_total(offer)
        if offer["total_first_year_comp_cents"] > req["budget_cents"]:
            raise ApiError(
                "ERR_OFFER_EXCEEDS_REQ_BUDGET",
                "Offer total exceeds requisition budget",
            )
        # At least one step with step_order=1.
        steps = steps_for_offer(offer["id"])
        if not steps or steps[0]["step_order"] != 1:
            raise ApiError("ERR_INVALID_STATE", "Offer requires an approval chain starting at step_order=1")

        offer["status"] = "PENDING_APPROVAL"
        offer["pinned_requisition_version"] = req["version"]
        bump(offer)
        recompute_active_offer_count(req)
        return respond(serialize_offer(offer))


# ---------- approve (one step at a time) ----------

@offers_bp.post("/offers/<oid>/approve")
@require_auth("HiringManager", "Compensation", "Executive")
def approve_offer_step(oid):
    body = get_json_body()
    require_fields(body, "step_order")
    step_order = body["step_order"]
    if isinstance(step_order, bool) or not isinstance(step_order, int):
        raise ApiError("ERR_VALIDATION", "step_order must be an integer")

    with store.lock:
        offer = path_offer(oid)
        if offer["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "Offer is not PENDING_APPROVAL")
        steps = steps_for_offer(offer["id"])
        # Find the step.
        target = next((s for s in steps if s["step_order"] == step_order), None)
        if target is None:
            raise ApiError("ERR_NOT_FOUND", "Approval step not found at the supplied step_order")
        if target["decision"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Approval step is not PENDING")
        # All prior steps must be APPROVED.
        for s in steps:
            if s["step_order"] < step_order and s["decision"] != "APPROVED":
                raise ApiError("ERR_INVALID_STATE", "A prior approval step is still pending or rejected")
        # Role + approver id check.
        role_to_step = {
            "HIRING_MANAGER": "HiringManager",
            "COMPENSATION": "Compensation",
            "EXECUTIVE": "Executive",
        }
        if g.user_role != role_to_step[target["approver_role"]]:
            raise ApiError("ERR_FORBIDDEN", f"Role {g.user_role} cannot approve this step")
        if g.user_id != target["required_approver_id"]:
            raise ApiError("ERR_FORBIDDEN", "Approver id does not match required_approver_id")
        # Segregation of duties: approver must not be the creating recruiter.
        if g.user_id == store.offers_created_by.get(offer["id"]):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "Approver may not be the recruiter who created the offer",
            )

        target["decision"] = "APPROVED"
        target["decided_at"] = iso_format(now())

        # Final step?
        if step_order == max_step_order(offer["id"]):
            # Background-check must be PASSED (PRD §3.5 cross-entity gate).
            if not _offer_has_passed_bgc(offer["id"]):
                # Roll back this step decision so the state stays consistent.
                target["decision"] = "PENDING"
                target["decided_at"] = None
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "Final approval requires a PASSED BackgroundCheck for this offer",
                )
            req = store.requisitions[offer["requisition_id"]]
            recompute_offer_total(offer)
            if offer["total_first_year_comp_cents"] > req["budget_cents"]:
                target["decision"] = "PENDING"
                target["decided_at"] = None
                raise ApiError(
                    "ERR_OFFER_EXCEEDS_REQ_BUDGET",
                    "Offer total exceeds requisition budget",
                )
            # Manager budget check.
            manager = store.hiring_managers.get(req["hiring_manager_id"])
            if manager is None:
                target["decision"] = "PENDING"
                target["decided_at"] = None
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "Hiring manager not found")
            if offer["total_first_year_comp_cents"] > manager.get("budget_cents", 0):
                target["decision"] = "PENDING"
                target["decided_at"] = None
                raise ApiError(
                    "ERR_MANAGER_BUDGET_EXCEEDED",
                    "Approving this offer would push the hiring manager past their budget",
                )
            # Commit.
            offer["status"] = "APPROVED"
            manager["budget_cents"] = manager["budget_cents"] - offer["total_first_year_comp_cents"]
            bump(manager)

        bump(offer)
        return respond(serialize_offer(offer))


def _find_background_check_for_offer(offer_id: str):
    """Return any BackgroundCheck for the offer (legacy single-BGC API).

    Multiple BGCs may now exist (a previous PASSED + a fresh PENDING),
    so callers that gate on PASSED should use `_offer_has_passed_bgc`.
    """
    for bg in store.background_checks.values():
        if bg["offer_id"] == offer_id:
            return bg
    return None


def _offer_has_passed_bgc(offer_id: str) -> bool:
    """PRD §3.5 — approval final step and extend require a PASSED BGC."""
    for bg in store.background_checks.values():
        if bg["offer_id"] == offer_id and bg["status"] == "PASSED":
            return True
    return False


# ---------- request-revision ----------

@offers_bp.post("/offers/<oid>/request-revision")
@require_auth("HiringManager", "Compensation", "Executive")
def request_revision(oid):
    body = get_json_body()
    require_fields(body, "step_order")
    step_order = body["step_order"]
    if isinstance(step_order, bool) or not isinstance(step_order, int):
        raise ApiError("ERR_VALIDATION", "step_order must be an integer")

    with store.lock:
        offer = path_offer(oid)
        if offer["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "Offer is not PENDING_APPROVAL")
        steps = steps_for_offer(offer["id"])
        target = next((s for s in steps if s["step_order"] == step_order), None)
        if target is None:
            raise ApiError("ERR_NOT_FOUND", "Approval step not found")
        if target["decision"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Approval step is not PENDING")
        role_to_step = {
            "HIRING_MANAGER": "HiringManager",
            "COMPENSATION": "Compensation",
            "EXECUTIVE": "Executive",
        }
        if g.user_role != role_to_step[target["approver_role"]]:
            raise ApiError("ERR_FORBIDDEN", f"Role {g.user_role} cannot request revision on this step")
        if g.user_id != target["required_approver_id"]:
            raise ApiError("ERR_FORBIDDEN", "Approver id does not match required_approver_id")

        target["decision"] = "REJECTED"
        target["decided_at"] = iso_format(now())
        offer["status"] = "NEGOTIATING"
        bump(offer)
        return respond(serialize_offer(offer))


# ---------- extend ----------

@offers_bp.post("/offers/<oid>/extend")
@require_auth("Recruiter")
def extend_offer(oid):
    body = get_json_body()
    require_fields(body, "expires_at")
    expires_raw = require_str(body["expires_at"], "expires_at")
    try:
        expires_dt = parse_iso(expires_raw)
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))

    with store.lock:
        offer = path_offer(oid)
        if g.user_id != store.offers_created_by.get(offer["id"]):
            raise ApiError("ERR_FORBIDDEN", "Only the creating recruiter may extend this offer")
        if offer["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Offer must be APPROVED to extend")
        if expires_dt <= now():
            raise ApiError("ERR_OFFER_EXPIRES_IN_PAST", "expires_at must be strictly after now()")
        if not _offer_has_passed_bgc(offer["id"]):
            raise ApiError(
                "ERR_INVALID_STATE",
                "BackgroundCheck must be PASSED to extend the offer",
            )

        offer["status"] = "EXTENDED"
        offer["expires_at"] = iso_format(expires_dt)
        bump(offer)
        return respond(serialize_offer(offer))


# ---------- accept ----------

@offers_bp.post("/offers/<oid>/accept")
@require_auth("Candidate")
def accept_offer(oid):
    with store.lock:
        offer = path_offer(oid)
        app = store.applications[offer["application_id"]]
        if g.user_id != app["candidate_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the candidate may accept this offer")
        if offer["status"] != "EXTENDED":
            raise ApiError("ERR_INVALID_STATE", "Offer is not EXTENDED")
        if offer.get("expires_at") and now() >= parse_iso(offer["expires_at"]):
            raise ApiError("ERR_INVALID_STATE", "Offer expiry has passed")
        req = store.requisitions[offer["requisition_id"]]
        if req["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Parent Requisition is not OPEN")
        if req.get("filled_count", 0) >= req["headcount"]:
            raise ApiError("ERR_HEADCOUNT_EXCEEDED", "Requisition has no remaining headcount")

        offer["status"] = "ACCEPTED"
        bump(offer)
        # Cascade: Application -> HIRED, Requisition.filled_count++, possibly close.
        cascade_application_to_hired(app, offer)
        recompute_active_offer_count(req)
        return respond(serialize_offer(offer))


# ---------- decline ----------

@offers_bp.post("/offers/<oid>/decline")
@require_auth("Candidate")
def decline_offer(oid):
    with store.lock:
        offer = path_offer(oid)
        app = store.applications[offer["application_id"]]
        if g.user_id != app["candidate_id"]:
            raise ApiError("ERR_FORBIDDEN", "Only the candidate may decline this offer")
        if offer["status"] != "EXTENDED":
            raise ApiError("ERR_INVALID_STATE", "Offer is not EXTENDED")
        cascade_offer_decline(offer)
        return respond(serialize_offer(offer))


# ---------- rescind ----------

@offers_bp.post("/offers/<oid>/rescind")
@require_auth("Recruiter")
def rescind_offer(oid):
    with store.lock:
        offer = path_offer(oid)
        if g.user_id != store.offers_created_by.get(offer["id"]):
            raise ApiError("ERR_FORBIDDEN", "Only the creating recruiter may rescind this offer")
        if offer["status"] not in {"APPROVED", "EXTENDED"}:
            raise ApiError("ERR_INVALID_STATE", "Offer must be APPROVED or EXTENDED to rescind")
        cascade_offer_rescind(offer, reason_for_app="OTHER")
        return respond(serialize_offer(offer))


# ---------- approval chain read ----------

@offers_bp.get("/offers/<oid>/approval-chain")
@require_auth("Recruiter", "HiringManager", "Compensation", "Executive", "PlatformAdmin")
def get_approval_chain(oid):
    with store.lock:
        path_offer(oid)
        steps = steps_for_offer(oid)
        return respond([serialize_approval_step(s) for s in steps])
