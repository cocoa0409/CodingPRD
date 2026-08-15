"""Business logic calculations: seat-time, refunds, pass rates, fees, etc."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
import db


DAILY_CREDIT_CAP_MINUTES = 480
ADMIN_FEE_CENTS = 5000
STATUTORY_ADMIN_FEE_CENTS = 1000
REGISTRATION_FEE_HIGH_CENTS = 2500
REGISTRATION_FEE_LOW_CENTS = 1500
FEE_TIER_THRESHOLD_CENTS = 100000
PASS_RATE_WINDOW_DAYS = 90
PASS_RATE_MIN_ATTEMPTS = 10
LATE_FEE_BASE_CENTS = 5000
LATE_FEE_PER_DAY_CENTS = 1000
LATE_FEE_CAP_CENTS = 50000
REPORTING_DEADLINE_DAYS = 30


def round_half_up_decimal(value):
    """Round a Decimal to integer using ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_order_total_cents(tuition_cents, scholarship_cents):
    """Pinned order: scholarship cap -> discounted tuition -> fee tier -> total."""
    scholarship_applied = min(scholarship_cents, tuition_cents // 2)
    discounted_tuition = tuition_cents - scholarship_applied
    if discounted_tuition >= FEE_TIER_THRESHOLD_CENTS:
        registration_fee = REGISTRATION_FEE_HIGH_CENTS
    else:
        registration_fee = REGISTRATION_FEE_LOW_CENTS
    charge_total_cents = discounted_tuition + registration_fee
    return charge_total_cents


def compute_seat_minutes(enrollment_id, course):
    """Recompute verified_seat_minutes, creditable_seat_minutes, completion_fraction_bps."""
    records = [
        r for r in db.attendance_records.values()
        if r["enrollment_id"] == enrollment_id and r["status"] == "VERIFIED"
    ]
    # Sort chronological: session_date ASC, ties by created_at ASC
    records.sort(key=lambda r: (r["session_date"], r["created_at"]))

    verified_total = sum(r["minutes"] for r in records)

    day_totals = {}
    creditable = 0
    for r in records:
        sd = r["session_date"]
        current = day_totals.get(sd, 0)
        headroom = max(0, DAILY_CREDIT_CAP_MINUTES - current)
        credited = min(r["minutes"], headroom)
        day_totals[sd] = current + credited
        creditable += credited

    required = course["required_seat_minutes"]
    if required > 0:
        frac = Decimal(creditable) * Decimal(10000) / Decimal(required)
        completion_fraction_bps = round_half_up_decimal(frac)
    else:
        completion_fraction_bps = 0

    return verified_total, creditable, completion_fraction_bps


def compute_refund_scheduled(paid_cents, completion_fraction_bps, reason):
    """Published tier schedule refund."""
    if reason == "SCHOOL_CANCELLED":
        return paid_cents

    f = completion_fraction_bps
    if f <= 1000:
        pct = Decimal("0.90")
    elif f <= 2500:
        pct = Decimal("0.75")
    elif f <= 5000:
        pct = Decimal("0.50")
    else:
        pct = Decimal("0.00")

    tiered = round_half_up_decimal(Decimal(paid_cents) * pct)

    if reason == "ADMINISTRATIVE":
        return tiered
    else:  # VOLUNTARY
        return max(0, tiered - ADMIN_FEE_CENTS)


def compute_refund_statutory(paid_cents, offering_start_date, offering_end_date, withdrawal_date):
    """Statutory pro-rata refund with pinned nested rounding."""
    total_days = (offering_end_date - offering_start_date).days + 1
    elapsed_days = (withdrawal_date - offering_start_date).days + 1
    elapsed_days = max(0, min(elapsed_days, total_days))

    # Round daily rate FIRST, then multiply
    daily_rate = round_half_up_decimal(Decimal(paid_cents) / Decimal(total_days))
    earned_cents = daily_rate * elapsed_days
    statutory = max(0, paid_cents - earned_cents - STATUTORY_ADMIN_FEE_CENTS)
    return statutory


def compute_granted_refund(scheduled, statutory):
    return max(scheduled, statutory)


def compute_pass_rate(school_id, window_end_date):
    """Compute pass rates over trailing 90-day window ending at window_end_date (inclusive)."""
    window_start = window_end_date - timedelta(days=PASS_RATE_WINDOW_DAYS)

    # Find all enrollments belonging to this school (via course -> offering -> enrollment)
    school_course_ids = {c["id"] for c in db.courses.values() if c["school_id"] == school_id}
    school_offering_ids = {o["id"] for o in db.offerings.values() if o["course_id"] in school_course_ids}
    school_enrollment_ids = {e["id"] for e in db.enrollments.values() if e["offering_id"] in school_offering_ids}

    first_attempts = []
    all_attempts = []

    for att in db.exam_attempts.values():
        if att["enrollment_id"] not in school_enrollment_ids:
            continue
        if att["status"] != "SCORED":
            continue
        scored_date = _extract_date(att["scored_at"])
        if scored_date is None:
            continue
        if window_start <= scored_date <= window_end_date:
            all_attempts.append(att)
            if att["attempt_number"] == 1:
                first_attempts.append(att)

    first_count = len(first_attempts)
    all_count = len(all_attempts)

    first_rate = None
    if first_count > 0:
        passed = sum(1 for a in first_attempts if a.get("outcome") == "PASSED")
        first_rate = round_half_up_decimal(Decimal(passed) * Decimal(10000) / Decimal(first_count))

    all_rate = None
    if all_count > 0:
        passed_all = sum(1 for a in all_attempts if a.get("outcome") == "PASSED")
        all_rate = round_half_up_decimal(Decimal(passed_all) * Decimal(10000) / Decimal(all_count))

    return {
        "window_start": window_start,
        "window_end": window_end_date,
        "first_attempt_count": first_count,
        "first_attempt_pass_rate_bps": first_rate,
        "all_attempt_count": all_count,
        "all_attempts_pass_rate_bps": all_rate,
    }


def _extract_date(dt_input):
    """Extract a date from a datetime or date or ISO string."""
    if dt_input is None:
        return None
    if isinstance(dt_input, date):
        return dt_input
    if isinstance(dt_input, str):
        try:
            from datetime import datetime
            s_clean = dt_input.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s_clean)
            return dt.date() if hasattr(dt, 'date') else dt
        except (ValueError, TypeError):
            return None
    if hasattr(dt_input, 'date'):
        return dt_input.date()
    return dt_input


def compute_late_fee(reporting_deadline_date, submit_date):
    """Compute late_days and late_fee_cents."""
    late_days = max(0, (submit_date - reporting_deadline_date).days)
    if late_days == 0:
        return 0, 0
    fee = min(LATE_FEE_CAP_CENTS, LATE_FEE_BASE_CENTS + LATE_FEE_PER_DAY_CENTS * late_days)
    return late_days, fee


def compute_reporting_deadline(period_end):
    """period_end + 30 calendar days."""
    return period_end + timedelta(days=REPORTING_DEADLINE_DAYS)


def round_to_half_hour(hours):
    """Round credit hours to nearest 0.5 with halves rounded up."""
    d = Decimal(str(hours))
    doubled = d * 2
    rounded_doubled = doubled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    result = rounded_doubled / 2
    return float(result)


def compute_exam_attempts_used(enrollment_id):
    """Count attempts in SCHEDULED, PROCTORED, SCORED, NO_SHOW (INVALIDATED excluded)."""
    return sum(
        1 for a in db.exam_attempts.values()
        if a["enrollment_id"] == enrollment_id
        and a["status"] in ("SCHEDULED", "PROCTORED", "SCORED", "NO_SHOW")
    )


def compute_enrolled_count(offering_id):
    """Count enrollments with academic_status NOT IN {WITHDRAWN, FAILED, EXPIRED}."""
    return sum(
        1 for e in db.enrollments.values()
        if e["offering_id"] == offering_id
        and e["academic_status"] not in ("WITHDRAWN", "FAILED", "EXPIRED")
    )


def update_offering_counts(offering):
    """Recompute enrolled_count and seats_available."""
    enrolled = compute_enrolled_count(offering["id"])
    offering["enrolled_count"] = enrolled
    offering["seats_available"] = offering["capacity"] - enrolled


def build_credit_report_lines(school_id, period_start, period_end):
    """Build line_items for a base credit report."""
    # Get all certificates for this school
    school_course_ids = {c["id"] for c in db.courses.values() if c["school_id"] == school_id}
    school_offering_ids = {o["id"] for o in db.offerings.values() if o["course_id"] in school_course_ids}
    school_enrollment_ids = {e["id"] for e in db.enrollments.values() if e["offering_id"] in school_offering_ids}

    certs = []
    for cert in db.certificates.values():
        if cert["enrollment_id"] not in school_enrollment_ids:
            continue
        if cert["status"] != "ACTIVE":
            continue
        if cert["credit_hours_pinned"] <= 0:
            continue
        issue_d = _extract_date(cert["issue_date"])
        if issue_d is None:
            continue
        if period_start <= issue_d <= period_end:
            enrollment = db.enrollments.get(cert["enrollment_id"])
            certs.append({
                "certificate_id": cert["id"],
                "enrollment_id": cert["enrollment_id"],
                "student_id": enrollment["student_id"] if enrollment else None,
                "credit_hours": round_to_half_hour(cert["credit_hours_pinned"]),
                "_issue_date": issue_d,
                "_created_at": cert["created_at"],
            })

    # Sort: issue_date ASC, tie-break created_at ASC
    certs.sort(key=lambda c: (c["_issue_date"], c["_created_at"]))

    # Remove internal sort keys
    line_items = []
    for c in certs:
        line_items.append({
            "certificate_id": c["certificate_id"],
            "enrollment_id": c["enrollment_id"],
            "student_id": c["student_id"],
            "credit_hours": c["credit_hours"],
        })

    total = sum(li["credit_hours"] for li in line_items)
    return line_items, total


def build_amendment_lines(parent_report):
    """Build line_items for an amendment: parent's lines whose cert is REVOKED, negated."""
    line_items = []
    for li in parent_report.get("line_items", []):
        cert = db.certificates.get(li["certificate_id"])
        if cert and cert["status"] == "REVOKED":
            line_items.append({
                "certificate_id": li["certificate_id"],
                "enrollment_id": li["enrollment_id"],
                "student_id": li["student_id"],
                "credit_hours": -li["credit_hours"],
            })
    total = sum(li["credit_hours"] for li in line_items)
    return line_items, total


def assign_certificate_number(school):
    """Assign next certificate number for the school in the current year."""
    issue_year = db.today().year
    school_course_ids = {c["id"] for c in db.courses.values() if c["school_id"] == school["id"]}
    school_offering_ids = {o["id"] for o in db.offerings.values() if o["course_id"] in school_course_ids}
    school_enrollment_ids = {e["id"] for e in db.enrollments.values() if e["offering_id"] in school_offering_ids}

    count = sum(
        1 for cert in db.certificates.values()
        if cert["enrollment_id"] in school_enrollment_ids
        and _extract_date(cert["issue_date"]) is not None
        and _extract_date(cert["issue_date"]).year == issue_year
    )
    seq = count + 1
    return f"{school['school_code']}-{issue_year}-{seq:04d}"
