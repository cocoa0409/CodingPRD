"""RFE endpoints: issue, list, get, respond."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_RFE_CAP_EXCEEDED,
    ERR_RFE_DEADLINE_PASSED,
    ERR_STALE_VERSION,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields,
    lookup_or_404,
    ensure_case_ownership,
)
from services.events import append_event
from services.calculations import (
    compute_rfe_deadline,
    MAX_RFE_ROUNDS,
    TERMINAL_CASE_STATES,
)


bp = Blueprint("rfes", __name__)


ALL_ROLES = ["Applicant", "Attorney", "Officer", "FieldOfficeAdmin"]


# ---------- POST /uscis/cases/{id}/rfes -------------------------------------

@bp.post("/uscis/cases/<rid>/rfes")
def issue_rfe(rid: str):
    require_auth(["Officer"])()
    case = lookup_or_404(db.cases, rid, "Case")

    if case.get("status") in TERMINAL_CASE_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Case is already terminal")
    if case.get("status") != "UNDER_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, f"Case must be UNDER_REVIEW (was {case.get('status')})")

    if case.get("rfe_round_count", 0) >= MAX_RFE_ROUNDS:
        raise APIError(ERR_RFE_CAP_EXCEEDED, 422, "RFE cap exceeded")

    body = get_json_body()
    require_fields(body, ["evidence_items_requested"])
    items = body["evidence_items_requested"]
    if not isinstance(items, list) or len(items) < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "evidence_items_requested must be a non-empty array")
    for it in items:
        if not isinstance(it, str):
            raise APIError(ERR_INVALID_REQUEST, 400, "evidence_items_requested must contain strings")

    issued_at = db.get_current_utc()
    deadline = compute_rfe_deadline(issued_at)

    rfe = {
        "case_id": case["id"],
        "issued_at": issued_at,
        "response_deadline": deadline,
        "evidence_items_requested": items,
        "status": "ISSUED",
        "responded_at": None,
    }
    db.stamp_common(rfe)
    db.rfes[rfe["id"]] = rfe

    case["rfe_round_count"] = case.get("rfe_round_count", 0) + 1
    prior = case["status"]
    case["status"] = "RFE_PENDING"
    db.bump(case)

    append_event(
        case["id"],
        "RFE_ISSUED",
        payload_json={"rfe_id": rfe["id"], "deadline": deadline},
    )
    append_event(case["id"], "STATUS_CHANGE", from_status=prior, to_status="RFE_PENDING")
    return ok_object(rfe, 201)


# ---------- GET /uscis/cases/{id}/rfes --------------------------------------

@bp.get("/uscis/cases/<rid>/rfes")
def list_case_rfes(rid: str):
    require_auth(ALL_ROLES)()
    case = lookup_or_404(db.cases, rid, "Case")
    ensure_case_ownership(case, current_role(), current_user_id())
    limit, offset = paginate_params(request.args)
    items = [r for r in db.rfes.values() if r.get("case_id") == rid]
    items.sort(key=lambda r: r.get("created_at", ""))
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


# ---------- GET /uscis/rfes/{id} --------------------------------------------

@bp.get("/uscis/rfes/<rid>")
def get_rfe(rid: str):
    require_auth(ALL_ROLES)()
    rfe = lookup_or_404(db.rfes, rid, "RFE")
    return ok_object(rfe, 200)


# ---------- POST /uscis/rfes/{id}/respond -----------------------------------

@bp.post("/uscis/rfes/<rid>/respond")
def respond_rfe(rid: str):
    require_auth(["Applicant", "Attorney"])()
    rfe = lookup_or_404(db.rfes, rid, "RFE")
    case = db.cases.get(rfe.get("case_id"))
    if case is None:
        raise APIError(ERR_INVALID_STATE, 409, "Parent case missing")
    ensure_case_ownership(case, current_role(), current_user_id())

    if rfe.get("status") in ("RESPONDED", "EXPIRED"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "RFE already terminal")
    if rfe.get("status") != "ISSUED":
        raise APIError(ERR_INVALID_STATE, 409, f"RFE must be ISSUED (was {rfe.get('status')})")
    if case.get("status") != "RFE_PENDING":
        raise APIError(ERR_INVALID_STATE, 409, f"Parent case must be RFE_PENDING (was {case.get('status')})")

    body = get_json_body()
    require_fields(body, ["expected_case_version", "response_summary"])
    expected_version = body["expected_case_version"]
    response_summary = body["response_summary"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_case_version must be integer")
    if not isinstance(response_summary, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "response_summary must be a string")

    # Deadline check: strict less-than. The PRD §3.6 deadline is a date; the
    # clock is a timestamp. We treat now's calendar-date portion against the
    # deadline date: 'now_date < deadline_date' is the strict less-than rule.
    now_iso = db.get_current_utc()
    now_date = now_iso[:10]
    deadline = rfe.get("response_deadline")
    if now_date >= deadline:
        raise APIError(ERR_RFE_DEADLINE_PASSED, 422, "Response deadline has passed")

    # OCC check — priority §2.11 places this last.
    if expected_version != case.get("version"):
        raise APIError(ERR_STALE_VERSION, 412, "Case version has advanced")

    rfe["status"] = "RESPONDED"
    rfe["responded_at"] = now_iso
    db.bump(rfe)

    prior = case["status"]
    case["status"] = "UNDER_REVIEW"  # rfe_round_count is NOT reset.
    db.bump(case)
    append_event(case["id"], "RFE_RESPONDED", payload_json={"rfe_id": rfe["id"]})
    append_event(case["id"], "STATUS_CHANGE", from_status=prior, to_status="UNDER_REVIEW")
    return ok_object(rfe, 200)
