"""Offer endpoints + two-step approval + extend/accept/decline/revoke."""
from flask import Blueprint, request

import clock
import db
from auth import require_role
from common import (
    get_json_or_400,
    require_str,
    require_int,
    new_id,
    now_iso,
    parse_pagination,
    paginate,
    get_or_404,
    fk_or_404,
    stamp_update,
)
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PRECONDITION_FAILED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_DUPLICATE_OFFER,
    ERR_SALARY_OUT_OF_BAND,
    ERR_BUDGET_EXCEEDED,
    ERR_STALE_VERSION,
    ERR_OFFER_EXPIRED,
)
from response import success_object, success_array
from serializers import ser_offer
from services.department import compute_committed_offer_cents
from services.cascades import (
    APPLICATION_NON_TERMINAL,
    OFFER_NON_TERMINAL_OR_ACCEPTED,
    revoke_offer_cascade,
    create_background_check,
    create_referral_bonus_if_eligible,
    transition_application_to_hired,
    compute_expires_at,
)


bp = Blueprint("offers", __name__)

OFFER_ACTIVE_STATUSES = {"PENDING_APPROVAL", "APPROVED", "EXTENDED", "ACCEPTED"}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@bp.post("/ats/offers")
def create_offer():
    uid, _ = require_role({"Recruiter"})
    body = get_json_or_400()
    application_id = require_str(body, "application_id")
    base_salary_cents = require_int(body, "base_salary_cents", minimum=0)
    signing_bonus_cents = require_int(body, "signing_bonus_cents", minimum=0)

    app = fk_or_404(db.applications, application_id, "application")
    req = db.requisitions.get(app["requisition_id"])

    # Duplicate offer (priority 11) — at most one active per application.
    for o in db.offers.values():
        if o["application_id"] == application_id and o["status"] in OFFER_ACTIVE_STATUSES:
            raise ApiError(ERR_DUPLICATE_OFFER, 422, "an active offer already exists for this application")

    # Salary band (priority 16).
    if not (req["base_salary_min_cents"] <= base_salary_cents <= req["base_salary_max_cents"]):
        raise ApiError(ERR_SALARY_OUT_OF_BAND, 422, "base_salary_cents outside requisition band")

    offer = {
        "id": new_id(),
        "application_id": application_id,
        "base_salary_cents": base_salary_cents,
        "signing_bonus_cents": signing_bonus_cents,
        "status": "PENDING_APPROVAL",
        "comp_approver_user_id": None,
        "vp_approver_user_id": None,
        "submitter_user_id": uid,
        "extended_at": None,
        "expires_at": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.offers[offer["id"]] = offer
    return success_object(ser_offer(offer), status=201)


@bp.get("/ats/offers/<offer_id>")
def read_offer(offer_id):
    require_role({"Recruiter", "HiringManager", "CompApprover", "VP", "PlatformAdmin", "Candidate"})
    offer = get_or_404(db.offers, offer_id, "offer")
    return success_object(ser_offer(offer), status=200)


@bp.get("/ats/offers")
def list_offers():
    require_role({"Recruiter", "HiringManager", "CompApprover", "VP", "PlatformAdmin"})
    limit, offset = parse_pagination()
    rows = list(db.offers.values())
    app_filter = request.args.get("application_id")
    status_filter = request.args.get("status")
    if app_filter:
        rows = [o for o in rows if o["application_id"] == app_filter]
    if status_filter:
        rows = [o for o in rows if o["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_offer(o) for o in page], limit, offset, total, status=200)


# ---------------------------------------------------------------------------
# Approval (two-step)
# ---------------------------------------------------------------------------


def _department_of_application(app_id):
    app = db.applications[app_id]
    req = db.requisitions[app["requisition_id"]]
    return db.departments[req["department_id"]]


@bp.post("/ats/offers/<offer_id>/approve")
def approve_offer(offer_id):
    uid, role = require_role({"CompApprover", "VP"})
    offer = get_or_404(db.offers, offer_id, "offer")
    body = get_json_or_400()
    expected_version = body.get("expected_offer_version")

    if offer["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_INVALID_STATE, 409, "offer not in PENDING_APPROVAL")

    is_comp_leg = (role == "CompApprover")
    is_vp_leg = (role == "VP")

    if is_comp_leg and offer["comp_approver_user_id"] is not None:
        # CompApprover acting twice on the same offer is invalid state for this leg.
        raise ApiError(ERR_INVALID_STATE, 409, "comp approval already completed")
    if is_vp_leg and offer["comp_approver_user_id"] is None:
        raise ApiError(ERR_INVALID_STATE, 409, "VP leg requires comp approval first")

    # Segregation: must differ from submitter; VP must also differ from comp_approver.
    if uid == offer["submitter_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "approver must differ from submitter")
    if is_vp_leg and uid == offer["comp_approver_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "VP must differ from comp approver")

    # Budget check (priority 18).
    dept = _department_of_application(offer["application_id"])
    committed = compute_committed_offer_cents(dept["id"])
    # offer.base_salary_cents is already included in committed (it's PENDING_APPROVAL which is active).
    net_committed = committed - offer["base_salary_cents"]
    if (dept["hiring_budget_cents"] - net_committed - offer["base_salary_cents"]) < 0:
        raise ApiError(ERR_BUDGET_EXCEEDED, 422, "insufficient budget headroom for offer approval")

    # OCC (priority 19) — last per priority order.
    if expected_version is None or not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_offer_version required")
    if expected_version != offer["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_offer_version mismatch")

    # Apply.
    if is_comp_leg:
        offer["comp_approver_user_id"] = uid
        # Still PENDING_APPROVAL.
    else:
        offer["vp_approver_user_id"] = uid
        offer["status"] = "APPROVED"
    stamp_update(offer)
    return success_object(ser_offer(offer), status=200)


@bp.post("/ats/offers/<offer_id>/reject")
def reject_offer(offer_id):
    uid, _ = require_role({"CompApprover", "VP"})
    offer = get_or_404(db.offers, offer_id, "offer")
    if offer["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_INVALID_STATE, 409, "offer not in PENDING_APPROVAL")
    if uid == offer["submitter_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "approver must differ from submitter")
    offer["status"] = "REJECTED"
    stamp_update(offer)
    return success_object(ser_offer(offer), status=200)


@bp.post("/ats/offers/<offer_id>/extend")
def extend_offer(offer_id):
    require_role({"Recruiter"})
    offer = get_or_404(db.offers, offer_id, "offer")
    if offer["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "offer not in APPROVED")
    app = db.applications.get(offer["application_id"])
    req = db.requisitions.get(app["requisition_id"]) if app else None
    if not req or req["status"] != "APPROVED":
        raise ApiError(ERR_PRECONDITION_FAILED, 409, "requisition not APPROVED")
    now_dt = clock.now()
    offer["status"] = "EXTENDED"
    offer["extended_at"] = clock.iso(now_dt)
    offer["expires_at"] = compute_expires_at(now_dt)
    stamp_update(offer)
    # Cascade application SCREENING|INTERVIEWING -> OFFER_EXTENDED.
    if app and app["status"] in {"SCREENING", "INTERVIEWING"}:
        app["status"] = "OFFER_EXTENDED"
        stamp_update(app)
    return success_object(ser_offer(offer), status=200)


@bp.post("/ats/offers/<offer_id>/accept")
def accept_offer(offer_id):
    require_role({"Candidate"})
    offer = get_or_404(db.offers, offer_id, "offer")
    if offer["status"] != "EXTENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "offer not in EXTENDED")
    # Expiry check.
    now_dt = clock.now()
    exp = clock.parse_iso(offer["expires_at"])
    if now_dt >= exp:
        # Treat as REVOKED per PRD §3.6.
        revoke_offer_cascade(offer)
        raise ApiError(ERR_OFFER_EXPIRED, 409, "offer expired")
    # Accept.
    offer["status"] = "ACCEPTED"
    offer["accepted_at"] = clock.iso(now_dt)
    stamp_update(offer)
    # Cascades: create BGC, create ReferralBonus, advance Application to HIRED.
    create_background_check(offer)
    create_referral_bonus_if_eligible(offer)
    transition_application_to_hired(offer["application_id"])
    return success_object(ser_offer(offer), status=200)


@bp.post("/ats/offers/<offer_id>/decline")
def decline_offer(offer_id):
    require_role({"Candidate"})
    offer = get_or_404(db.offers, offer_id, "offer")
    if offer["status"] != "EXTENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "offer not in EXTENDED")
    offer["status"] = "DECLINED"
    stamp_update(offer)
    return success_object(ser_offer(offer), status=200)


@bp.post("/ats/offers/<offer_id>/revoke")
def revoke_offer(offer_id):
    require_role({"Recruiter"})
    offer = get_or_404(db.offers, offer_id, "offer")
    if offer["status"] not in {"APPROVED", "EXTENDED"}:
        raise ApiError(ERR_INVALID_STATE, 409, "offer not in APPROVED or EXTENDED")
    revoke_offer_cascade(offer)
    return success_object(ser_offer(offer), status=200)
