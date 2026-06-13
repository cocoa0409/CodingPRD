"""Timesheet routes (PRD 3.6)."""

from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import (
    get_user_context, require_role, get_json_body, parse_pagination, paginate,
)
from response import object_response, array_response
from services import common, serialize, recompute, ownership, calc

bp = Blueprint("timesheets", __name__)

TIMESHEET_TARGETS = {"SUBMITTED", "APPROVED", "REJECTED", "DRAFT"}


def _compute_money(ts, placement):
    hours = ts["hours"]
    ts["pay_cents"] = calc.timesheet_pay(hours, placement["pay_rate_cents"])
    ts["bill_cents"] = calc.timesheet_bill(hours, placement["bill_rate_cents"])
    ts["margin_cents"] = ts["bill_cents"] - ts["pay_cents"]


def _weeks_overlap_halfopen(s1, e1, s2, e2):
    """Half-open [s,e) overlap: adjacency at a shared boundary is allowed; only
    interior overlap conflicts (PRD 3.6). Overlap iff s1 < e2 and s2 < e1."""
    return s1 < e2 and s2 < e1


@bp.route("/staffing/timesheets", methods=["POST"])
def create_timesheet():
    user_id, role = get_user_context()
    require_role(role, {"Candidate", "Recruiter"})
    body = get_json_body()

    placement_id = common.require_str(body, "placement_id")
    week_start = common.require_str(body, "week_start")
    week_end = common.require_str(body, "week_end")
    hours = common.require_number(body, "hours")

    # Priority 3 existence (before priority-4 range checks).
    placement = common.get_or_404(db.placements, placement_id, errors.ERR_PLACEMENT_NOT_FOUND)

    # Ownership: a Candidate may only create timesheets on its own placements.
    if role == "Candidate":
        ownership.candidate_owns_placement(user_id, placement)

    # Priority 4 structural checks.
    ws_dt = common._parse_dt(week_start)
    we_dt = common._parse_dt(week_end)
    if not (we_dt > ws_dt):
        raise ApiError(errors.ERR_VALIDATION, 422, "week_end must be after week_start.")
    if not (hours > 0):
        raise ApiError(errors.ERR_VALIDATION, 422, "hours must be > 0.")

    # State: placement must be ACTIVE.
    if placement["assignment_status"] != "ACTIVE":
        raise ApiError(errors.ERR_PLACEMENT_NOT_ACTIVE, 409, "Placement is not ACTIVE.")

    # Week-overlap (priority 10) vs non-REJECTED timesheets of same placement.
    for ts in db.timesheets.values():
        if ts["placement_id"] == placement_id and ts["status"] != "REJECTED":
            o_s = common._parse_dt(ts["week_start"])
            o_e = common._parse_dt(ts["week_end"])
            if _weeks_overlap_halfopen(ws_dt, we_dt, o_s, o_e):
                raise ApiError(errors.ERR_TIMESHEET_WEEK_OVERLAP, 409, "Timesheet week overlaps.")

    rec = common.init_mutable({
        "placement_id": placement_id,
        "week_start": week_start,
        "week_end": week_end,
        "hours": hours,
        "status": "DRAFT",
        "invoice_id": None,
    })
    _compute_money(rec, placement)
    db.timesheets[rec["id"]] = rec
    return object_response(serialize.timesheet(rec), 201)


@bp.route("/staffing/timesheets", methods=["GET"])
def list_timesheets():
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client", "Candidate"})
    limit, offset = parse_pagination()

    placement_filter = request.args.get("placement_id")
    invoice_filter = request.args.get("invoice_id")
    status_filter = request.args.get("status")

    rows = list(db.timesheets.values())
    if placement_filter is not None:
        rows = [r for r in rows if r["placement_id"] == placement_filter]
    if invoice_filter is not None:
        rows = [r for r in rows if r.get("invoice_id") == invoice_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if role == "Client":
        rows = [r for r in rows if ownership.timesheet_client(r) == user_id]
    elif role == "Candidate":
        rows = [r for r in rows if _candidate_owns(user_id, r)]

    page, total = paginate(rows, limit, offset)
    return array_response([serialize.timesheet(r) for r in page], limit, offset, total)


def _candidate_owns(user_id, timesheet):
    pl = db.placements.get(timesheet["placement_id"])
    return pl is not None and pl["candidate_id"] == user_id


@bp.route("/staffing/timesheets/<tid>", methods=["GET"])
def get_timesheet(tid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client", "Candidate"})
    rec = common.get_or_404(db.timesheets, tid, errors.ERR_TIMESHEET_NOT_FOUND)
    if role == "Client":
        ownership.client_owns(user_id, ownership.timesheet_client(rec))
    elif role == "Candidate":
        ownership.candidate_owns_timesheet(user_id, rec)
    return object_response(serialize.timesheet(rec), 200)


@bp.route("/staffing/timesheets/<tid>", methods=["PATCH"])
def patch_timesheet(tid):
    user_id, role = get_user_context()
    require_role(role, {"Candidate", "Client"})
    rec = common.get_or_404(db.timesheets, tid, errors.ERR_TIMESHEET_NOT_FOUND)
    body = get_json_body()
    target = common.require_enum(body, "target_status", TIMESHEET_TARGETS)

    # RBAC by target (PRD 3.6 / roles matrix):
    #   Candidate: SUBMITTED (submit), DRAFT (revise)
    #   Client:    APPROVED, REJECTED
    candidate_targets = {"SUBMITTED", "DRAFT"}
    client_targets = {"APPROVED", "REJECTED"}
    if target in candidate_targets:
        require_role(role, {"Candidate"})
        ownership.candidate_owns_timesheet(user_id, rec)
    elif target in client_targets:
        require_role(role, {"Client"})
        ownership.client_owns(user_id, ownership.timesheet_client(rec))

    status = rec["status"]
    placement = db.placements.get(rec["placement_id"])

    if target == "SUBMITTED":
        if status != "DRAFT":
            raise ApiError(errors.ERR_TIMESHEET_BAD_STATE, 409, "Timesheet is not DRAFT.")
        rec["status"] = "SUBMITTED"
        common.touch(rec)

    elif target == "APPROVED":
        if status != "SUBMITTED":
            raise ApiError(errors.ERR_TIMESHEET_BAD_STATE, 409, "Timesheet is not SUBMITTED.")
        rec["status"] = "APPROVED"
        common.touch(rec)
        # Side effect: placement.actual_margin_cents += this margin (counted
        # once at APPROVED). Recompute from the APPROVED/INVOICED set keeps it
        # exact and order-stable.
        if placement is not None:
            recompute.recompute_actual_margin(placement)

    elif target == "REJECTED":
        if status != "SUBMITTED":
            raise ApiError(errors.ERR_TIMESHEET_BAD_STATE, 409, "Timesheet is not SUBMITTED.")
        rec["status"] = "REJECTED"
        common.touch(rec)

    elif target == "DRAFT":
        if status != "REJECTED":
            raise ApiError(errors.ERR_TIMESHEET_BAD_STATE, 409, "Timesheet is not REJECTED.")
        # Revise: may carry a new hours value; recompute money if so.
        if "hours" in body and body["hours"] is not None:
            new_hours = common.require_number(body, "hours")
            if not (new_hours > 0):
                raise ApiError(errors.ERR_VALIDATION, 422, "hours must be > 0.")
            rec["hours"] = new_hours
            if placement is not None:
                _compute_money(rec, placement)
        rec["status"] = "DRAFT"
        common.touch(rec)

    return object_response(serialize.timesheet(rec), 200)
