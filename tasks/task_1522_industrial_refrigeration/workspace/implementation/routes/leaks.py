"""Leak events and the regulatory notification clock (PRD 3.8)."""
from flask import Blueprint

import calc
import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    apply_filters,
    bad_request,
    body_row,
    endpoint,
    operator_employee,
    paginate,
    pagination,
    path_row,
    req_number,
    req_string,
)
from serialize import leak_out
from store import db, sorted_rows, touch
from util import add_minutes, ZERO

bp = Blueprint("leaks", __name__)

CREATE_SCHEMA = (
    frozenset(["system_id", "estimated_release_lbs", "source_description"]),
    frozenset(["system_id", "estimated_release_lbs", "source_description"]),
)
CONFIRM_SCHEMA = (frozenset(["final_release_lbs"]), frozenset(["final_release_lbs"]))
EMPTY_SCHEMA = (frozenset(), frozenset())

STATUS_VALUES = ("SUSPECTED", "CONFIRMED", "FALSE_ALARM")


@bp.post("/psm/leak-events")
@endpoint(["Operator"], schema=CREATE_SCHEMA)
def report_leak(ctx):
    # step 0 -- payload values; the initial estimate must be strictly positive
    estimated = req_number(ctx.body, "estimated_release_lbs")
    if estimated <= ZERO:
        bad_request("Field 'estimated_release_lbs' must be strictly positive.")
    source = req_string(ctx.body, "source_description")
    # step 2 -- entity-backed Operator identity
    operator_employee(ctx)
    # step 3
    system = body_row(ctx.body, "systems", "system_id")
    row = db.create(
        "leak_events",
        {
            "system_id": system["id"],
            "estimated_release_lbs": estimated,
            "source_description": source,
            "status": "SUSPECTED",
            "final_release_lbs": None,
            "confirmed_at": None,
            "notification_deadline_at": None,
            "notification_status": "NOT_REQUIRED",
            "notified_at": None,
            "auto_incident_id": None,
        },
    )
    return envelope.created(leak_out(row))


@bp.get("/psm/leak-events/<leak_id>")
@endpoint(ALL_ROLES)
def get_leak(ctx, leak_id):
    return envelope.ok(leak_out(path_row("leak_events", leak_id)))


@bp.get("/psm/leak-events")
@endpoint(ALL_ROLES)
def list_leaks(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.leak_events.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("system_id", "system_id", None),
            ("auto_incident_id", "auto_incident_id", None),
            ("status", "status", STATUS_VALUES),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [leak_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


@bp.post("/psm/leak-events/<leak_id>/confirm")
@endpoint(["ComplianceOfficer"], schema=CONFIRM_SCHEMA)
def confirm_leak(ctx, leak_id):
    final_release = req_number(ctx.body, "final_release_lbs")
    leak = path_row("leak_events", leak_id)
    # step 5 -- SUSPECTED only
    if leak["status"] != "SUSPECTED":
        raise ApiError("ERR_INVALID_STATE")
    # step 10 -- strictly positive confirmed quantity
    if final_release <= ZERO:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE")

    now = db.now()
    leak["status"] = "CONFIRMED"
    leak["final_release_lbs"] = final_release
    leak["confirmed_at"] = now
    # notification obligation: exactly 100.0 lbs qualifies (>= RQ)
    if calc.notification_required(final_release):
        leak["notification_deadline_at"] = add_minutes(now, calc.NOTIFY_WINDOW_MINUTES)
        leak["notification_status"] = "PENDING"
    else:
        leak["notification_deadline_at"] = None
        leak["notification_status"] = "NOT_REQUIRED"

    # auto-created incident on the system's facility; the one place
    # reported_by_employee_id is legitimately null
    system = db.systems.get(leak["system_id"])
    incident = db.create(
        "incidents",
        {
            "facility_id": system["facility_id"] if system else None,
            "equipment_id": None,
            "severity": calc.incident_severity_for_release(final_release),
            "description": leak["source_description"],
            "reported_by_employee_id": None,
            "investigator_employee_id": None,
            "status": "REPORTED",
            "reopen_count": 0,
            "source_leak_event_id": leak["id"],
        },
    )
    leak["auto_incident_id"] = incident["id"]
    touch(leak)
    return envelope.ok(leak_out(leak))


@bp.post("/psm/leak-events/<leak_id>/false-alarm")
@endpoint(["ComplianceOfficer"], schema=EMPTY_SCHEMA)
def false_alarm(ctx, leak_id):
    leak = path_row("leak_events", leak_id)
    if leak["status"] != "SUSPECTED":
        raise ApiError("ERR_INVALID_STATE")
    leak["status"] = "FALSE_ALARM"
    touch(leak)
    return envelope.ok(leak_out(leak))


@bp.post("/psm/leak-events/<leak_id>/notify-regulator")
@endpoint(["ComplianceOfficer"], schema=EMPTY_SCHEMA)
def notify_regulator(ctx, leak_id):
    leak = path_row("leak_events", leak_id)
    # step 5 -- the self-transition is declared on CONFIRMED events only
    if leak["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    # step 10 -- a notification must actually be outstanding
    if leak["notification_status"] not in ("PENDING", "OVERDUE"):
        raise ApiError("ERR_NOTIFICATION_NOT_REQUIRED")
    leak["notified_at"] = db.now()
    leak["notification_status"] = "NOTIFIED"
    touch(leak)
    return envelope.ok(leak_out(leak))
