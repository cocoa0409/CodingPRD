"""EnrollmentPeriod endpoints (PRD §3.3).

A period frames an open-enrollment cycle, defining the guaranteed-issue window
[gi_window_start, gi_window_end) and the benefit_year_start. Lifecycle:
SCHEDULED -> OPEN -> CLOSED.
"""

from flask import Blueprint, request

import errors
import serializers
import services
from clock import format_iso8601_ms
from db import db
from middleware import require_roles
from response import success, list_success
from validation import (
    get_json_body, require_str, require_datetime, parse_pagination, paginate,
)

bp = Blueprint("enrollment_periods", __name__)


def _store_datetimes(record, gi_start_dt, gi_end_dt, by_start_dt):
    """Keep ISO strings (response) plus internal parsed datetimes (computation)."""
    record["gi_window_start"] = format_iso8601_ms(gi_start_dt)
    record["gi_window_end"] = format_iso8601_ms(gi_end_dt)
    record["benefit_year_start"] = format_iso8601_ms(by_start_dt)
    record["_gi_window_start_dt"] = gi_start_dt
    record["_gi_window_end_dt"] = gi_end_dt
    record["_benefit_year_start_dt"] = by_start_dt


@bp.route("/benefits/enrollment-periods", methods=["POST"])
@require_roles("BenefitsAdmin")
def create_period():
    body = get_json_body()
    employer_id = require_str(body, "employer_id")
    label = require_str(body, "label")
    gi_start = require_datetime(body, "gi_window_start")
    gi_end = require_datetime(body, "gi_window_end")
    benefit_year_start = require_datetime(body, "benefit_year_start")

    # gi_window_end must be strictly later than gi_window_start (PRD §3.3).
    if not (gi_end > gi_start):
        raise errors.invalid_request("gi_window_end must be strictly later than gi_window_start")

    if services.find_employer(employer_id) is None:
        raise errors.not_found("Employer not found")

    record = {
        "employer_id": employer_id,
        "label": label,
        "status": "SCHEDULED",
    }
    _store_datetimes(record, gi_start, gi_end, benefit_year_start)
    with db.lock:
        db.enrollment_periods.insert(record)
    return success(serializers.enrollment_period(record), 201)


@bp.route("/benefits/enrollment-periods", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def list_periods():
    limit, offset = parse_pagination()
    employer_id = request.args.get("employer_id")
    status = request.args.get("status")

    items = db.enrollment_periods.all()
    if employer_id is not None:
        items = [p for p in items if p["employer_id"] == employer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]

    page, total = paginate(items, limit, offset)
    return list_success(
        [serializers.enrollment_period(p) for p in page], limit, offset, total
    )


@bp.route("/benefits/enrollment-periods/<period_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def get_period(period_id):
    record = db.enrollment_periods.get(period_id)
    if record is None:
        raise errors.not_found("Enrollment period not found")
    return success(serializers.enrollment_period(record), 200)


@bp.route("/benefits/enrollment-periods/<period_id>/open", methods=["POST"])
@require_roles("BenefitsAdmin")
def open_period(period_id):
    record = db.enrollment_periods.get(period_id)
    if record is None:
        raise errors.not_found("Enrollment period not found")
    with db.lock:
        if record["status"] != "SCHEDULED":
            raise errors.invalid_state("Enrollment period must be SCHEDULED to open")
        record["status"] = "OPEN"
        db.enrollment_periods.touch(record)
    return success(serializers.enrollment_period(record), 200)


@bp.route("/benefits/enrollment-periods/<period_id>/close", methods=["POST"])
@require_roles("BenefitsAdmin")
def close_period(period_id):
    record = db.enrollment_periods.get(period_id)
    if record is None:
        raise errors.not_found("Enrollment period not found")
    with db.lock:
        if record["status"] != "OPEN":
            raise errors.invalid_state("Enrollment period must be OPEN to close")
        record["status"] = "CLOSED"
        db.enrollment_periods.touch(record)
    return success(serializers.enrollment_period(record), 200)
