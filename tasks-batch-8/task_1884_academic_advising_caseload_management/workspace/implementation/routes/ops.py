"""Clock, retention report, and ops daily-close endpoints."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object
from services.common import body, iso_z, parse_iso_datetime, require_fields, require_enum, touch
from services.calculations import (
    compute_is_sla_breached, recompute_advisor_loads,
    recompute_advisor_scheduled_minutes, recompute_student_risk,
)

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["to_iso8601"])
    target = parse_iso_datetime(data["to_iso8601"])
    require_role(role, ("AdvisingDirector",))
    db.set_logical_clock_iso(iso_z(target))
    return success_object({"current_utc": db.get_logical_clock_iso()})


@bp.route("/advising/reports/retention", methods=["GET"])
def retention_report():
    user_id, role = get_auth_context()
    variant = request.args.get("variant")
    cohort_year_raw = request.args.get("cohort_year")
    from_term = request.args.get("from_term_code")
    to_term = request.args.get("to_term_code")
    # request-shape validation before role authorization per pipeline
    if variant is None:
        raise ApiError(errors.ERR_VALIDATION, "variant is required", 400)
    if variant not in ("COHORT_PERSISTED", "TERM_OVER_TERM"):
        raise ApiError(errors.ERR_VALIDATION, f"Invalid variant: {variant}", 400)
    cohort_year = None
    if cohort_year_raw is not None:
        try:
            cohort_year = int(cohort_year_raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_VALIDATION, "cohort_year must be an integer", 400)
    if variant == "COHORT_PERSISTED" and cohort_year is None:
        raise ApiError(errors.ERR_VALIDATION,
                       "cohort_year is required for COHORT_PERSISTED", 400)
    if variant == "TERM_OVER_TERM" and (not from_term or not to_term):
        raise ApiError(errors.ERR_VALIDATION,
                       "from_term_code and to_term_code are required for TERM_OVER_TERM", 400)
    require_role(role, ("AdvisingDirector",))

    students = list(db.students.values())
    if variant == "COHORT_PERSISTED":
        denominator = sum(1 for s in students if s["cohort_year"] == cohort_year)
        numerator = sum(1 for s in students
                        if s["cohort_year"] == cohort_year and s["care_status"] == "ENROLLED")
    else:  # TERM_OVER_TERM
        pool = [s for s in students if from_term in s.get("enrolled_term_codes", [])]
        if cohort_year is not None:
            pool = [s for s in pool if s["cohort_year"] == cohort_year]
        denominator = len(pool)
        numerator = sum(1 for s in pool if to_term in s.get("enrolled_term_codes", []))

    if denominator == 0:
        rate = 0
        numerator = 0
        rate_out: object = 0
    else:
        rate_dec = (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)
        rate_out = float(rate_dec)
    return success_object({
        "variant": variant,
        "cohort_year": cohort_year,
        "numerator": numerator,
        "denominator": denominator,
        "rate": rate_out,
    })


@bp.route("/advising/ops/daily-close", methods=["POST"])
def daily_close():
    user_id, role = get_auth_context()
    require_role(role, ("AdvisingDirector",))
    now_iso = db.get_logical_clock_iso()
    now = parse_iso_datetime(now_iso)
    current_date = now.strftime("%Y-%m-%d")

    no_show_marked = 0
    for appt in list(db.appointments.values()):
        if appt["status"] != "SCHEDULED":
            continue
        start = parse_iso_datetime(appt["scheduled_start_at"])
        if now > start + timedelta(minutes=10):
            appt["status"] = "NO_SHOW"
            touch(appt)
            no_show_marked += 1
            student = db.students.get(appt["student_id"])
            if student:
                student["no_show_count"] = student.get("no_show_count", 0) + 1
                recompute_student_risk(student["id"])
            recompute_advisor_scheduled_minutes(appt["advisor_id"])
            # assigned advisor weighted_load recompute (student risk weight may have changed)
            if student:
                from services.calculations import get_assigned_advisor_id
                assigned = get_assigned_advisor_id(student["id"])
                if assigned:
                    recompute_advisor_loads(assigned)

    queue_expired = 0
    for ticket in list(db.dropin_tickets.values()):
        if ticket["status"] == "QUEUED" and ticket["queue_date"] < current_date:
            ticket["status"] = "LEFT"
            touch(ticket)
            queue_expired += 1

    # refresh SLA breach flags against the logical clock
    for referral in db.referrals.values():
        referral["is_sla_breached"] = compute_is_sla_breached(referral, now_iso)

    return success_object({
        "no_show_marked": no_show_marked,
        "queue_expired": queue_expired,
    })
