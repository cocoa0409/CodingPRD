"""Routes: call-coverage assignments and early release."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from store import db
from errors import ApiError, err_invalid_time_window
from envelope import ok, ok_list
from validate import auth, get_body, check_body, sort_and_page, apply_filters
import calc
import serializers as ser

bp = Blueprint("calls", __name__, url_prefix="/anesthesia-ops")

SCHED = ["Scheduler"]
ALL = ["GroupAdministrator", "Scheduler", "AttendingAnesthesiologist", "CRNA",
       "BillingSpecialist", "ComplianceAuditor"]


@bp.post("/call-assignments")
def create_call_assignment():
    auth(SCHED)
    body = get_body()
    check_body(body, {
        "roster_id": {"kind": "str", "req": True},
        "provider_id": {"kind": "str", "req": True},
        "window_start_minute": {"kind": "int", "req": True},
        "window_end_minute": {"kind": "int", "req": True},
    })
    if not (0 <= body["window_start_minute"] < body["window_end_minute"] <= 1439):
        raise err_invalid_time_window()
    roster = db.rosters.get(body["roster_id"])
    if roster is None:
        raise ApiError("ERR_ROSTER_NOT_FOUND", 404, "Roster not found")
    provider = db.providers.get(body["provider_id"])
    if provider is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "Provider not found")
    if roster["lifecycle"] != "PUBLISHED":
        raise ApiError("ERR_ROSTER_NOT_PUBLISHED", 409, "Roster is not PUBLISHED")
    # closed-interval overlap per provider per service date, across all rosters
    for ca in db.call_assignments.values():
        if ca["provider_id"] != body["provider_id"]:
            continue
        r = db.rosters.get(ca["roster_id"])
        if r is None or r["service_date"] != roster["service_date"]:
            continue
        if calc.closed_overlap(body["window_start_minute"], body["window_end_minute"],
                               ca["window_start_minute"], ca["window_end_minute"]):
            raise ApiError("ERR_CALL_WINDOW_OVERLAP", 409,
                           "Call window overlaps an existing window for this provider/date")
    rec = db.new_record(roster_id=body["roster_id"], provider_id=body["provider_id"],
                        window_start_minute=body["window_start_minute"],
                        window_end_minute=body["window_end_minute"],
                        status="SCHEDULED", released_at_minute=None)
    db.call_assignments[rec["id"]] = rec
    return ok(ser.call_assignment(rec), 201)


@bp.get("/call-assignments")
def list_call_assignments():
    auth(ALL)
    items = apply_filters(db.call_assignments.values(), request.args,
                          ["roster_id", "provider_id", "status"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.call_assignment(r) for r in page], limit, offset, total)


@bp.get("/call-assignments/<ca_id>")
def get_call_assignment(ca_id):
    auth(ALL)
    rec = db.call_assignments.get(ca_id)
    if rec is None:
        raise ApiError("ERR_CALL_ASSIGNMENT_NOT_FOUND", 404, "Call assignment not found")
    return ok(ser.call_assignment(rec))


@bp.post("/call-assignments/<ca_id>/release")
def release_call_assignment(ca_id):
    auth(SCHED)
    get_body()
    rec = db.call_assignments.get(ca_id)
    if rec is None:
        raise ApiError("ERR_CALL_ASSIGNMENT_NOT_FOUND", 404, "Call assignment not found")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_CALL_NOT_RELEASABLE", 409, "Call assignment is not SCHEDULED")
    roster = db.rosters[rec["roster_id"]]
    if db.clock_date_str() != roster["service_date"]:
        raise ApiError("ERR_CLOCK_DATE_MISMATCH", 409,
                       "Clock date must equal the roster service date")
    clock_min = db.clock_minute()
    if not (rec["window_start_minute"] < clock_min < rec["window_end_minute"]):
        raise ApiError("ERR_CALL_NOT_RELEASABLE", 409,
                       "Clock minute must fall strictly inside the call window")
    rec["released_at_minute"] = clock_min
    rec["status"] = "RELEASED"
    db.bump(rec)
    ag = calc.find_agreement(roster["site_id"], roster["service_date"])
    if ag is not None:
        served = clock_min - rec["window_start_minute"]
        window_len = rec["window_end_minute"] - rec["window_start_minute"]
        if served * 2 >= window_len:
            amount = ag["call_stipend_cents"]
        elif served * 4 >= window_len:
            amount = int((Decimal(ag["call_stipend_cents"]) / 2).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
        else:
            amount = None
        if amount is not None:
            calc.create_stipend_entry(rec["provider_id"], roster["id"], "CALL",
                                      roster["service_date"], amount)
    return ok(ser.call_assignment(rec))
