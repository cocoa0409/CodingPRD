"""The ten declared calculations (scaffold table 3 / PRD sections 2.8 and 3).

Every rounding is half-up; every evaluation order that could change a rounded
result is pinned exactly as the specification states it.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def rhu(value, places):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def num(value):
    """Decimal -> JSON number, keeping whole values as ints."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def present(value):
    if isinstance(value, bool):
        return value is True
    if isinstance(value, str):
        return value.strip() != ""
    return False


def whole_days(start, end):
    """Whole days from start to end, discarding the fractional day."""
    if start is None or end is None:
        return 0
    return (end - start).days


def whole_hours_decimal(start, end):
    seconds = D((end - start).total_seconds())
    return rhu(seconds / D(3600), 2)


# --------------------------------------------------------------------------
# 1. notice_statutory_completeness
# --------------------------------------------------------------------------
NOTICE_WEIGHTS = (
    ("signature_present", 8),
    ("work_identification", 18),
    ("material_identification", 20),
    ("contact_email", 10),
    ("good_faith_statement", 18),
    ("accuracy_statement", 8),
    ("authority_statement", 18),
)
NOTICE_CORE_ORDER = (
    "signature_present",
    "work_identification",
    "material_identification",
    "good_faith_statement",
    "authority_statement",
)
SUBSTANTIAL_THRESHOLD = 92
STRICT_THRESHOLD = 100


def notice_completeness(notice, program_tier):
    score = 0
    for field, weight in NOTICE_WEIGHTS:
        if present(notice.get(field)):
            score += weight

    variant = (
        "STRICT_COMPLIANCE"
        if notice.get("submission_channel") == "API_BULK" or program_tier == "TRUSTED"
        else "SUBSTANTIAL_COMPLIANCE"
    )

    core_missing = None
    for field in NOTICE_CORE_ORDER:
        if not present(notice.get(field)):
            core_missing = field
            break

    sworn = notice.get("sworn_under_penalty") is True
    if variant == "SUBSTANTIAL_COMPLIANCE":
        clears = score >= SUBSTANTIAL_THRESHOLD
    else:
        clears = score >= STRICT_THRESHOLD and sworn

    passes = clears and core_missing is None
    if passes:
        reason = None
    elif core_missing is not None:
        reason = "CORE_ELEMENT_MISSING:" + core_missing
    elif variant == "STRICT_COMPLIANCE" and not sworn:
        reason = "UNSWORN_UNDER_STRICT_VARIANT"
    else:
        reason = "SCORE_BELOW_THRESHOLD"
    return score, variant, passes, reason


# --------------------------------------------------------------------------
# 2. counter_notice_statutory_completeness
# --------------------------------------------------------------------------
COUNTER_WEIGHTS = (
    ("signature_present", 20),
    ("material_identification", 20),
    ("good_faith_mistake_statement", 22),
    ("contact_email", 26),
    ("consent_to_jurisdiction", 6),
    ("consent_to_service_of_process", 6),
)
COUNTER_CONSENT_ORDER = ("consent_to_jurisdiction", "consent_to_service_of_process")
COUNTER_THRESHOLD = 94


def counter_completeness(counter):
    score = 0
    for field, weight in COUNTER_WEIGHTS:
        if present(counter.get(field)):
            score += weight

    consent_missing = None
    for field in COUNTER_CONSENT_ORDER:
        if not present(counter.get(field)):
            consent_missing = field
            break

    passes = score >= COUNTER_THRESHOLD and consent_missing is None
    if passes:
        reason = None
    elif consent_missing is not None:
        reason = "CONSENT_MISSING:" + consent_missing
    else:
        reason = "SCORE_BELOW_THRESHOLD"
    return score, passes, reason


# --------------------------------------------------------------------------
# 3. account_strike_points
# --------------------------------------------------------------------------
STRIKE_BASE_POINTS = 10
DECAY_FACTORS = (Decimal("1.0"), Decimal("0.65"), Decimal("0.325"))
TIER_WEIGHTS = {"STANDARD": 1.0, "VERIFIED": 1.5, "TRUSTED": 2.0}


def decay_factor(age_days, decay_step_days):
    if decay_step_days <= 0:
        return DECAY_FACTORS[0]
    step = age_days // decay_step_days
    if step < 0:
        step = 0
    if step <= 2:
        return DECAY_FACTORS[step]
    return Decimal("0.0")


def strike_points(weight, age_days, decay_step_days):
    factor = decay_factor(age_days, decay_step_days)
    return rhu(D(STRIKE_BASE_POINTS) * D(weight) * factor, 2)


def total_strike_points(strikes, clock, decay_step_days):
    """strikes: iterable of records already filtered to ACTIVE/DECAYED."""
    ordered = sorted(strikes, key=lambda record: record["accrued_at"])
    running = Decimal(0)
    for record in ordered:
        age = whole_days(record["accrued_at"], clock)
        running += strike_points(record["weight"], age, decay_step_days)
    return rhu(running, 2)


# --------------------------------------------------------------------------
# 4. restoration_window
# --------------------------------------------------------------------------
RESTORE_MIN_BUSINESS_DAYS = 10
RESTORE_MAX_BUSINESS_DAYS = 14
PROVIDER_HOLIDAYS = frozenset(
    [
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 11, 27),
        date(2026, 12, 25),
        date(2027, 1, 1),
    ]
)


def is_business_day(moment):
    return moment.weekday() < 5 and moment.date() not in PROVIDER_HOLIDAYS


def add_business_days(anchor, count):
    """The anchor instant itself never counts; its UTC time-of-day is preserved."""
    moment = anchor
    counted = 0
    while counted < count:
        moment = moment + timedelta(days=1)
        if is_business_day(moment):
            counted += 1
    return moment


def restoration_window(forwarded_at):
    return (
        add_business_days(forwarded_at, RESTORE_MIN_BUSINESS_DAYS),
        add_business_days(forwarded_at, RESTORE_MAX_BUSINESS_DAYS),
    )


# --------------------------------------------------------------------------
# 5. misrepresentation_penalty
# --------------------------------------------------------------------------
PER_ITEM_BASE_CENTS = 25000
DAILY_HARM_CENTS = 1500
SURCHARGE_TIER1_FLOOR = 100000
SURCHARGE_TIER2_FLOOR = 500000
SURCHARGE_RATE_TIER1 = Decimal("0.10")
SURCHARGE_RATE_TIER2 = Decimal("0.20")


def misrepresentation_penalty(affected_claim_count, disabled_day_count):
    base = PER_ITEM_BASE_CENTS * affected_claim_count + DAILY_HARM_CENTS * disabled_day_count
    # The tier is selected from the BASE and never re-selected from the total.
    if base >= SURCHARGE_TIER2_FLOOR:
        rate = SURCHARGE_RATE_TIER2
    elif base >= SURCHARGE_TIER1_FLOOR:
        rate = SURCHARGE_RATE_TIER1
    else:
        rate = Decimal("0")
    surcharge = int(rhu(D(base) * rate, 0))
    return base, surcharge, base + surcharge


# --------------------------------------------------------------------------
# 6. safe_harbor_compliance_score
# --------------------------------------------------------------------------
RESPONSE_WEIGHT = 40
RESPONSE_TARGET_HOURS = 48
RESTORATION_WEIGHT = 30
OVERDUE_PENALTY = 6
TERMINATION_WEIGHT = 20
CONTACT_WEIGHT = 10
ELIGIBLE_FLOOR = 85
AT_RISK_FLOOR = 60


def median_response_hours(latencies):
    ordered = sorted(latencies)
    count = len(ordered)
    if count == 0:
        return Decimal("0")
    if count % 2 == 1:
        return ordered[count // 2]
    lower = ordered[count // 2 - 1]
    upper = ordered[count // 2]
    return rhu((lower + upper) / D(2), 2)


def response_component(median_hours):
    ratio = (D(RESPONSE_TARGET_HOURS) - D(median_hours)) / D(RESPONSE_TARGET_HOURS)
    if ratio < 0:
        ratio = Decimal(0)
    if ratio > 1:
        ratio = Decimal(1)
    return rhu(D(RESPONSE_WEIGHT) * ratio, 2)


def restoration_component(overdue_count):
    value = D(RESTORATION_WEIGHT) - D(OVERDUE_PENALTY) * D(overdue_count)
    if value < 0:
        value = Decimal(0)
    return rhu(value, 2)


def posture_for_score(score):
    if score >= ELIGIBLE_FLOOR:
        return "ELIGIBLE"
    if score >= AT_RISK_FLOOR:
        return "AT_RISK"
    return "FORFEITED"


# --------------------------------------------------------------------------
# 7. reference_match_confidence
# --------------------------------------------------------------------------
SIMILARITY_WEIGHT = Decimal("0.80")
REGISTRATION_WEIGHT = Decimal("0.20")
MIN_CONFIDENCE = {
    "STANDARD": Decimal("1.0"),
    "VERIFIED": Decimal("0.95"),
    "TRUSTED": Decimal("0.90"),
}


def prefix_length(left, right):
    length = 0
    for a, b in zip(left or "", right or ""):
        if a != b:
            break
        length += 1
    return length


def match_confidence(item_fingerprint, reference):
    shared = prefix_length(item_fingerprint, reference.get("fingerprint_hash"))
    bonus = REGISTRATION_WEIGHT if reference.get("registration_number") is not None else Decimal(0)
    return rhu(SIMILARITY_WEIGHT * D(shared) / D(32) + bonus, 4)


def select_reference(item_fingerprint, candidates, program_tier):
    """candidates: ACTIVE reference files of the notice's holder, any order."""
    floor = MIN_CONFIDENCE.get(program_tier, Decimal("1.0"))
    scored = []
    for reference in candidates:
        confidence = match_confidence(item_fingerprint, reference)
        if confidence >= floor:
            scored.append((confidence, reference))
    if not scored:
        return None, None
    # confidence DESC, then created_at ASC; id is never consulted.
    scored.sort(key=lambda pair: (-pair[0], pair[1]["created_at"]))
    confidence, reference = scored[0]
    return reference, confidence


# --------------------------------------------------------------------------
# 8. rights_holder_abuse_score
# --------------------------------------------------------------------------
WITHDRAWN_WEIGHT = 1
REJECTED_WEIGHT = 2
MISREPRESENTATION_WEIGHT = 3
VOLUME_FLOOR = 5
AUTO_OPEN_FLOOR = Decimal("40")
SUSPENSION_FLOOR = Decimal("70")


def abuse_score(withdrawn_count, rejected_count, misrepresentation_count, notices_processed):
    weighted = (
        WITHDRAWN_WEIGHT * withdrawn_count
        + REJECTED_WEIGHT * rejected_count
        + MISREPRESENTATION_WEIGHT * misrepresentation_count
    )
    denominator = max(notices_processed, VOLUME_FLOOR)
    return rhu(D(100) * D(weighted) / D(denominator), 2)


# --------------------------------------------------------------------------
# 9. ingestion_window_quota / 10. claim_dispute_interval_overlap
# --------------------------------------------------------------------------
WINDOW_HOURS = 24
REGISTRATION_TERM_DAYS = 1095


def window_start(clock):
    return clock - timedelta(hours=WINDOW_HOURS)


def interval_occupied(clock, disabled_at, dispute_window_days):
    """Half-open [disabled_at, disabled_at + dispute_window_days)."""
    if disabled_at is None:
        return False
    upper = disabled_at + timedelta(days=dispute_window_days)
    return disabled_at <= clock < upper
