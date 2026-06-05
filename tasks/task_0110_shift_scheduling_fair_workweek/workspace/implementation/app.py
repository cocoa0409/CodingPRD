"""Shift Scheduling & Fair Workweek API — entry point + all routes.

Python + Flask, in-memory store, server-held logical clock. Store starts EMPTY
on every boot (no seeding). See PRD.md for the contract.
"""
import os

from flask import Flask, request

import clock
import db
from errors import ApiError
from middleware import authenticate, require_role, ROLE_MANAGER, ROLE_WORKER
from response import object_response, array_response
from serialize import view
from util import (
    get_json_body, require_fields, parse_utc, require_int, require_number,
    require_string, optional_bool, optional_number, optional_int, optional_string,
    pagination_params, paginate, sort_by_created, hours_between,
)
from services import scheduling as sched

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling — every ApiError renders the standard error envelope.
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _error_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    from flask import jsonify
    return jsonify(body), err.http_status


def _error_meta():
    import random
    import string
    from clock import now_iso
    return {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_iso(),
    }


@app.errorhandler(404)
def handle_404(_e):
    err = ApiError("ERR_NOT_FOUND")
    return handle_api_error(err)


@app.errorhandler(405)
def handle_405(_e):
    err = ApiError("ERR_NOT_FOUND")
    return handle_api_error(err)


# ---------------------------------------------------------------------------
# Existence lookups (PRD §2.6: validate path/body ids left-to-right).
# ---------------------------------------------------------------------------
def get_location_or_404(loc_id):
    rec = db.locations.get(loc_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def get_worker_or_404(worker_id):
    rec = db.workers.get(worker_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def get_shift_or_404(shift_id):
    rec = db.shifts.get(shift_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def get_assignment_or_404(asg_id):
    rec = db.assignments.get(asg_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def get_bid_or_404(bid_id):
    rec = db.bids.get(bid_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def get_swap_or_404(swap_id):
    rec = db.swaps.get(swap_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def get_time_off_or_404(to_id):
    rec = db.time_off_requests.get(to_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def get_template_or_404(tpl_id):
    rec = db.shift_templates.get(tpl_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def get_pay_period_or_404(pp_id):
    rec = db.pay_periods.get(pp_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def list_response(entity_type, records):
    """Sort by created_at ASC, paginate, render array envelope."""
    limit, offset = pagination_params()
    ordered = sort_by_created(records)
    page, total = paginate(ordered, limit, offset)
    items = [view(entity_type, r) for r in page]
    return array_response(items, limit, offset, total)


# ===========================================================================
# Location
# ===========================================================================
@app.route("/locations", methods=["POST"])
def create_location():
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    body = get_json_body()
    require_fields(body, ["name", "time_zone", "overtime_cost_guardrail_cents"])
    name = require_string(body, "name")
    time_zone = require_string(body, "time_zone")
    guardrail = require_int(body, "overtime_cost_guardrail_cents")
    rec = db.common_fields()
    rec.update({
        "name": name,
        "time_zone": time_zone,
        "predictability_pay_enabled": optional_bool(body, "predictability_pay_enabled", True),
        "advance_notice_days": optional_int(body, "advance_notice_days", 14),
        "min_rest_hours_between_shifts": optional_int(body, "min_rest_hours_between_shifts", 10),
        "overtime_weekly_threshold_hours": optional_number(body, "overtime_weekly_threshold_hours", 40),
        "overtime_multiplier": optional_number(body, "overtime_multiplier", 1.5),
        "overtime_cost_guardrail_cents": guardrail,
        "status": "ACTIVE",
    })
    db.locations[rec["id"]] = rec
    return object_response(view("Location", rec), 201)


@app.route("/locations/<loc_id>", methods=["GET"])
def get_location(loc_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    rec = get_location_or_404(loc_id)
    return object_response(view("Location", rec))


# ===========================================================================
# Worker
# ===========================================================================
@app.route("/locations/<loc_id>/workers", methods=["POST"])
def create_worker(loc_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    body = get_json_body()
    require_fields(body, ["full_name", "email", "base_hourly_rate_cents"])
    rec = db.common_fields()
    rec.update({
        "location_id": loc["id"],
        "full_name": require_string(body, "full_name"),
        "email": require_string(body, "email"),
        "is_minor": optional_bool(body, "is_minor", False),
        "minor_daily_cap_hours": optional_number(body, "minor_daily_cap_hours", 8),
        "minor_weekly_cap_hours": optional_number(body, "minor_weekly_cap_hours", 18),
        "base_hourly_rate_cents": require_int(body, "base_hourly_rate_cents"),
        "no_show_strikes": 0,
        "status": "ACTIVE",
    })
    db.workers[rec["id"]] = rec
    return object_response(view("Worker", rec), 201)


@app.route("/locations/<loc_id>/workers", methods=["GET"])
def list_location_workers(loc_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    get_location_or_404(loc_id)
    records = [w for w in db.workers.values() if w["location_id"] == loc_id]
    return list_response("Worker", records)


@app.route("/workers/<worker_id>", methods=["GET"])
def get_worker(worker_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    rec = get_worker_or_404(worker_id)
    return object_response(view("Worker", rec))


# ===========================================================================
# Availability
# ===========================================================================
@app.route("/workers/<worker_id>/availability", methods=["POST"])
def create_availability(worker_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    worker = get_worker_or_404(worker_id)
    body = get_json_body()
    require_fields(body, ["kind", "start_utc", "end_utc"])
    kind = require_string(body, "kind")
    if kind not in ("AVAILABLE", "UNAVAILABLE"):
        raise ApiError("ERR_INVALID_REQUEST", "kind must be AVAILABLE or UNAVAILABLE.")
    start = parse_utc(body["start_utc"], "start_utc")
    end = parse_utc(body["end_utc"], "end_utc")
    if not (end > start):
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    rec = db.common_fields()
    rec.update({
        "worker_id": worker["id"],
        "kind": kind,
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
    })
    db.availabilities[rec["id"]] = rec
    return object_response(view("Availability", rec), 201)


@app.route("/workers/<worker_id>/availability", methods=["GET"])
def list_availability(worker_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    get_worker_or_404(worker_id)
    records = [a for a in db.availabilities.values() if a["worker_id"] == worker_id]
    return list_response("Availability", records)


# ===========================================================================
# Time-off
# ===========================================================================
@app.route("/workers/<worker_id>/time-off", methods=["POST"])
def create_time_off(worker_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    worker = get_worker_or_404(worker_id)
    # Worker may only submit against their own record (ownership).
    if uid != worker["id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    body = get_json_body()
    require_fields(body, ["start_utc", "end_utc", "reason"])
    start = parse_utc(body["start_utc"], "start_utc")
    end = parse_utc(body["end_utc"], "end_utc")
    reason = require_string(body, "reason")
    if not (end > start):
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    rec = db.common_fields()
    rec.update({
        "worker_id": worker["id"],
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "reason": reason,
        "status": "PENDING",
        "decided_by_manager_id": None,
    })
    db.time_off_requests[rec["id"]] = rec
    return object_response(view("TimeOffRequest", rec), 201)


@app.route("/workers/<worker_id>/time-off", methods=["GET"])
def list_time_off(worker_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    get_worker_or_404(worker_id)
    records = [t for t in db.time_off_requests.values() if t["worker_id"] == worker_id]
    return list_response("TimeOffRequest", records)


@app.route("/locations/<loc_id>/time-off/<to_id>/approve", methods=["POST"])
def approve_time_off(loc_id, to_id):
    uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    get_location_or_404(loc_id)
    to = get_time_off_or_404(to_id)
    if to["status"] != "PENDING":
        raise ApiError("ERR_INVALID_TIME_OFF_STATE")
    # No SCHEDULED/CONFIRMED assignment overlaps [start,end) half-open.
    t_start = parse_utc(to["start_utc"])
    t_end = parse_utc(to["end_utc"])
    for a in db.assignments.values():
        if a["worker_id"] != to["worker_id"]:
            continue
        if a["status"] not in sched.SCHEDULED_OR_CONFIRMED:
            continue
        s = db.shifts[a["shift_id"]]
        if sched.overlaps_half_open(t_start, t_end, sched.shift_start(s), sched.shift_end(s)):
            raise ApiError("ERR_TIME_OFF_CONFLICTS_ASSIGNMENT")
    to["status"] = "APPROVED"
    to["decided_by_manager_id"] = uid
    db.touch(to)
    return object_response(view("TimeOffRequest", to))


@app.route("/locations/<loc_id>/time-off/<to_id>/deny", methods=["POST"])
def deny_time_off(loc_id, to_id):
    uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    get_location_or_404(loc_id)
    to = get_time_off_or_404(to_id)
    if to["status"] != "PENDING":
        raise ApiError("ERR_INVALID_TIME_OFF_STATE")
    to["status"] = "DENIED"
    to["decided_by_manager_id"] = uid
    db.touch(to)
    return object_response(view("TimeOffRequest", to))


@app.route("/locations/<loc_id>/time-off/<to_id>/cancel", methods=["POST"])
def cancel_time_off(loc_id, to_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    to = get_time_off_or_404(to_id)
    if to["status"] != "PENDING":
        raise ApiError("ERR_INVALID_TIME_OFF_STATE")
    if uid != to["worker_id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    to["status"] = "CANCELLED"
    db.touch(to)
    return object_response(view("TimeOffRequest", to))


# ===========================================================================
# ShiftTemplate + generation
# ===========================================================================
@app.route("/locations/<loc_id>/shift-templates", methods=["POST"])
def create_template(loc_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    body = get_json_body()
    require_fields(body, ["role_name", "weekday", "local_start_minute",
                          "duration_minutes", "forecast_headcount"])
    role_name = require_string(body, "role_name")
    weekday = require_int(body, "weekday")
    if weekday < 0 or weekday > 6:
        raise ApiError("ERR_INVALID_REQUEST", "weekday must be 0..6.")
    local_start_minute = require_int(body, "local_start_minute")
    if local_start_minute < 0 or local_start_minute > 1439:
        raise ApiError("ERR_INVALID_REQUEST", "local_start_minute must be 0..1439.")
    duration_minutes = require_int(body, "duration_minutes")
    if duration_minutes <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "duration_minutes must be > 0.")
    forecast_headcount = require_int(body, "forecast_headcount")
    if forecast_headcount < 1:
        raise ApiError("ERR_INVALID_REQUEST", "forecast_headcount must be >= 1.")
    rec = db.common_fields()
    rec.update({
        "location_id": loc["id"],
        "role_name": role_name,
        "weekday": weekday,
        "local_start_minute": local_start_minute,
        "duration_minutes": duration_minutes,
        "forecast_headcount": forecast_headcount,
    })
    db.shift_templates[rec["id"]] = rec
    return object_response(view("ShiftTemplate", rec), 201)


@app.route("/locations/<loc_id>/shift-templates", methods=["GET"])
def list_templates(loc_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    get_location_or_404(loc_id)
    records = [t for t in db.shift_templates.values() if t["location_id"] == loc_id]
    return list_response("ShiftTemplate", records)


@app.route("/locations/<loc_id>/shift-templates/<tpl_id>/generate", methods=["POST"])
def generate_shift(loc_id, tpl_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    tpl = get_template_or_404(tpl_id)
    body = get_json_body()
    require_fields(body, ["week_start_local_date"])
    week_start = require_string(body, "week_start_local_date")
    start_utc, end_utc = _resolve_template_instants(tpl, loc, week_start)
    rec = db.common_fields()
    rec.update({
        "location_id": loc["id"],
        "template_id": tpl["id"],
        "role_name": tpl["role_name"],
        "start_utc": start_utc,
        "end_utc": end_utc,
        "headcount_required": tpl["forecast_headcount"],
        "posted_utc": None,
        "status": "DRAFT",
    })
    _stamp_shift_computed(rec)
    db.shifts[rec["id"]] = rec
    return object_response(view("Shift", rec), 201)


def _resolve_template_instants(tpl, loc, week_start_local_date):
    """Resolve the template's weekday + local_start_minute + duration against the
    location-local calendar for the given week-start date -> UTC instant strings."""
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo
    try:
        base = date.fromisoformat(week_start_local_date)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "week_start_local_date must be YYYY-MM-DD.")
    tz = ZoneInfo(loc["time_zone"])
    # week_start_local_date is treated as the Monday (weekday 0) of the week;
    # add the template's weekday offset to land on the target local day.
    target_day = base + timedelta(days=tpl["weekday"])
    minute = tpl["local_start_minute"]
    local_start = datetime(target_day.year, target_day.month, target_day.day,
                           minute // 60, minute % 60, tzinfo=tz)
    local_end = local_start + timedelta(minutes=tpl["duration_minutes"])
    start_utc = local_start.astimezone(ZoneInfo("UTC"))
    end_utc = local_end.astimezone(ZoneInfo("UTC"))
    from util import to_iso_millis
    return to_iso_millis(start_utc), to_iso_millis(end_utc)


def _stamp_shift_computed(rec):
    rec["duration_hours"] = sched.shift_duration_hours(rec)
    rec["headcount_filled"] = sched.headcount_filled(rec)


# ===========================================================================
# Shift
# ===========================================================================
@app.route("/locations/<loc_id>/shifts", methods=["POST"])
def create_shift(loc_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    body = get_json_body()
    require_fields(body, ["role_name", "start_utc", "end_utc", "headcount_required"])
    role_name = require_string(body, "role_name")
    start = parse_utc(body["start_utc"], "start_utc")
    end = parse_utc(body["end_utc"], "end_utc")
    headcount = require_int(body, "headcount_required")
    if headcount < 1:
        raise ApiError("ERR_INVALID_REQUEST", "headcount_required must be >= 1.")
    template_id = optional_string(body, "template_id", None)
    if template_id is not None and template_id not in db.shift_templates:
        raise ApiError("ERR_NOT_FOUND")
    if not (end > start):
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    rec = db.common_fields()
    rec.update({
        "location_id": loc["id"],
        "template_id": template_id,
        "role_name": role_name,
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "headcount_required": headcount,
        "posted_utc": None,
        "status": "DRAFT",
    })
    _stamp_shift_computed(rec)
    db.shifts[rec["id"]] = rec
    return object_response(view("Shift", rec), 201)


@app.route("/shifts", methods=["GET"])
def list_shifts():
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    loc_filter = request.args.get("location_id")
    tpl_filter = request.args.get("template_id")
    records = []
    for s in db.shifts.values():
        if loc_filter is not None and s["location_id"] != loc_filter:
            continue
        if tpl_filter is not None and s["template_id"] != tpl_filter:
            continue
        records.append(s)
    return list_response("Shift", records)


@app.route("/shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    rec = get_shift_or_404(shift_id)
    _stamp_shift_computed(rec)
    return object_response(view("Shift", rec))


@app.route("/locations/<loc_id>/shifts/<shift_id>/post", methods=["POST"])
def post_shift(loc_id, shift_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    get_location_or_404(loc_id)
    shift = get_shift_or_404(shift_id)
    if shift["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SHIFT_STATE")
    if not (sched.shift_end(shift) > sched.shift_start(shift)):
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    from util import to_iso_millis
    shift["posted_utc"] = to_iso_millis(clock.now())
    shift["status"] = "OPEN"
    db.touch(shift)
    _stamp_shift_computed(shift)
    return object_response(view("Shift", shift))


@app.route("/locations/<loc_id>/shifts/<shift_id>/cancel", methods=["POST"])
def cancel_shift(loc_id, shift_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    shift = get_shift_or_404(shift_id)
    if shift["status"] not in ("DRAFT", "OPEN", "FULLY_STAFFED"):
        raise ApiError("ERR_INVALID_SHIFT_STATE")

    was_active = shift["status"] in ("OPEN", "FULLY_STAFFED")
    within_window = sched.within_advance_notice_window(shift, loc)

    shift["status"] = "CANCELLED"
    db.touch(shift)

    if was_active:
        affected_pps = set()
        for a in list(db.assignments.values()):
            if a["shift_id"] != shift["id"]:
                continue
            if a["status"] not in sched.NON_TERMINAL_ASSIGNMENT:
                continue
            worker = db.workers[a["worker_id"]]
            pp = db.pay_periods.get(a["pay_period_id"])
            a["status"] = "CANCELLED"
            db.touch(a)
            if pp is not None:
                affected_pps.add(pp["id"])
            # Short-notice cancel accrual per held worker.
            if within_window and pp is not None:
                sched.accrue_short_notice_cancel(shift, worker, loc, pp)
        # Reject still-SUBMITTED bids.
        sched.reject_submitted_bids(shift)
        # Reconcile each affected pay-period.
        for pp_id in affected_pps:
            sched.reconcile_pay_period(db.pay_periods[pp_id])

    _stamp_shift_computed(shift)
    return object_response(view("Shift", shift))


@app.route("/locations/<loc_id>/shifts/<shift_id>/complete", methods=["POST"])
def complete_shift(loc_id, shift_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    shift = get_shift_or_404(shift_id)
    if shift["status"] not in ("OPEN", "FULLY_STAFFED"):
        raise ApiError("ERR_INVALID_SHIFT_STATE")
    if not (clock.now() >= sched.shift_end(shift)):
        raise ApiError("ERR_SHIFT_NOT_ENDED")

    shift["status"] = "COMPLETED"
    db.touch(shift)

    affected_pps = set()
    for a in list(db.assignments.values()):
        if a["shift_id"] != shift["id"]:
            continue
        if a["status"] not in sched.SCHEDULED_OR_CONFIRMED:
            continue
        a["status"] = "COMPLETED"
        worker = db.workers[a["worker_id"]]
        a["finalized_cost_cents"] = sched.compute_finalized_cost(a, shift, worker, loc)
        db.touch(a)
        if a["pay_period_id"] in db.pay_periods:
            affected_pps.add(a["pay_period_id"])
    for pp_id in affected_pps:
        sched.reconcile_pay_period(db.pay_periods[pp_id])

    _stamp_shift_computed(shift)
    return object_response(view("Shift", shift))


# ===========================================================================
# Assignment (direct + lifecycle)
# ===========================================================================
@app.route("/locations/<loc_id>/assignments", methods=["POST"])
def create_assignment(loc_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    body = get_json_body()
    require_fields(body, ["shift_id", "worker_id"])
    shift = get_shift_or_404(body["shift_id"])
    worker = get_worker_or_404(body["worker_id"])
    force = optional_bool(body, "force_over_guardrail", False)
    # State precondition (§3.4/§3.5): a direct assignment targets a *posted*,
    # non-terminal shift. Posting makes a shift "eligible for bidding and
    # assignment" (§3.4), so DRAFT (un-posted) and the terminal COMPLETED/
    # CANCELLED states are invalid -> ERR_INVALID_SHIFT_STATE. A FULLY_STAFFED
    # shift is posted and non-terminal; the PRD designates the
    # already-at-headcount case as ERR_SHIFT_FULLY_STAFFED (§3.9), which the
    # over-staffing guard inside the eligibility battery surfaces in its proper
    # precedence slot. So FULLY_STAFFED must fall through to the battery here.
    if shift["status"] not in ("OPEN", "FULLY_STAFFED"):
        raise ApiError("ERR_INVALID_SHIFT_STATE")
    rec = sched.create_scheduled_assignment(shift, worker, loc, "DIRECT", force)
    _stamp_shift_computed(shift)
    return object_response(view("Assignment", rec), 201)


@app.route("/assignments", methods=["GET"])
def list_assignments():
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    shift_filter = request.args.get("shift_id")
    worker_filter = request.args.get("worker_id")
    pp_filter = request.args.get("pay_period_id")
    records = []
    for a in db.assignments.values():
        if shift_filter is not None and a["shift_id"] != shift_filter:
            continue
        if worker_filter is not None and a["worker_id"] != worker_filter:
            continue
        if pp_filter is not None and a["pay_period_id"] != pp_filter:
            continue
        records.append(a)
    return list_response("Assignment", records)


@app.route("/assignments/<asg_id>", methods=["GET"])
def get_assignment(asg_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    rec = get_assignment_or_404(asg_id)
    return object_response(view("Assignment", rec))


@app.route("/locations/<loc_id>/assignments/<asg_id>/confirm", methods=["POST"])
def confirm_assignment(loc_id, asg_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    asg = get_assignment_or_404(asg_id)
    if asg["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    if uid != asg["worker_id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    shift = db.shifts[asg["shift_id"]]
    if not (clock.now() < sched.shift_start(shift)):
        raise ApiError("ERR_SHIFT_ALREADY_STARTED")
    asg["status"] = "CONFIRMED"
    db.touch(asg)
    return object_response(view("Assignment", asg))


@app.route("/locations/<loc_id>/assignments/<asg_id>/cancel", methods=["POST"])
def cancel_assignment(loc_id, asg_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    asg = get_assignment_or_404(asg_id)
    if asg["status"] not in sched.SCHEDULED_OR_CONFIRMED:
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    pp = db.pay_periods.get(asg["pay_period_id"])
    if pp is not None and pp["status"] != "OPEN":
        raise ApiError("ERR_PAY_PERIOD_LOCKED")
    shift = db.shifts[asg["shift_id"]]
    worker = db.workers[asg["worker_id"]]

    asg["status"] = "CANCELLED"
    db.touch(asg)
    # Bubble-down parent shift if it was fully staffed.
    sched.bubble_down_if_understaffed(shift)
    _stamp_shift_computed(shift)
    # Short-notice cancel accrual.
    if sched.within_advance_notice_window(shift, loc) and pp is not None:
        sched.accrue_short_notice_cancel(shift, worker, loc, pp)
    sched.reconcile_pay_period(pp)
    return object_response(view("Assignment", asg))


@app.route("/locations/<loc_id>/assignments/<asg_id>/no-show", methods=["POST"])
def no_show_assignment(loc_id, asg_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    get_location_or_404(loc_id)
    asg = get_assignment_or_404(asg_id)
    if asg["status"] not in sched.SCHEDULED_OR_CONFIRMED:
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    shift = db.shifts[asg["shift_id"]]
    if not (clock.now() >= sched.shift_start(shift)):
        raise ApiError("ERR_SHIFT_NOT_STARTED")
    worker = db.workers[asg["worker_id"]]
    pp = db.pay_periods.get(asg["pay_period_id"])

    asg["status"] = "NO_SHOW"
    db.touch(asg)
    # Cross-entity cascade: strike++, suspend at ceiling.
    worker["no_show_strikes"] += 1
    if worker["no_show_strikes"] >= sched.STRIKE_CEILING:
        worker["status"] = "SUSPENDED"
    db.touch(worker)
    # Bubble-down + reconcile.
    sched.bubble_down_if_understaffed(shift)
    _stamp_shift_computed(shift)
    sched.reconcile_pay_period(pp)
    return object_response(view("Assignment", asg))


# ===========================================================================
# Open-shift bidding + award
# ===========================================================================
@app.route("/locations/<loc_id>/shifts/<shift_id>/bids", methods=["POST"])
def create_bid(loc_id, shift_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    shift = get_shift_or_404(shift_id)
    body = get_json_body()
    # Bidder is the acting worker (X-User-ID).
    worker = db.workers.get(uid)
    if worker is None:
        raise ApiError("ERR_NOT_FOUND")
    if shift["status"] != "OPEN":
        raise ApiError("ERR_INVALID_SHIFT_STATE")
    # Cross-location: bidder must belong to the shift's location.
    if worker["location_id"] != shift["location_id"]:
        raise ApiError("ERR_CROSS_LOCATION")
    # Suspended workers may not bid.
    sched.check_not_suspended(worker)
    seniority = optional_int(body, "seniority_score", 0)
    rec = db.common_fields()
    rec.update({
        "shift_id": shift["id"],
        "worker_id": worker["id"],
        "seniority_score": seniority,
        "status": "SUBMITTED",
    })
    db.bids[rec["id"]] = rec
    return object_response(view("OpenShiftBid", rec), 201)


@app.route("/bids", methods=["GET"])
def list_bids():
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    shift_filter = request.args.get("shift_id")
    worker_filter = request.args.get("worker_id")
    records = []
    for b in db.bids.values():
        if shift_filter is not None and b["shift_id"] != shift_filter:
            continue
        if worker_filter is not None and b["worker_id"] != worker_filter:
            continue
        records.append(b)
    return list_response("OpenShiftBid", records)


@app.route("/bids/<bid_id>", methods=["GET"])
def get_bid(bid_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    rec = get_bid_or_404(bid_id)
    return object_response(view("OpenShiftBid", rec))


@app.route("/locations/<loc_id>/bids/<bid_id>/withdraw", methods=["POST"])
def withdraw_bid(loc_id, bid_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    bid = get_bid_or_404(bid_id)
    if bid["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_BID_STATE")
    if uid != bid["worker_id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    bid["status"] = "WITHDRAWN"
    db.touch(bid)
    return object_response(view("OpenShiftBid", bid))


@app.route("/locations/<loc_id>/shifts/<shift_id>/award", methods=["POST"])
def award_shift(loc_id, shift_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    shift = get_shift_or_404(shift_id)
    body = get_json_body()
    require_fields(body, ["bid_id", "expected_shift_version"])
    bid = get_bid_or_404(body["bid_id"])
    expected_version = require_int(body, "expected_shift_version")
    force = optional_bool(body, "force_over_guardrail", False)

    # State (priority 6): shift must be OPEN.
    if shift["status"] != "OPEN":
        raise ApiError("ERR_INVALID_SHIFT_STATE")

    # Pay-period locked (priority 7) — check before OCC per validation order.
    pp = sched.find_pay_period_for_shift(shift)
    if pp is not None and pp["status"] != "OPEN":
        raise ApiError("ERR_PAY_PERIOD_LOCKED")

    # OCC (priority 8): expected_shift_version must equal current version.
    if expected_version != shift["version"]:
        raise ApiError("ERR_STALE_SHIFT_VERSION")

    # Bid must be the winner among SUBMITTED bids (bid_award_selection).
    winner = _select_winning_bid(shift)
    if winner is None or bid["id"] != winner["id"]:
        raise ApiError("ERR_BID_NOT_WINNER")

    worker = db.workers[bid["worker_id"]]
    rec = sched.create_scheduled_assignment(shift, worker, loc, "BID", force)
    # Award succeeded: winning bid -> AWARDED, increment shift version.
    bid["status"] = "AWARDED"
    db.touch(bid)
    shift["version"] += 1  # award itself increments version (PRD §2.11)
    shift["updated_at"] = db.iso_millis(db._wall_now())
    # bubble-up already ran inside create_scheduled_assignment; if it flipped to
    # FULLY_STAFFED the winning bid is excluded (already AWARDED) from rejection.
    _stamp_shift_computed(shift)
    return object_response(view("Assignment", rec), 201)


def _select_winning_bid(shift):
    """Highest seniority_score; tie-break earliest created_at (then _seq); id never
    used."""
    candidates = [b for b in db.bids.values()
                  if b["shift_id"] == shift["id"] and b["status"] == "SUBMITTED"]
    if not candidates:
        return None
    return max(candidates, key=lambda b: (
        b["seniority_score"], -_created_epoch(b),
    ))


def _created_epoch(record):
    """Monotonic key for created ordering: combine created_at + _seq."""
    return record["_seq"]


# ===========================================================================
# Swap
# ===========================================================================
@app.route("/locations/<loc_id>/swaps", methods=["POST"])
def create_swap(loc_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    body = get_json_body()
    require_fields(body, ["from_assignment_id", "to_worker_id"])
    from_asg = get_assignment_or_404(body["from_assignment_id"])
    to_worker = get_worker_or_404(body["to_worker_id"])
    # Initiator must own the from_assignment.
    if uid != from_asg["worker_id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    rec = db.common_fields()
    rec.update({
        "from_assignment_id": from_asg["id"],
        "to_worker_id": to_worker["id"],
        "counter_assignment_id": None,
        "status": "PROPOSED",
        "decided_by_manager_id": None,
    })
    db.swaps[rec["id"]] = rec
    return object_response(view("SwapRequest", rec), 201)


@app.route("/swaps", methods=["GET"])
def list_swaps():
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    from_filter = request.args.get("from_assignment_id")
    to_filter = request.args.get("to_worker_id")
    counter_filter = request.args.get("counter_assignment_id")
    records = []
    for s in db.swaps.values():
        if from_filter is not None and s["from_assignment_id"] != from_filter:
            continue
        if to_filter is not None and s["to_worker_id"] != to_filter:
            continue
        if counter_filter is not None and s["counter_assignment_id"] != counter_filter:
            continue
        records.append(s)
    return list_response("SwapRequest", records)


@app.route("/swaps/<swap_id>", methods=["GET"])
def get_swap(swap_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    rec = get_swap_or_404(swap_id)
    return object_response(view("SwapRequest", rec))


def _swap_initiator_id(swap):
    return db.assignments[swap["from_assignment_id"]]["worker_id"]


@app.route("/locations/<loc_id>/swaps/<swap_id>/counter", methods=["POST"])
def counter_swap(loc_id, swap_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    swap = get_swap_or_404(swap_id)
    body = get_json_body()
    require_fields(body, ["counter_assignment_id"])
    counter = get_assignment_or_404(body["counter_assignment_id"])
    if swap["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_SWAP_STATE")
    if uid != swap["to_worker_id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    if counter["worker_id"] != uid or counter["status"] not in sched.SCHEDULED_OR_CONFIRMED:
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    swap["counter_assignment_id"] = counter["id"]
    swap["status"] = "COUNTERED"
    db.touch(swap)
    return object_response(view("SwapRequest", swap))


@app.route("/locations/<loc_id>/swaps/<swap_id>/repropose", methods=["POST"])
def repropose_swap(loc_id, swap_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    swap = get_swap_or_404(swap_id)
    if swap["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_SWAP_STATE")
    if uid != _swap_initiator_id(swap):
        raise ApiError("ERR_UNAUTHORIZED")
    swap["counter_assignment_id"] = None
    swap["status"] = "PROPOSED"
    db.touch(swap)
    return object_response(view("SwapRequest", swap))


@app.route("/locations/<loc_id>/swaps/<swap_id>/accept", methods=["POST"])
def accept_swap(loc_id, swap_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    swap = get_swap_or_404(swap_id)
    if swap["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_SWAP_STATE")
    if swap["status"] == "PROPOSED":
        # counterparty accepts
        if uid != swap["to_worker_id"]:
            raise ApiError("ERR_UNAUTHORIZED")
    else:  # COUNTERED -> initiator accepts the counter
        if uid != _swap_initiator_id(swap):
            raise ApiError("ERR_UNAUTHORIZED")
    swap["status"] = "ACCEPTED"
    db.touch(swap)
    return object_response(view("SwapRequest", swap))


@app.route("/locations/<loc_id>/swaps/<swap_id>/reject", methods=["POST"])
def reject_swap(loc_id, swap_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    swap = get_swap_or_404(swap_id)
    if swap["status"] not in ("PROPOSED", "COUNTERED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_SWAP_STATE")
    # A party to the swap: initiator or counterparty.
    if uid != swap["to_worker_id"] and uid != _swap_initiator_id(swap):
        raise ApiError("ERR_UNAUTHORIZED")
    swap["status"] = "REJECTED"
    db.touch(swap)
    return object_response(view("SwapRequest", swap))


@app.route("/locations/<loc_id>/swaps/<swap_id>/cancel", methods=["POST"])
def cancel_swap(loc_id, swap_id):
    uid, role = authenticate()
    require_role(role, [ROLE_WORKER])
    get_location_or_404(loc_id)
    swap = get_swap_or_404(swap_id)
    if swap["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_SWAP_STATE")
    if uid != _swap_initiator_id(swap):
        raise ApiError("ERR_UNAUTHORIZED")
    swap["status"] = "CANCELLED"
    db.touch(swap)
    return object_response(view("SwapRequest", swap))


@app.route("/locations/<loc_id>/swaps/<swap_id>/approve", methods=["POST"])
def approve_swap(loc_id, swap_id):
    uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    swap = get_swap_or_404(swap_id)
    if swap["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_SWAP_STATE")
    from_asg = db.assignments[swap["from_assignment_id"]]
    if from_asg["status"] not in sched.SCHEDULED_OR_CONFIRMED:
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")

    to_worker = db.workers[swap["to_worker_id"]]
    from_shift = db.shifts[from_asg["shift_id"]]
    counter_asg = None
    if swap["counter_assignment_id"]:
        counter_asg = db.assignments[swap["counter_assignment_id"]]

    # Receiving worker (to_worker) must pass minor-cap hard check for the swapped
    # (from) shift; clopening here is soft and only flags.
    sched.check_minor_caps(to_worker, from_shift, from_asg["pay_period_id"], loc,
                           exclude_assignment_id=from_asg["id"])
    if counter_asg is not None:
        from_worker = db.workers[from_asg["worker_id"]]
        counter_shift = db.shifts[counter_asg["shift_id"]]
        sched.check_minor_caps(from_worker, counter_shift, counter_asg["pay_period_id"], loc,
                               exclude_assignment_id=counter_asg["id"])

    # Cross-entity cascade.
    affected_pps = set()
    original_from_worker = from_asg["worker_id"]
    from_asg["worker_id"] = to_worker["id"]
    from_asg["source"] = "SWAP"
    from_asg["clopening_flag"] = sched.compute_clopening_flag(from_asg, from_shift, to_worker, loc)
    from_asg["provisional_cost_cents"] = sched.compute_provisional_cost(from_asg, from_shift, to_worker, loc)
    db.touch(from_asg)
    affected_pps.add(from_asg["pay_period_id"])

    if counter_asg is not None:
        counter_worker = db.workers[original_from_worker]
        counter_shift = db.shifts[counter_asg["shift_id"]]
        counter_asg["worker_id"] = original_from_worker
        counter_asg["source"] = "SWAP"
        counter_asg["clopening_flag"] = sched.compute_clopening_flag(counter_asg, counter_shift, counter_worker, loc)
        counter_asg["provisional_cost_cents"] = sched.compute_provisional_cost(counter_asg, counter_shift, counter_worker, loc)
        db.touch(counter_asg)
        affected_pps.add(counter_asg["pay_period_id"])

    for pp_id in affected_pps:
        if pp_id in db.pay_periods:
            sched.reconcile_pay_period(db.pay_periods[pp_id])

    swap["status"] = "MANAGER_APPROVED"
    swap["decided_by_manager_id"] = uid
    db.touch(swap)
    return object_response(view("SwapRequest", swap))


# ===========================================================================
# PayPeriod
# ===========================================================================
@app.route("/locations/<loc_id>/pay-periods", methods=["POST"])
def create_pay_period(loc_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    loc = get_location_or_404(loc_id)
    body = get_json_body()
    require_fields(body, ["start_utc", "end_utc"])
    start = parse_utc(body["start_utc"], "start_utc")
    end = parse_utc(body["end_utc"], "end_utc")
    if not (end > start):
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    rec = db.common_fields()
    rec.update({
        "location_id": loc["id"],
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "status": "OPEN",
        "projected_labor_cost_cents": 0,
        "finalized_labor_cost_cents": None,
    })
    db.pay_periods[rec["id"]] = rec
    return object_response(view("PayPeriod", rec), 201)


@app.route("/locations/<loc_id>/pay-periods", methods=["GET"])
def list_pay_periods(loc_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    get_location_or_404(loc_id)
    records = [p for p in db.pay_periods.values() if p["location_id"] == loc_id]
    return list_response("PayPeriod", records)


@app.route("/pay-periods/<pp_id>", methods=["GET"])
def get_pay_period(pp_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    rec = get_pay_period_or_404(pp_id)
    return object_response(view("PayPeriod", rec))


@app.route("/locations/<loc_id>/pay-periods/<pp_id>/lock", methods=["POST"])
def lock_pay_period(loc_id, pp_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    get_location_or_404(loc_id)
    pp = get_pay_period_or_404(pp_id)
    if pp["status"] != "OPEN":
        raise ApiError("ERR_PAY_PERIOD_LOCKED")
    # Every assignment in this period must be terminal.
    for a in db.assignments.values():
        if a["pay_period_id"] == pp["id"] and a["status"] not in sched.TERMINAL_ASSIGNMENT:
            raise ApiError("ERR_OPEN_ASSIGNMENTS_EXIST")
    finalized = 0
    for a in db.assignments.values():
        if a["pay_period_id"] == pp["id"] and a["status"] == "COMPLETED":
            finalized += a["finalized_cost_cents"] or 0
    for e in db.ledger.values():
        if e["pay_period_id"] == pp["id"]:
            finalized += e["amount_cents"]
    pp["finalized_labor_cost_cents"] = finalized
    pp["status"] = "LOCKED"
    db.touch(pp)
    return object_response(view("PayPeriod", pp))


# ===========================================================================
# Predictability ledger (read-only)
# ===========================================================================
@app.route("/predictability-ledger", methods=["GET"])
def list_ledger():
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    worker_filter = request.args.get("worker_id")
    shift_filter = request.args.get("shift_id")
    pp_filter = request.args.get("pay_period_id")
    records = []
    for e in db.ledger.values():
        if worker_filter is not None and e["worker_id"] != worker_filter:
            continue
        if shift_filter is not None and e["shift_id"] != shift_filter:
            continue
        if pp_filter is not None and e["pay_period_id"] != pp_filter:
            continue
        records.append(e)
    return list_response("PredictabilityLedgerEntry", records)


@app.route("/predictability-ledger/<ledger_id>", methods=["GET"])
def get_ledger_entry(ledger_id):
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER, ROLE_WORKER])
    rec = db.ledger.get(ledger_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return object_response(view("PredictabilityLedgerEntry", rec))


# ===========================================================================
# Test-driving clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require_role(role, [ROLE_MANAGER])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    instant = parse_utc(body["to_iso8601"], "to_iso8601")
    clock.set_now(instant)
    return object_response({})


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Store starts empty; nothing is seeded.
    port = int(os.environ.get("PORT", "10000"))

    # Boot robustness under per-test-server isolation with 8 concurrent rounds:
    # the runner kills the previous server and relaunches us before every test.
    # Two failure modes under that load:
    #   (1) the old process has not fully released the listening socket yet, so a
    #       plain bind raises "Address already in use" and we die before the
    #       runner's poll window — reported as "could not be restarted";
    #   (2) the accept backlog is exhausted while the CPU is saturated by 7 other
    #       booting servers, so an inbound connection is reset before accept —
    #       reported by the client as "Connection reset by peer".
    # Build the WSGI server explicitly so we can (a) retry the bind for a short
    # window with no TOCTOU gap (make_server binds immediately and owns the
    # socket) and (b) widen the listen backlog so concurrent connection attempts
    # queue instead of being reset.
    import time as _time
    from werkzeug.serving import make_server

    deadline = _time.time() + 12.0
    srv = None
    while True:
        try:
            srv = make_server("0.0.0.0", port, app, threaded=True)
            break
        except OSError:
            if _time.time() >= deadline:
                raise
            _time.sleep(0.1)

    try:
        # Widen the kernel accept queue beyond the default so a burst of
        # connections during high-load reboots queues rather than resets.
        srv.socket.listen(128)
    except OSError:
        pass

    srv.serve_forever()
