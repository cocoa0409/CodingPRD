"""Monitoring visits (PRD sec 3.7)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.common import require_owner, require_state
from services import cascades
from services import calculations as calc
from services import lookup
from services import serializers as ser

bp = Blueprint("visits", __name__)

REVIEWER = mw.ROLE_STATE_AGENCY_REVIEWER
SPONSOR_ADMIN = mw.ROLE_SPONSOR_ADMIN
MONITOR = mw.ROLE_FIELD_MONITOR

VISIT_STATUSES = ("SCHEDULED", "CONDUCTED", "REPORT_FILED", "CLOSED", "CANCELLED")


@bp.post("/sfsp/monitoring-visits")
@mw.endpoint([MONITOR])
def schedule_visit():
    body = mw.json_body()
    site_id = mw.field_str(body, "site_id")
    monitor_user_id = mw.field_str(body, "monitor_user_id")
    visit_type = mw.field_enum(body, "visit_type", calc.VISIT_TYPES)
    scheduled_date = mw.field_date(body, "scheduled_date")
    window_start = mw.field_time(body, "window_start")
    window_end = mw.field_time(body, "window_end")
    if window_start >= window_end:
        mw.bad_request("Field 'window_start' must be strictly before 'window_end'.")

    site = lookup.require_site(site_id)

    scheduled_iso = db.date_iso(scheduled_date)
    same_day = [
        visit
        for visit in db.store.visits.values()
        if visit["monitor_user_id"] == monitor_user_id
        and visit["scheduled_date"] == scheduled_iso
        and visit["status"] != "CANCELLED"
    ]

    # Monitor windows are CLOSED intervals: touching endpoints collide.
    for visit in same_day:
        other_start = db.parse_hhmm(visit["window_start"])
        other_end = db.parse_hhmm(visit["window_end"])
        if window_start <= other_end and other_start <= window_end:
            raise ApiError("ERR_MONITOR_SCHEDULE_CONFLICT")

    if len(same_day) >= calc.MAX_VISITS_PER_MONITOR_DAY:
        raise ApiError("ERR_MONITOR_DAILY_CAP_EXCEEDED")

    visit = db.new_row(
        {
            "site_id": site["id"],
            "monitor_user_id": monitor_user_id,
            "visit_type": visit_type,
            "scheduled_date": scheduled_iso,
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "status": "SCHEDULED",
            "conducted_at": None,
            "findings": None,
            "highest_severity": None,
            "due_date": None,
            "is_late": False,
            "cancel_reason": None,
        }
    )
    visit["due_date"] = calc.visit_due_date(visit, site)
    visit["is_late"] = calc.visit_is_late(visit)
    db.store.visits[visit["id"]] = visit
    return response.created_response(ser.visit(visit))


@bp.get("/sfsp/monitoring-visits/<visit_id>")
@mw.endpoint([REVIEWER, SPONSOR_ADMIN, MONITOR])
def get_visit(visit_id):
    visit = lookup.require_visit(visit_id)
    return response.object_response(ser.visit(visit))


@bp.get("/sfsp/monitoring-visits")
@mw.endpoint([REVIEWER, SPONSOR_ADMIN, MONITOR])
def list_visits():
    limit, offset = mw.pagination()
    site_id = mw.query_value("site_id")
    monitor_user_id = mw.query_value("monitor_user_id")
    status = mw.query_enum("status", VISIT_STATUSES)
    visit_type = mw.query_enum("visit_type", calc.VISIT_TYPES)
    scheduled_date = mw.query_date("scheduled_date")

    rows = []
    for visit in db.store.visits.values():
        if site_id is not None and visit["site_id"] != site_id:
            continue
        if monitor_user_id is not None and visit["monitor_user_id"] != monitor_user_id:
            continue
        if status is not None and visit["status"] != status:
            continue
        if visit_type is not None and visit["visit_type"] != visit_type:
            continue
        if scheduled_date is not None and visit["scheduled_date"] != db.date_iso(
            scheduled_date
        ):
            continue
        rows.append(visit)
    return response.paginate(rows, limit, offset, ser.visit)


@bp.post("/sfsp/monitoring-visits/<visit_id>/conduct")
@mw.endpoint([MONITOR])
def conduct_visit(visit_id):
    visit = lookup.require_visit(visit_id)
    require_owner(visit["monitor_user_id"])
    require_state(visit["status"] == "SCHEDULED", "ERR_VISIT_STATE_INVALID")

    scheduled_date = db.parse_date(visit["scheduled_date"])
    if db.clock.today() < scheduled_date:
        raise ApiError("ERR_VISIT_DATE_NOT_REACHED")

    visit["status"] = "CONDUCTED"
    visit["conducted_at"] = db.clock.now_iso()
    visit["is_late"] = calc.visit_is_late(visit)
    db.touch(visit)
    return response.object_response(ser.visit(visit))


@bp.post("/sfsp/monitoring-visits/<visit_id>/report")
@mw.endpoint([MONITOR])
def report_visit(visit_id):
    body = mw.json_body()
    findings = mw.field_list(body, "findings")
    normalized = []
    for element in findings:
        if not isinstance(element, dict):
            mw.bad_request("Each 'findings' element must be an object.")
        finding_code = mw.field_str(element, "finding_code")
        severity = mw.field_enum(element, "severity", calc.SEVERITIES)
        normalized.append({"finding_code": finding_code, "severity": severity})

    visit = lookup.require_visit(visit_id)
    require_owner(visit["monitor_user_id"])
    require_state(visit["status"] == "CONDUCTED", "ERR_VISIT_STATE_INVALID")

    if not normalized:
        visit["findings"] = []
        visit["highest_severity"] = "NONE"
        visit["status"] = "CLOSED"
        visit["is_late"] = calc.visit_is_late(visit)
        db.touch(visit)
        return response.object_response(ser.visit(visit))

    highest = max(normalized, key=lambda item: calc.SEVERITY_ORDER[item["severity"]])
    highest_severity = highest["severity"]
    finding_code = min(
        item["finding_code"]
        for item in normalized
        if item["severity"] == highest_severity
    )

    visit["findings"] = normalized
    visit["highest_severity"] = highest_severity
    visit["status"] = "REPORT_FILED"
    visit["is_late"] = calc.visit_is_late(visit)
    db.touch(visit)

    site = lookup.require_site(visit["site_id"])
    cascades.create_corrective_action(
        site,
        severity=highest_severity,
        finding_code=finding_code,
        origin="VISIT_FINDING",
        opened_by_user_id=mw.acting_user_id(),
        monitoring_visit_id=visit["id"],
    )
    return response.object_response(ser.visit(visit))


@bp.post("/sfsp/monitoring-visits/<visit_id>/cancel")
@mw.endpoint([MONITOR])
def cancel_visit(visit_id):
    body = mw.json_body()
    reason = mw.field_str(body, "reason")

    visit = lookup.require_visit(visit_id)
    require_owner(visit["monitor_user_id"])
    require_state(visit["status"] == "SCHEDULED", "ERR_VISIT_STATE_INVALID")

    visit["status"] = "CANCELLED"
    visit["cancel_reason"] = reason
    visit["is_late"] = False
    db.touch(visit)
    return response.object_response(ser.visit(visit))
