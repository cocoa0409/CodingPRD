"""Domain calculations, derived fields, and cascading side effects."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from store import db, now_iso
from common import touch

# ---- constants ----
LEVELS_ORDER = {"NONE": 0, "PUPPY": 1, "BASIC": 2, "INTERMEDIATE": 3, "ADVANCED": 4}
CLASS_LEVELS = {"PUPPY", "BASIC", "INTERMEDIATE", "ADVANCED"}
PREREQ_LEVELS = {"NONE", "PUPPY", "BASIC", "INTERMEDIATE"}
REQUIRED_VACCINES = ("RABIES", "DHPP", "BORDETELLA")
INTAKE_FLAG_THRESHOLD = 7
TRAINER_BUFFER_MIN = 15
BULK_THRESHOLD = 8
BULK_DISCOUNT = Decimal("0.10")
BONUS_CREDITS = 1

PACKAGE_TIERS = {
    "STARTER": (4, 20000),
    "VALUE": (8, 36000),
    "PRO": (16, 64000),
}


def round_half_up(value):
    """Round a Decimal/rational to a whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 datetime/date string to an aware UTC datetime."""
    if value is None:
        return None
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Plain date (YYYY-MM-DD)
        try:
            dt = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def date_of(value):
    dt = parse_dt(value)
    if dt is None:
        return None
    return dt.date()


# ---------------------------------------------------------------------------
# tiered_package_pricing
# ---------------------------------------------------------------------------
def compute_package_pricing(tier):
    base_credits, base_price = PACKAGE_TIERS[tier]
    bulk = base_credits >= BULK_THRESHOLD
    discount = BULK_DISCOUNT if bulk else Decimal("0")
    price_paid = round_half_up(Decimal(base_price) * (Decimal("1") - discount))
    credits_total = base_credits + (BONUS_CREDITS if bulk else 0)
    return credits_total, price_paid


# ---------------------------------------------------------------------------
# Package credit position (from redemption ledger)
# ---------------------------------------------------------------------------
def package_credits_consumed(package_id):
    consumed = 0
    for red in db.package_redemptions.values():
        if red["package_id"] != package_id:
            continue
        if red["kind"] == "DEBIT":
            consumed += red["credits"]
        elif red["kind"] == "REVERSAL":
            consumed -= red["credits"]
    return consumed


def recompute_package(package):
    """Recompute credits_consumed/remaining and auto ACTIVE<->DEPLETED."""
    consumed = package_credits_consumed(package["id"])
    remaining = package["credits_total"] - consumed
    changed = (package["credits_consumed"] != consumed or
               package["credits_remaining"] != remaining)
    package["credits_consumed"] = consumed
    package["credits_remaining"] = remaining
    status_changed = False
    if package["status"] != "EXPIRED":
        if remaining == 0 and package["status"] == "ACTIVE":
            package["status"] = "DEPLETED"
            status_changed = True
        elif remaining > 0 and package["status"] == "DEPLETED":
            package["status"] = "ACTIVE"
            status_changed = True
    if changed or status_changed:
        touch(package)
    return package


# ---------------------------------------------------------------------------
# package_credit_valuation
# ---------------------------------------------------------------------------
def compute_valuation(package):
    credits_remaining = package["credits_remaining"]
    credits_total = package["credits_total"]
    price = package["price_paid_cents"]
    per_credit_value = Decimal(price) / Decimal(credits_total)
    per_credit_rounded = round_half_up(per_credit_value)
    per_credit_valuation = per_credit_rounded * credits_remaining
    blended = round_half_up(Decimal(price) * Decimal(credits_remaining) / Decimal(credits_total))
    return per_credit_valuation, blended


# ---------------------------------------------------------------------------
# vaccination_posture
# ---------------------------------------------------------------------------
def compute_vaccination_posture(dog_id, reference_date):
    """reference_date is a date object."""
    records = [v for v in db.vaccinations.values()
               if v["dog_id"] == dog_id and not v["voided"]]
    if not records:
        return "UNKNOWN"
    for vtype in REQUIRED_VACCINES:
        covered = False
        for r in records:
            if r["vaccine_type"] != vtype:
                continue
            adm = date_of(r["administered_on"])
            exp = date_of(r["expires_on"])
            if adm is None or exp is None:
                continue
            # half-open: administered_on <= ref < expires_on
            if adm <= reference_date < exp:
                covered = True
                break
        if not covered:
            return "NONCOMPLIANT"
    return "COMPLIANT"


def dog_posture_now(dog_id):
    ref = db.current_clock().date()
    return compute_vaccination_posture(dog_id, ref)


def series_first_session_date(series_id):
    """Date of the series' first non-makeup session's starts_at, or None."""
    sessions = [s for s in db.class_sessions.values()
                if s["series_id"] == series_id and not s["is_makeup_slot"]]
    if not sessions:
        return None
    sessions.sort(key=lambda s: (s["sequence_index"], s["starts_at"]))
    return date_of(sessions[0]["starts_at"])


# ---------------------------------------------------------------------------
# Dog computed facets
# ---------------------------------------------------------------------------
def compute_highest_completed_level(dog_id):
    best = "NONE"
    for e in db.enrollments.values():
        if e["dog_id"] != dog_id or e["status"] != "GRADUATED":
            continue
        series = db.class_series.get(e["series_id"])
        if not series:
            continue
        lvl = series["level"]
        if LEVELS_ORDER[lvl] > LEVELS_ORDER[best]:
            best = lvl
    return best


def compute_intake_status(dog_id):
    intakes = [i for i in db.behavioral_intakes.values() if i["dog_id"] == dog_id]
    if not intakes:
        return "PENDING"
    intakes.sort(key=lambda i: (i["created_at"], i["id"]))
    return intakes[-1]["outcome"]


def refresh_dog_computed(dog):
    """Recompute computed fields without mutating version (read-time refresh)."""
    dog["vaccination_posture"] = dog_posture_now(dog["id"])
    dog["highest_completed_level"] = compute_highest_completed_level(dog["id"])
    dog["intake_status"] = compute_intake_status(dog["id"])


# ---------------------------------------------------------------------------
# intake_outcome
# ---------------------------------------------------------------------------
def compute_intake_outcome(reactivity_score, bite_history):
    flagged = bite_history is True or reactivity_score >= INTAKE_FLAG_THRESHOLD
    return "FLAGGED" if flagged else "CLEARED"


# ---------------------------------------------------------------------------
# seat_accounting
# ---------------------------------------------------------------------------
def seat_holding_count(series_id):
    return sum(1 for e in db.enrollments.values()
               if e["series_id"] == series_id and e["status"] in ("ACTIVE", "SUSPENDED"))


def enrolled_count(series_id):
    return sum(1 for e in db.enrollments.values()
               if e["series_id"] == series_id and e["status"] in ("ACTIVE", "GRADUATED"))


def seats_available_raw(series):
    return series["capacity"] - seat_holding_count(series["id"])


def recompute_series_seats(series):
    """Recompute enrolled_count + seats_available (display-floored at 0); mutates."""
    new_enrolled = enrolled_count(series["id"])
    raw = seats_available_raw(series)
    new_seats = max(0, raw)
    changed = (series.get("enrolled_count") != new_enrolled or
               series.get("seats_available") != new_seats)
    series["enrolled_count"] = new_enrolled
    series["seats_available"] = new_seats
    if changed:
        touch(series)


# ---------------------------------------------------------------------------
# enrollment_progress
# ---------------------------------------------------------------------------
def compute_sessions_attended(enrollment_id):
    count = 0
    for a in db.attendance_records.values():
        if a["enrollment_id"] != enrollment_id:
            continue
        if a["state"] == "PRESENT":
            session = db.class_sessions.get(a["session_id"])
            if session and not session["is_makeup_slot"]:
                count += 1
        elif a["state"] == "MAKEUP_DONE":
            count += 1
    return count


def refresh_enrollment_progress(enrollment):
    series = db.class_series.get(enrollment["series_id"])
    session_count = series["session_count"] if series else 0
    attended = compute_sessions_attended(enrollment["id"])
    remaining = max(0, session_count - attended)
    eligible = attended >= session_count if session_count else False
    changed = (enrollment.get("sessions_attended") != attended or
               enrollment.get("sessions_remaining") != remaining or
               enrollment.get("graduation_eligible") != eligible)
    enrollment["sessions_attended"] = attended
    enrollment["sessions_remaining"] = remaining
    enrollment["graduation_eligible"] = eligible
    return changed


def refresh_enrollment_progress_touch(enrollment):
    if refresh_enrollment_progress(enrollment):
        touch(enrollment)


# ---------------------------------------------------------------------------
# attendance makeup_eligible
# ---------------------------------------------------------------------------
def compute_makeup_eligible(attendance):
    state = attendance["state"]
    if state == "MISSED_PROVIDER":
        return True
    if state == "ABSENT":
        enrollment = db.enrollments.get(attendance["enrollment_id"])
        if enrollment:
            series = db.class_series.get(enrollment["series_id"])
            if series and series["modality"] == "PRIVATE":
                return True
    return False


def refresh_attendance_eligible(attendance):
    attendance["makeup_eligible"] = compute_makeup_eligible(attendance)


# ---------------------------------------------------------------------------
# enrollment_refund
# ---------------------------------------------------------------------------
def compute_refund(enrollment, series):
    attended = compute_sessions_attended(enrollment["id"])
    session_count = series["session_count"]
    remaining = max(0, session_count - attended)
    per_session = Decimal(series["list_price_cents"]) / Decimal(session_count)
    refund_cents = round_half_up(per_session * Decimal(remaining))
    consumed_cents = round_half_up(per_session * Decimal(attended))
    if enrollment["payment_method"] == "PACKAGE":
        credits_refunded = series["credit_cost"] if remaining > 0 else 0
    else:
        credits_refunded = 0
    return {
        "refund_cents": refund_cents,
        "consumed_value_cents": consumed_cents,
        "credits_refunded": credits_refunded,
        "remaining": remaining,
    }


# ---------------------------------------------------------------------------
# trainer overlap
# ---------------------------------------------------------------------------
def trainer_double_booked(trainer_id, starts_at, ends_at, exclude_session_id=None):
    c_start = parse_dt(starts_at)
    c_end = parse_dt(ends_at)
    for x in db.class_sessions.values():
        if x["trainer_id"] != trainer_id:
            continue
        if x["status"] == "CANCELLED":
            continue
        if exclude_session_id is not None and x["id"] == exclude_session_id:
            continue
        x_start = parse_dt(x["starts_at"])
        x_end = parse_dt(x["ends_at"])
        # gap in minutes between the two sessions
        if c_start >= x_end:
            gap = (c_start - x_end).total_seconds() / 60.0
        elif x_start >= c_end:
            gap = (x_start - c_end).total_seconds() / 60.0
        else:
            gap = -1  # they overlap
        if gap < TRAINER_BUFFER_MIN:
            return True
    return False


# ---------------------------------------------------------------------------
# dog schedule overlap
# ---------------------------------------------------------------------------
def dog_committed_intervals(dog_id, extra_session_ids=None):
    """Collect [start,end) intervals for sessions the dog is committed to.

    Committed = EXPECTED/PRESENT/MAKEUP_PENDING attendance on non-CANCELLED
    sessions across all non-WITHDRAWN enrollments of the dog.
    """
    intervals = []
    enr_ids = {e["id"] for e in db.enrollments.values()
               if e["dog_id"] == dog_id and e["status"] != "WITHDRAWN"}
    for a in db.attendance_records.values():
        if a["enrollment_id"] not in enr_ids:
            continue
        if a["state"] not in ("EXPECTED", "PRESENT", "MAKEUP_PENDING"):
            continue
        session = db.class_sessions.get(a["session_id"])
        if not session or session["status"] == "CANCELLED":
            continue
        intervals.append((parse_dt(session["starts_at"]), parse_dt(session["ends_at"])))
    if extra_session_ids:
        for sid in extra_session_ids:
            session = db.class_sessions.get(sid)
            if session and session["status"] != "CANCELLED":
                intervals.append((parse_dt(session["starts_at"]), parse_dt(session["ends_at"])))
    return intervals


def intervals_strictly_overlap(intervals, candidate_intervals):
    """True if any candidate strictly overlaps any committed interval."""
    for (a, b) in intervals:
        for (c, d) in candidate_intervals:
            if a is None or b is None or c is None or d is None:
                continue
            if a < d and c < b:
                return True
    return False
