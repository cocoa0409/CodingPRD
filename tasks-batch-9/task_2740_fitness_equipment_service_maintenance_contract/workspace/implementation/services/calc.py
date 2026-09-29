"""Domain constants and the arithmetic rules (money, durations, scores)."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Declared vocabularies
# ---------------------------------------------------------------------------
CATEGORIES = ("TREADMILL", "ELLIPTICAL", "BIKE", "STRENGTH")
COVERAGE_TIERS = ("BRONZE", "SILVER", "GOLD")
PARTS_INCLUSIONS = ("NONE", "WEAR_ONLY", "FULL")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
PART_CATEGORIES = ("CONSUMABLE", "WEAR", "STRUCTURAL", "ELECTRONIC")
PART_SOURCES = ("NEW", "REFURBISHED", "LOANER_SWAP")
DUTY_STATUSES = ("ON_DUTY", "OFF_DUTY")
CHECKLIST_RESULTS = ("PASS", "FAIL")
LOCKOUT_REASONS = (
    "INSPECTOR_TAG_OUT",
    "SAFETY_DOC_REJECTED",
    "SAFETY_CRITICAL_FAIL",
    "MEMBER_INJURY",
)

LIVE_CONTRACT_STATUSES = ("ACTIVE", "SUSPENDED", "RENEWAL_QUOTED")
LIVE_CALL_STATUSES = ("OPEN", "DISPATCHED", "ON_SITE", "PARTS_HOLD")
HELD_ASSIGNMENT_STATUSES = ("RESERVED", "CONFIRMED")

# ---------------------------------------------------------------------------
# Pinned tier tables
# ---------------------------------------------------------------------------
SLA_RESPONSE_MINUTES = {"BRONZE": 480, "SILVER": 240, "GOLD": 120}
PM_MIN_VISITS = {"BRONZE": 1, "SILVER": 2, "GOLD": 4}
CREDIT_GRACE_MINUTES = {"BRONZE": 720, "SILVER": 360, "GOLD": 180}
CREDIT_RATE_CENTS_PER_HOUR = {"BRONZE": 400, "SILVER": 900, "GOLD": 1600}
CREDIT_CAP_PCT = Decimal("0.15")

SEVERITY_SLA_FACTOR = {
    "CRITICAL": Decimal("0.5"),
    "MAJOR": Decimal("1.0"),
    "MINOR": Decimal("2.0"),
}
SEVERITY_PLANNED_MINUTES = {"CRITICAL": 180, "MAJOR": 120, "MINOR": 60}

SOURCE_PRICE_FACTOR = {
    "NEW": Decimal("1.00"),
    "REFURBISHED": Decimal("0.60"),
    "LOANER_SWAP": Decimal("0.00"),
}
PARTS_SURCHARGE_PCT = {
    "NONE": Decimal("0.00"),
    "WEAR_ONLY": Decimal("0.08"),
    "FULL": Decimal("0.18"),
}

TRAVEL_BUFFER_MINUTES = 45
VISIT_MAX_SPAN_MINUTES = 480
PARTS_HOLD_LIMIT = 3
PM_INTERVAL_DUE_FACTOR = Decimal("1.25")

REPLACEMENT_THRESHOLD_UNSUPPORTED = Decimal("60.00")
REPLACEMENT_THRESHOLD_DEFAULT = Decimal("40.00")

RISK_HIGH_RATIO = Decimal("0.30")
RISK_MODERATE_RATIO = Decimal("0.15")

QUOTE_VALID_DAYS = 30
QUOTE_FLOOR_PCT = Decimal("0.90")
QUOTE_CAP_PCT = Decimal("1.35")
HISTORY_LOAD_CAP = Decimal("0.25")
HISTORY_BREACH_LOAD = Decimal("0.03")
HISTORY_CRITICAL_LOAD = Decimal("0.015")
CONDITION_REPLACEMENT_ADDER = Decimal("0.25")
CONDITION_UNSUPPORTED_ADDER = Decimal("0.20")
CONDITION_ANNOUNCED_ADDER = Decimal("0.10")

TRAILING_WINDOW_DAYS = 365
YEAR_DAYS = 365

FAILURE_VARIANT_MIN_CALLS = 3
SEVERITY_WEIGHT = {
    "CRITICAL": Decimal("8"),
    "MAJOR": Decimal("4"),
    "MINOR": Decimal("2"),
}


# ---------------------------------------------------------------------------
# Rounding and duration primitives
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def money2(value):
    """Two-decimal half-up rounding for reported ratios and scores."""
    return rhu(value, 2)


def floor_minutes(delta):
    """Elapsed duration floored to whole minutes."""
    if isinstance(delta, timedelta):
        seconds = delta.total_seconds()
    else:
        seconds = float(delta)
    return int(seconds // 60)


def minutes_between(start, end):
    return floor_minutes(end - start)


def parse_day(value):
    parts = [int(p) for p in value.split("-")]
    return date(parts[0], parts[1], parts[2])


def day_start(value):
    """Midnight UTC of a YYYY-MM-DD calendar day."""
    d = parse_day(value)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def whole_years(from_day, to_moment):
    """floor(elapsed days / 365) between a calendar day and an instant's day."""
    start = parse_day(from_day) if isinstance(from_day, str) else from_day
    end = to_moment.date() if isinstance(to_moment, datetime) else to_moment
    elapsed = (end - start).days
    if elapsed < 0:
        return 0
    return elapsed // YEAR_DAYS


def period_key_of(moment):
    return "%04d-%02d" % (moment.year, moment.month)


# ---------------------------------------------------------------------------
# Preventive-maintenance status and compliance
# ---------------------------------------------------------------------------
def pm_status_for(usage_hours, usage_hours_at_last_pm, pm_interval_hours):
    since = dec(usage_hours) - dec(usage_hours_at_last_pm)
    interval = dec(pm_interval_hours)
    if since < interval:
        return "OK"
    if since < interval * PM_INTERVAL_DUE_FACTOR:
        return "DUE"
    return "OVERDUE"


def pm_compliance_pct(completed, missed):
    denominator = completed + missed
    if denominator == 0:
        return Decimal("100.00")
    return money2(dec(100) * dec(completed) / dec(denominator))


# ---------------------------------------------------------------------------
# Condition score
# ---------------------------------------------------------------------------
def replacement_threshold(support_status):
    if support_status == "UNSUPPORTED":
        return REPLACEMENT_THRESHOLD_UNSUPPORTED
    return REPLACEMENT_THRESHOLD_DEFAULT


def usage_based_score(usage_hours, expected_service_life_hours, age_years):
    life = dec(expected_service_life_hours)
    if life <= 0:
        ratio = Decimal(0)
    else:
        ratio = dec(usage_hours) / life
    raw = dec(100) - dec(100) * ratio - dec(2) * dec(age_years)
    return clamp_score(raw)


def failure_based_score(counts, downtime_minutes_ytd):
    raw = dec(100)
    for severity, weight in SEVERITY_WEIGHT.items():
        raw = raw - weight * dec(counts.get(severity, 0))
    raw = raw - dec(downtime_minutes_ytd) / dec(60)
    return clamp_score(raw)


def clamp_score(raw):
    score = money2(raw)
    if score < Decimal("0.00"):
        return Decimal("0.00")
    if score > Decimal("100.00"):
        return Decimal("100.00")
    return score


def fleet_risk(candidate_count, covered_count):
    if covered_count <= 0:
        ratio = Decimal(0)
    else:
        ratio = dec(candidate_count) / dec(covered_count)
    if ratio >= RISK_HIGH_RATIO:
        return "HIGH"
    if ratio >= RISK_MODERATE_RATIO:
        return "MODERATE"
    return "LOW"


# ---------------------------------------------------------------------------
# Service-call response targets
# ---------------------------------------------------------------------------
def sla_target_minutes(contract_sla_minutes, severity):
    return rhu_int(dec(contract_sla_minutes) * SEVERITY_SLA_FACTOR[severity])


# ---------------------------------------------------------------------------
# Downtime and credit
# ---------------------------------------------------------------------------
def operating_overlap_minutes(started_at, effective_end_at, open_minute, close_minute):
    """Day-by-day overlap of [started, end) with each day's operating window."""
    if effective_end_at <= started_at:
        return 0
    total_seconds = 0
    cursor = datetime(started_at.year, started_at.month, started_at.day, tzinfo=timezone.utc)
    last = datetime(effective_end_at.year, effective_end_at.month, effective_end_at.day,
                    tzinfo=timezone.utc)
    while cursor <= last:
        window_open = cursor + timedelta(minutes=open_minute)
        window_close = cursor + timedelta(minutes=close_minute)
        overlap_start = max(started_at, window_open)
        overlap_end = min(effective_end_at, window_close)
        if overlap_end > overlap_start:
            total_seconds += (overlap_end - overlap_start).total_seconds()
        cursor = cursor + timedelta(days=1)
    return int(total_seconds // 60)


def credit_cents(billable_minutes, coverage_tier, grace_minutes=None):
    grace = CREDIT_GRACE_MINUTES[coverage_tier] if grace_minutes is None else grace_minutes
    rate = CREDIT_RATE_CENTS_PER_HOUR[coverage_tier]
    billable = dec(billable_minutes) - dec(grace)
    if billable < 0:
        billable = Decimal(0)
    return rhu_int(billable / dec(60) * dec(rate))


def credit_cap_cents(annual_base_cents):
    return rhu_int(dec(annual_base_cents) * CREDIT_CAP_PCT)


# ---------------------------------------------------------------------------
# Renewal quote pricing
# ---------------------------------------------------------------------------
def age_multiplier(age_years):
    if age_years <= 2:
        return Decimal("1.00")
    if age_years <= 5:
        return Decimal("1.15")
    if age_years <= 8:
        return Decimal("1.35")
    return Decimal("1.60")


def condition_multiplier(replacement_recommended, support_status):
    multiplier = Decimal("1.00")
    if replacement_recommended:
        multiplier += CONDITION_REPLACEMENT_ADDER
    if support_status == "UNSUPPORTED":
        multiplier += CONDITION_UNSUPPORTED_ADDER
    if support_status == "END_OF_SUPPORT_ANNOUNCED":
        multiplier += CONDITION_ANNOUNCED_ADDER
    return multiplier


def history_load_pct(sla_breach_count, critical_call_count):
    load = HISTORY_BREACH_LOAD * dec(sla_breach_count) + HISTORY_CRITICAL_LOAD * dec(critical_call_count)
    if load > HISTORY_LOAD_CAP:
        return HISTORY_LOAD_CAP
    return load


def compliance_discount_pct(pm_compliance):
    compliance = dec(pm_compliance)
    if compliance >= Decimal("90.00"):
        return Decimal("0.05")
    if compliance >= Decimal("75.00"):
        return Decimal("0.02")
    return Decimal("0.00")
