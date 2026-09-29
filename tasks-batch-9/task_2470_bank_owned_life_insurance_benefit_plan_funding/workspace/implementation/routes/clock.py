"""The logical clock (PRD 2.5)."""

from flask import Blueprint

from response import object_response
from store import db, touch
from util import format_datetime
from validation import authorize, get_datetime, json_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(("PlatformAdmin",))
    body = json_body()
    _raw, moment = get_datetime(body, "to_iso8601", required=True)
    db.clock = moment

    expired_consent_count = 0
    touched_employees = set()
    for record in db.consent_records.values():
        if record["status"] != "EXECUTED":
            continue
        if record["_coverage_end_date"] < moment:
            record["status"] = "EXPIRED"
            touch(record)
            expired_consent_count += 1
            touched_employees.add(record["employee_id"])

    for employee_id in touched_employees:
        employee = db.employees.get(employee_id)
        if employee is None:
            continue
        still_executed = any(
            r["employee_id"] == employee_id and r["status"] == "EXECUTED"
            for r in db.consent_records.values()
        )
        if not still_executed and employee["insurable_interest_status"] != "NOT_ESTABLISHED":
            employee["insurable_interest_status"] = "NOT_ESTABLISHED"
            touch(employee)

    return object_response(
        {
            "current_utc": format_datetime(db.clock),
            "expired_consent_count": expired_consent_count,
        }
    )
