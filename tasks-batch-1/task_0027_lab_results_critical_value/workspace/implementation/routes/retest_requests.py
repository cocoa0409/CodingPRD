"""RetestRequest routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_STATE
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields, require_enum, lookup_or_404,
)


bp = Blueprint("retest_requests", __name__)

RETEST_REASONS = {"DELTA_CHECK_FAIL", "CLINICIAN_DOUBT", "INSTRUMENT_QC_FAIL"}


# ---------- POST /results/{id}/retest-requests ---------------------------

@bp.post("/results/<rid>/retest-requests")
def open_retest(rid):
    require_auth(["OrderingProvider"])()
    r = lookup_or_404(db.results, rid, "Result")
    body = get_json_body()
    require_fields(body, ["reason"])
    reason = body["reason"]
    require_enum(reason, RETEST_REASONS, "reason")

    if r.get("status") not in ("RELEASED", "AMENDED"):
        raise APIError(ERR_INVALID_STATE, 409,
                       "Retest may only target a RELEASED or AMENDED Result")

    rr = {
        "original_result_id": rid,
        "new_order_id": None,
        "reason": reason,
        "status": "REQUESTED",
    }
    db.stamp_common(rr)
    db.retest_requests[rr["id"]] = rr
    return ok_object(rr, http_status=201)


# ---------- GET /retest-requests/{id} ------------------------------------

@bp.get("/retest-requests/<tid>")
def get_retest(tid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    rr = lookup_or_404(db.retest_requests, tid, "RetestRequest")
    return ok_object(rr)


# ---------- GET /retest-requests -----------------------------------------

@bp.get("/retest-requests")
def list_retests():
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    limit, offset = paginate_params(request.args)
    items = list(db.retest_requests.values())
    for key in ("original_result_id", "new_order_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [rr for rr in items if rr.get(key) == val]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------- POST /retest-requests/{id}/schedule --------------------------

@bp.post("/retest-requests/<tid>/schedule")
def schedule_retest(tid):
    require_auth(["LabTech"])()
    rr = lookup_or_404(db.retest_requests, tid, "RetestRequest")
    if rr.get("status") != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"RetestRequest.status '{rr.get('status')}' is not REQUESTED")

    original = db.results.get(rr["original_result_id"])
    if original is None:
        raise APIError(ERR_INVALID_STATE, 409,
                       "Original result no longer exists")
    if original.get("status") not in ("RELEASED", "AMENDED"):
        raise APIError(ERR_INVALID_STATE, 409,
                       "Original result must be RELEASED or AMENDED")

    original_order = db.lab_orders.get(original.get("lab_order_id"))
    if original_order is None:
        raise APIError(ERR_INVALID_STATE, 409,
                       "Original lab order no longer exists")

    # Auto-create the fresh LabOrder with priority=STAT.
    new_order = {
        "patient_id": original_order["patient_id"],
        "ordering_clinician_id": original_order["ordering_clinician_id"],
        "panel_code": original_order["panel_code"],
        "priority": "STAT",
        "status": "DRAFT",
        "ordered_at": db.get_current_utc_iso(),
        "specimens_count": 0,
        "accessioned_count": 0,
        "turn_around_time_minutes": None,
        "compliance_incident": False,
    }
    db.stamp_common(new_order)
    db.lab_orders[new_order["id"]] = new_order

    rr["new_order_id"] = new_order["id"]
    rr["status"] = "SCHEDULED"
    db.bump(rr)
    return ok_object(rr)


# ---------- POST /retest-requests/{id}/cancel ----------------------------

@bp.post("/retest-requests/<tid>/cancel")
def cancel_retest(tid):
    require_auth(["OrderingProvider"])()
    rr = lookup_or_404(db.retest_requests, tid, "RetestRequest")
    if rr.get("status") != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"RetestRequest.status '{rr.get('status')}' is not REQUESTED")
    rr["status"] = "CANCELLED"
    db.bump(rr)
    return ok_object(rr)


# A scaffold-mentioned transition SCHEDULED->COMPLETED via POST .../complete is
# referenced but not in the §1.5 endpoint table; we expose it for completeness
# so test harnesses that reach the COMPLETED terminal state have a way to do so.
@bp.post("/retest-requests/<tid>/complete")
def complete_retest(tid):
    require_auth(["LabTech"])()
    rr = lookup_or_404(db.retest_requests, tid, "RetestRequest")
    if rr.get("status") != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"RetestRequest.status '{rr.get('status')}' is not SCHEDULED")
    new_order = db.lab_orders.get(rr.get("new_order_id"))
    if new_order is None or new_order.get("status") != "RESULTED":
        raise APIError(ERR_INVALID_STATE, 409,
                       "New lab order must be RESULTED before completing the retest")
    rr["status"] = "COMPLETED"
    db.bump(rr)
    return ok_object(rr)
