"""/foia/requests — file/manage FOIA requests + lifecycle action endpoints."""

from __future__ import annotations

from typing import Optional

from flask import Blueprint, g, request as flask_request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import (
    ApiError,
    ERR_FK_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_GLOMAR_WITH_RECORDS,
    ERR_INVALID_GLOMAR_BASIS,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_MISSING_THIRD_PARTY_NOTICE,
    ERR_FEE_NOT_RESOLVED,
    ERR_NO_RESPONSIVE_RECORDS,
    ERR_NOT_FOUND,
    ERR_TOLLING_LIMIT_EXCEEDED,
)
from ..serializers import serialize_request
from ..services.fees import (
    FREE_THRESHOLD_CENTS,
    calc_fee_final,
    sum_chargeable_pages,
)
from ..store import append_audit, store
from ..timeutil import (
    add_business_days,
    business_days_between,
    clock,
    iso_now,
    parse_iso,
)
from ..util import (
    get_pagination,
    paginate,
    require_bool,
    require_json_body,
    require_str,
)


requests_bp = Blueprint("requests", __name__)

MAX_TOLL_DAYS = 30
RESPONSE_DAYS = 20
GLOMAR_ALLOWED_CODES = {"B1", "B6", "B7C"}


def _get_request(rid: str) -> dict:
    req = store.requests.get(rid)
    if req is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Request not found.")
    return req


def _calc_response_deadline(filed_at_iso: str, tolling_days_consumed: int) -> str:
    base = parse_iso(filed_at_iso)
    deadline = add_business_days(base, RESPONSE_DAYS + tolling_days_consumed)
    return iso_now(deadline)


def _fee_assessment_for_request(request_id: str) -> Optional[dict]:
    for fa in store.fee_assessments.values():
        if fa.get("request_id") == request_id:
            return fa
    return None


def _records_for_request(request_id: str):
    return [
        r
        for r in store.responsive_records.values()
        if r.get("request_id") == request_id
    ]


def _notices_for_record(record_id: str):
    return [
        n
        for n in store.third_party_notices.values()
        if n.get("record_id") == record_id
    ]


# ---------- POST /foia/requests ----------
@requests_bp.post("/foia/requests")
@require_auth({"Requester"})
def create_request():
    payload = require_json_body()
    requester_id = require_str(payload, "requester_id", max_len=200)
    subject_summary = require_str(payload, "subject_summary", max_len=2000)
    fee_waiver_requested = require_bool(payload, "fee_waiver_requested", default=False) or False

    requester = store.requesters.get(requester_id)
    if requester is None:
        raise ApiError(ERR_FK_NOT_FOUND, 404, "Referenced requester does not exist.")
    if requester["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Requester is not ACTIVE.")
    if requester["requester_tier"] != "COMMERCIAL":
        if not requester.get("tier_justification"):
            raise ApiError(
                ERR_INVALID_INPUT,
                400,
                "tier_justification required for non-commercial requester.",
            )

    entity = {
        "requester_id": requester_id,
        "subject_summary": subject_summary,
        "status": "INTAKE",
        "fee_estimate_accepted": False,
        "fee_waiver_requested": fee_waiver_requested,
        "fee_waiver_granted": None,
        "glomar_invoked": False,
        "glomar_exemption_basis": [],
        "filed_at": None,
        "response_due_at": None,
        "tolling_days_consumed": 0,
        "determination_at": None,
    }
    with store.lock:
        store.stamp_create(entity)
        store.requests[entity["id"]] = entity
        append_audit(
            subject_type="REQUEST",
            subject_id=entity["id"],
            event_code="INTAKE_RECEIVED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"requester_id": requester_id},
        )

    return ok_object(serialize_request(entity), status=201)


# ---------- GET /foia/requests/{id} ----------
@requests_bp.get("/foia/requests/<rid>")
@require_auth({"Requester", "Officer", "AppealAuthority"})
def get_request(rid: str):
    req = _get_request(rid)
    return ok_object(serialize_request(req))


# ---------- GET /foia/requests ----------
@requests_bp.get("/foia/requests")
@require_auth({"Officer", "AppealAuthority"})
def list_requests():
    limit, offset = get_pagination()
    status_filter = flask_request.args.get("status")
    requester_filter = flask_request.args.get("requester_id")
    items = list(store.requests.values())
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    if requester_filter:
        items = [r for r in items if r["requester_id"] == requester_filter]
    items.sort(key=lambda r: r["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_request(r) for r in page],
        limit=limit,
        offset=offset,
        total_count=total,
        has_more=has_more,
    )


# ---------- POST /foia/requests/{id}/acknowledge ----------
@requests_bp.post("/foia/requests/<rid>/acknowledge")
@require_auth({"Officer"})
def acknowledge(rid: str):
    req = _get_request(rid)
    with store.lock:
        if req["status"] != "INTAKE":
            raise ApiError(ERR_INVALID_STATE, 409, "Request is not in INTAKE.")
        requester = store.requesters.get(req["requester_id"])
        if requester is None or requester["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409, "Requester not ACTIVE.")
        if requester["requester_tier"] != "COMMERCIAL" and not requester.get("tier_justification"):
            raise ApiError(
                ERR_INVALID_INPUT,
                400,
                "tier_justification required for non-commercial requester.",
            )
        now_iso = iso_now(clock.now())
        req["status"] = "ACKNOWLEDGED"
        req["filed_at"] = now_iso
        req["response_due_at"] = _calc_response_deadline(now_iso, 0)
        store.bump(req)
        append_audit(
            subject_type="REQUEST",
            subject_id=req["id"],
            event_code="ACKNOWLEDGED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"filed_at": now_iso, "response_due_at": req["response_due_at"]},
        )
    return ok_object(serialize_request(req))


# ---------- POST /foia/requests/{id}/start-tolling ----------
@requests_bp.post("/foia/requests/<rid>/start-tolling")
@require_auth({"Officer"})
def start_tolling(rid: str):
    req = _get_request(rid)
    payload = require_json_body()
    reason = require_str(payload, "reason", max_len=1000)
    with store.lock:
        # Per §1.4 priority 10: tolling cap is checked BEFORE the state precondition.
        if req["tolling_days_consumed"] >= MAX_TOLL_DAYS:
            raise ApiError(
                ERR_TOLLING_LIMIT_EXCEEDED,
                422,
                "Cumulative tolling already at the 30-business-day limit.",
            )
        if req["status"] != "ACKNOWLEDGED":
            raise ApiError(ERR_INVALID_STATE, 409, "Request is not in ACKNOWLEDGED.")
        # We do not have a measured pause length yet, but we must reject any
        # call when consumed days have already reached the cap.  An open
        # TOLLING_STARTED with no matching TOLLING_ENDED is the marker the
        # /resume-clock endpoint looks for.
        append_audit(
            subject_type="REQUEST",
            subject_id=req["id"],
            event_code="TOLLING_STARTED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"reason": reason, "started_at": iso_now(clock.now())},
        )
        store.bump(req)
    return ok_object(serialize_request(req))


# ---------- POST /foia/requests/{id}/resume-clock ----------
@requests_bp.post("/foia/requests/<rid>/resume-clock")
@require_auth({"Officer"})
def resume_clock(rid: str):
    req = _get_request(rid)
    with store.lock:
        if req["status"] != "ACKNOWLEDGED":
            raise ApiError(ERR_INVALID_STATE, 409, "Request is not in ACKNOWLEDGED.")
        # Find latest TOLLING_STARTED with no matching TOLLING_ENDED after it.
        entries = sorted(
            [
                e
                for e in store.audit_entries.values()
                if e["subject_type"] == "REQUEST" and e["subject_id"] == rid
            ],
            key=lambda e: e["created_at"],
        )
        latest_start = None
        for e in entries:
            if e["event_code"] == "TOLLING_STARTED":
                latest_start = e
            elif e["event_code"] == "TOLLING_ENDED":
                latest_start = None
        if latest_start is None:
            raise ApiError(ERR_INVALID_STATE, 409, "No open TOLLING_STARTED entry.")

        started_at_iso = latest_start["payload"].get("started_at") or latest_start["created_at"]
        elapsed = business_days_between(parse_iso(started_at_iso), clock.now())
        new_consumed = min(MAX_TOLL_DAYS, req["tolling_days_consumed"] + elapsed)
        req["tolling_days_consumed"] = new_consumed
        if req.get("filed_at"):
            req["response_due_at"] = _calc_response_deadline(req["filed_at"], new_consumed)
        store.bump(req)
        append_audit(
            subject_type="REQUEST",
            subject_id=req["id"],
            event_code="TOLLING_ENDED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={
                "elapsed_business_days": elapsed,
                "tolling_days_consumed": new_consumed,
                "response_due_at": req["response_due_at"],
            },
        )
    return ok_object(serialize_request(req))


# ---------- POST /foia/requests/{id}/start-search ----------
@requests_bp.post("/foia/requests/<rid>/start-search")
@require_auth({"Officer"})
def start_search(rid: str):
    req = _get_request(rid)
    with store.lock:
        if req["status"] != "ACKNOWLEDGED":
            raise ApiError(ERR_INVALID_STATE, 409, "Request is not in ACKNOWLEDGED.")
        fa = _fee_assessment_for_request(rid)
        if fa is not None:
            estimate = fa.get("estimate_total_cents", 0)
            if fa["status"] not in ("ACCEPTED", "WAIVED") and estimate > FREE_THRESHOLD_CENTS:
                raise ApiError(
                    ERR_FEE_NOT_RESOLVED,
                    422,
                    "Fee estimate exceeds free threshold and has not been accepted or waived.",
                )
        if req.get("fee_waiver_requested") and req.get("fee_waiver_granted") is None:
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Fee waiver requested but not yet adjudicated.",
            )
        req["status"] = "SEARCH"
        store.bump(req)
        append_audit(
            subject_type="REQUEST",
            subject_id=req["id"],
            event_code="SEARCH_STARTED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={},
        )
    return ok_object(serialize_request(req))


# ---------- POST /foia/requests/{id}/close-search ----------
@requests_bp.post("/foia/requests/<rid>/close-search")
@require_auth({"Officer"})
def close_search(rid: str):
    req = _get_request(rid)
    with store.lock:
        if req["status"] != "SEARCH":
            raise ApiError(ERR_INVALID_STATE, 409, "Request is not in SEARCH.")

        records = _records_for_request(rid)
        # Every record with contains_third_party_info == true needs a
        # terminal-state notice; and the record itself must carry a
        # non-null third_party_id.
        for rec in records:
            if rec.get("contains_third_party_info"):
                if not rec.get("third_party_id"):
                    raise ApiError(
                        ERR_MISSING_THIRD_PARTY_NOTICE,
                        422,
                        "Record marked third-party has no third_party_id.",
                    )
                rec_notices = _notices_for_record(rec["id"])
                if not rec_notices:
                    raise ApiError(
                        ERR_MISSING_THIRD_PARTY_NOTICE,
                        422,
                        "Third-party record missing notice.",
                    )
                if not any(
                    n["status"] in ("CONSENTED", "OBJECTED", "EXPIRED", "OVERRIDDEN")
                    for n in rec_notices
                ):
                    raise ApiError(
                        ERR_MISSING_THIRD_PARTY_NOTICE,
                        422,
                        "Third-party notice not yet resolved.",
                    )

        # Cascade: recompute final fee on the assessment.
        fa = _fee_assessment_for_request(rid)
        if fa is not None:
            requester = store.requesters[req["requester_id"]]
            tier = fa.get("tier_at_assessment") or requester["requester_tier"]
            chargeable_pages = sum_chargeable_pages(records)
            if fa["status"] == "WAIVED":
                fa["final_total_cents"] = 0
            else:
                fa["final_total_cents"] = calc_fee_final(
                    tier=tier,
                    actual_pages=chargeable_pages,
                    estimated_search_hours=float(fa["estimated_search_hours"]),
                    estimated_review_hours=float(fa["estimated_review_hours"]),
                    estimate_total_cents=int(fa.get("estimate_total_cents", 0)),
                )
            fa["status"] = "FINALIZED"
            store.bump(fa)

        req["status"] = "DETERMINATION_PENDING"
        store.bump(req)
        append_audit(
            subject_type="REQUEST",
            subject_id=req["id"],
            event_code="SEARCH_STARTED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"phase": "search_closed"},
        )
    return ok_object(serialize_request(req))


# ---------- POST /foia/requests/{id}/determine ----------
@requests_bp.post("/foia/requests/<rid>/determine")
@require_auth({"Officer"})
def determine(rid: str):
    req = _get_request(rid)
    with store.lock:
        if req["status"] != "DETERMINATION_PENDING":
            raise ApiError(ERR_INVALID_STATE, 409, "Request is not DETERMINATION_PENDING.")
        if req.get("glomar_invoked"):
            raise ApiError(ERR_INVALID_STATE, 409, "Glomar requests use /issue-glomar.")
        records = _records_for_request(rid)
        if not records:
            raise ApiError(
                ERR_NO_RESPONSIVE_RECORDS,
                422,
                "Determine requires at least one responsive record.",
            )

        dispositions = [r.get("disposition") for r in records]
        if any(d == "PENDING_REVIEW" for d in dispositions):
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "All records must have a final disposition before determination.",
            )

        all_released = all(d == "RELEASED_FULL" for d in dispositions)
        all_withheld = all(d == "WITHHELD_FULL" for d in dispositions)
        any_released = any(d in ("RELEASED_FULL", "RELEASED_REDACTED") for d in dispositions)
        any_withheld_or_redacted = any(d in ("RELEASED_REDACTED", "WITHHELD_FULL") for d in dispositions)

        if all_released:
            outcome = "RELEASED"
            new_status = "RELEASED"
        elif all_withheld:
            # Each WITHHELD_FULL record needs at least one ExemptionClaim.
            for rec in records:
                claims = [
                    c
                    for c in store.exemption_claims.values()
                    if c["record_id"] == rec["id"]
                ]
                if not claims:
                    raise ApiError(
                        ERR_INVALID_STATE,
                        409,
                        "WITHHELD_FULL record lacks an ExemptionClaim.",
                    )
            outcome = "DENIED"
            new_status = "DENIED"
        elif any_released and any_withheld_or_redacted:
            outcome = "PARTIAL_RELEASE"
            new_status = "PARTIAL_RELEASE"
        else:
            # Should not happen — leave a defensive branch.
            raise ApiError(ERR_INVALID_STATE, 409, "Indeterminate disposition mix.")

        now_iso = iso_now(clock.now())
        req["status"] = new_status
        req["determination_at"] = now_iso
        store.bump(req)
        append_audit(
            subject_type="REQUEST",
            subject_id=req["id"],
            event_code="DETERMINATION_ISSUED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"outcome": outcome},
        )

        # Auto-dismiss REMANDED appeals on this request (post-remand fresh
        # determination scenario, §3.9).
        for appeal in store.appeals.values():
            if appeal["request_id"] == rid and appeal["status"] == "REMANDED":
                appeal["status"] = "DISMISSED"
                store.bump(appeal)
                append_audit(
                    subject_type="APPEAL",
                    subject_id=appeal["id"],
                    event_code="APPEAL_DECIDED",
                    actor_role="system",
                    actor_id="system",
                    payload={"outcome": "DISMISSED", "reason": "fresh-determination"},
                )

    return ok_object(serialize_request(req))


# ---------- POST /foia/requests/{id}/issue-glomar ----------
@requests_bp.post("/foia/requests/<rid>/issue-glomar")
@require_auth({"Officer"})
def issue_glomar(rid: str):
    req = _get_request(rid)
    payload = require_json_body()
    basis = payload.get("glomar_exemption_basis")

    with store.lock:
        # PRD §3.10: ERR_INVALID_STATE is ordered above
        # ERR_INVALID_GLOMAR_BASIS in the validation priority.
        if req["status"] != "DETERMINATION_PENDING":
            raise ApiError(ERR_INVALID_STATE, 409, "Glomar issued from DETERMINATION_PENDING only.")
        if not isinstance(basis, list) or not basis:
            raise ApiError(
                ERR_INVALID_GLOMAR_BASIS,
                422,
                "glomar_exemption_basis must be a non-empty array.",
            )
        if len(basis) > 3:
            raise ApiError(
                ERR_INVALID_GLOMAR_BASIS,
                422,
                "glomar_exemption_basis may contain at most 3 entries.",
            )
        for code in basis:
            if code not in GLOMAR_ALLOWED_CODES:
                raise ApiError(
                    ERR_INVALID_GLOMAR_BASIS,
                    422,
                    f"Code {code!r} is not a permitted Glomar basis.",
                )
        records = _records_for_request(rid)
        if records:
            raise ApiError(
                ERR_GLOMAR_WITH_RECORDS,
                422,
                "Cannot issue Glomar while responsive records exist.",
            )
        now_iso = iso_now(clock.now())
        req["status"] = "GLOMAR_ISSUED"
        req["glomar_invoked"] = True
        req["glomar_exemption_basis"] = list(basis)
        req["determination_at"] = now_iso
        store.bump(req)
        append_audit(
            subject_type="REQUEST",
            subject_id=req["id"],
            event_code="GLOMAR_ISSUED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"glomar_exemption_basis": list(basis)},
        )
    return ok_object(serialize_request(req))


# ---------- POST /foia/requests/{id}/withdraw ----------
@requests_bp.post("/foia/requests/<rid>/withdraw")
@require_auth({"Requester"})
def withdraw(rid: str):
    req = _get_request(rid)
    with store.lock:
        if g.user_id != req["requester_id"]:
            raise ApiError(ERR_FORBIDDEN, 403, "Only the owning requester may withdraw.")
        if req["status"] not in ("INTAKE", "ACKNOWLEDGED", "SEARCH"):
            raise ApiError(ERR_INVALID_STATE, 409, "Cannot withdraw from this state.")
        req["status"] = "WITHDRAWN"
        store.bump(req)
        fa = _fee_assessment_for_request(rid)
        if fa is not None:
            fa["status"] = "WAIVED"
            store.bump(fa)
        append_audit(
            subject_type="REQUEST",
            subject_id=req["id"],
            event_code="DETERMINATION_ISSUED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"outcome": "WITHDRAWN"},
        )
    return ok_object(serialize_request(req))


# ---------- POST /foia/requests/{id}/resume-search ----------
@requests_bp.post("/foia/requests/<rid>/resume-search")
@require_auth({"Officer"})
def resume_search(rid: str):
    req = _get_request(rid)
    with store.lock:
        if req["status"] != "REOPENED_BY_APPEAL":
            raise ApiError(ERR_INVALID_STATE, 409, "Request is not REOPENED_BY_APPEAL.")
        req["status"] = "SEARCH"
        store.bump(req)
        append_audit(
            subject_type="REQUEST",
            subject_id=req["id"],
            event_code="SEARCH_STARTED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={"cycle": "post-remand"},
        )
    return ok_object(serialize_request(req))
