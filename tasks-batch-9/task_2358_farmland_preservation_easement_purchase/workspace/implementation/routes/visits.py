"""MonitoringVisit endpoints (PRD 3.8)."""

from flask import Blueprint, request

from db import base_row, db, touch
from errors import ApiError
from middleware import authenticate
from response import created, listing, ok, pagination
from services import calc, cascade, lookup, serialize
from validation import Payload, body_fk, raw_body

bp = Blueprint("visits", __name__)

VISIT_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
VIOLATION_STATUSES = ("OPEN", "CURE_PLAN_ACCEPTED", "CURED", "ESCALATED")


@bp.post("/monitoring-visits")
def schedule_visit():
    authenticate(("StewardshipMonitor",))
    body = raw_body()
    easement = lookup.get_easement(body_fk(body, "easement_id"))
    payload = Payload(body, ("easement_id", "window_start", "window_end"))
    payload.string("easement_id", min_len=1)
    window_start = payload.instant("window_start")
    window_end = payload.instant("window_end")
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "window_end must be strictly after window_start"
        )

    # rung 9 -- deed dimension.
    if easement["status"] not in ("RECORDED", "AMENDED"):
        raise ApiError(
            "ERR_INVALID_EASEMENT_STATE",
            "only a RECORDED or AMENDED easement accepts monitoring visits",
        )
    # rung 11 -- stewardship hold.
    if easement["stewardship_hold"]:
        raise ApiError(
            "ERR_EASEMENT_NOT_COMPLIANT",
            "an easement under a stewardship hold accepts no new monitoring work",
        )
    # rung 12 -- half-open window overlap against SCHEDULED visits only.
    for existing in lookup.visits_of(easement["id"]):
        if existing["status"] != "SCHEDULED":
            continue
        if window_start < existing["window_end"] and existing["window_start"] < window_end:
            raise ApiError(
                "ERR_MONITORING_WINDOW_OVERLAP",
                "the window overlaps an already scheduled visit",
            )
    # rung 16 -- referential scope.
    parent_app = db.applications.get(easement["application_id"])
    if parent_app is not None and parent_app["parcel_id"] != easement["parcel_id"]:
        raise ApiError(
            "ERR_EASEMENT_SCOPE_MISMATCH",
            "the easement does not belong to the program that recorded it",
        )

    row = base_row()
    row.update(
        {
            "easement_id": easement["id"],
            "window_start": window_start,
            "window_end": window_end,
            "status": "SCHEDULED",
            "completed_at": None,
            "observed_impervious_sqft": None,
            "finding": None,
            "notes": None,
            "cancellation_reason": None,
        }
    )
    db.monitoring_visits[row["id"]] = row
    return created(serialize.monitoring_visit(row))


@bp.get("/monitoring-visits/<visit_id>")
def read_visit(visit_id):
    authenticate(("ProgramAdmin", "StewardshipMonitor", "Landowner"))
    return ok(serialize.monitoring_visit(lookup.get_visit(visit_id)))


@bp.post("/monitoring-visits/<visit_id>/completion")
def complete_visit(visit_id):
    authenticate(("StewardshipMonitor",))
    visit = lookup.get_visit(visit_id)
    payload = Payload(raw_body(), ("observed_impervious_sqft", "notes"))
    observed = payload.integer("observed_impervious_sqft", minimum=0)
    notes = payload.string("notes", required=False, default=None, min_len=1, max_len=2000)

    if visit["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_VISIT_STATE", "only a SCHEDULED visit can be completed"
        )
    if db.clock < visit["window_start"]:
        raise ApiError(
            "ERR_INVALID_VISIT_STATE",
            "a visit cannot be completed before its window opens",
        )

    easement = db.easements[visit["easement_id"]]
    program = lookup.program_of_easement(easement)
    completed_at = db.clock
    finding, excess = calc.impervious_finding(
        observed, easement["impervious_allowance_sqft"]
    )
    visit["status"] = "COMPLETED"
    visit["completed_at"] = completed_at
    visit["observed_impervious_sqft"] = observed
    visit["finding"] = finding
    if notes is not None:
        visit["notes"] = notes
    touch(visit)

    # the stewardship dimension resets, independently of compliance
    easement["last_monitored_on"] = completed_at
    cascade.project_stewardship(easement, program)
    easement["stewardship_status"] = "MONITORING_CURRENT"
    touch(easement)

    if finding == "CONFIRMED_VIOLATION":
        cascade.open_violation(
            easement, "IMPERVIOUS_EXCEEDANCE", excess, visit["id"]
        )
    return ok(serialize.monitoring_visit(visit))


@bp.post("/monitoring-visits/<visit_id>/cancellation")
def cancel_visit(visit_id):
    authenticate(("StewardshipMonitor",))
    visit = lookup.get_visit(visit_id)
    payload = Payload(raw_body(), ("reason",))
    reason = payload.string("reason", min_len=1, max_len=500)

    if visit["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_VISIT_STATE", "only a SCHEDULED visit can be cancelled"
        )
    visit["status"] = "CANCELLED"
    visit["cancellation_reason"] = reason
    touch(visit)
    return ok(serialize.monitoring_visit(visit))


@bp.get("/monitoring-visits/<visit_id>/violations")
def list_visit_violations(visit_id):
    authenticate(("ProgramAdmin", "StewardshipMonitor"))
    visit = lookup.get_visit(visit_id)
    limit, offset = pagination(request.args)
    status = request.args.get("status")
    if status is not None and status not in VIOLATION_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST", "status filter is not valid")
    rows = lookup.violations_of_visit(visit["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return listing(rows, limit, offset, serialize.violation)
