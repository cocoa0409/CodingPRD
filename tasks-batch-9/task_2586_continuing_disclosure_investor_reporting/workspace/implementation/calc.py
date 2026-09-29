"""Business-day calendar, deadline derivations, and every declared calculation."""
from datetime import date, timedelta
from decimal import Decimal

from core import (DB, by_seq, clock_date, date_part, day_diff, failure_events_of,
                  fmt_ts, money, num2, parse_date_str, round_half_up)

# ------------------------------------------------------ business-day calendar
MARKET_HOLIDAYS = frozenset([
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 11),
    date(2026, 11, 26), date(2026, 12, 25), date(2027, 1, 1), date(2027, 1, 18),
    date(2027, 2, 15), date(2027, 5, 31), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
])


def is_business_day(day):
    return day.weekday() < 5 and day not in MARKET_HOLIDAYS


def add_business_days(base, count):
    """The `count`-th business day strictly after `base`; base is never counted."""
    cursor = base
    remaining = count
    while remaining > 0:
        cursor = cursor + timedelta(days=1)
        if is_business_day(cursor):
            remaining -= 1
    return cursor


def roll_forward_to_business_day(day):
    cursor = day
    while not is_business_day(cursor):
        cursor = cursor + timedelta(days=1)
    return cursor


# --------------------------------------------------------------- domain constants
MATERIAL_EVENT_FILING_BUSINESS_DAYS = 10
EVENT_BACKDATE_MAX_DAYS = 30
MAJOR_DAYS_LATE = 30
MATERIAL_OBLIGATION_THRESHOLD_BP = 500
MAX_SUBMISSION_ATTEMPTS = 3
MONITORING_ACK_MAX_GAP_DAYS = 45
DEFAULT_FILING_WINDOW_DAYS = 210

PER_SE_EVENT_TYPES = frozenset([
    "PRINCIPAL_PAYMENT_DELINQUENCY", "RATING_CHANGE", "DEFEASANCE", "BOND_CALL",
])

TIER_MULTIPLIER = {
    "TIER_0": Decimal("1.00"),
    "TIER_1": Decimal("1.10"),
    "TIER_2": Decimal("1.25"),
    "TIER_3": Decimal("1.40"),
}

OPINION_MULTIPLIER = {
    "UNMODIFIED": Decimal("1.0"),
    "QUALIFIED": Decimal("0.8"),
    "UNAUDITED_INTERIM": Decimal("0.5"),
    None: Decimal("0.0"),
}

READINESS_FACTOR = {
    "READY": 1.0,
    "WAIVED": 1.0,
    "DRAFT": 0.5,
    "NOT_STARTED": 0.0,
    "VOID": 0.0,
}

OPEN_CYCLE_STATUSES = ("DRAFTING", "READY_TO_FILE", "FILING_IN_PROGRESS", "DELINQUENT")
OPEN_NOTICE_STATUSES = ("DETERMINATION_PENDING", "MATERIAL", "FILING_IN_PROGRESS")


# ------------------------------------------------------------ date derivations
def annual_report_due_date(period_end, filing_window_days):
    raw = period_end + timedelta(days=filing_window_days)
    return roll_forward_to_business_day(raw)


def material_event_deadline(occurrence_date):
    return add_business_days(occurrence_date, MATERIAL_EVENT_FILING_BUSINESS_DAYS)


def is_per_se_material(event_type):
    return event_type in PER_SE_EVENT_TYPES


def minus_five_years(day):
    try:
        return day.replace(year=day.year - 5)
    except ValueError:  # 29 February -> 28 February
        return day.replace(year=day.year - 5, day=28)


# ------------------------------------------------- content preparation score
def readiness_factor(status):
    return READINESS_FACTOR.get(status, 0.0)


def completeness_score(cycle):
    """Per-item 4dp contributions, summed as rounded, then scaled to 2dp."""
    total = Decimal("0")
    for item in by_seq([i for i in DB.content_items.values()
                        if i["cycle_id"] == cycle["id"]]):
        if item["status"] == "VOID":
            continue
        requirement = DB.content_requirements.get(item["content_requirement_id"])
        requires_opinion = bool(requirement and requirement["requires_audit_opinion"])
        if requires_opinion:
            opinion = OPINION_MULTIPLIER.get(item["audit_opinion_type"], Decimal("0.0"))
        else:
            opinion = Decimal("1.0")
        weight = Decimal(item["weight_bp_snapshot"]) / Decimal(10000)
        readiness = Decimal(str(readiness_factor(item["status"])))
        total += round_half_up(weight * readiness * opinion, 4)
    return num2(total * Decimal(100))


# ------------------------------------------------- direct placement materiality
def materiality_ratio_bp(principal_cents, outstanding_par_cents):
    if not outstanding_par_cents:
        return 0
    return money(Decimal(principal_cents) * Decimal(10000)
                 / Decimal(outstanding_par_cents))


# ------------------------------------------------------- failure event severity
def failure_severity(kind, days_late):
    if kind in ("ANNUAL_REPORT_MISSED", "MATERIAL_EVENT_MISSED"):
        return "MAJOR"
    return "MAJOR" if days_late >= MAJOR_DAYS_LATE else "MINOR"


# ---------------------------------------------------------- invoice calculation
def confirmed_filing_count(engagement_id):
    return len([f for f in DB.filings.values()
                if f["submitting_engagement_id"] == engagement_id
                and f["status"] == "CONFIRMED"])


def invoice_total(filing_count, retainer_cents, posture):
    fees = (min(filing_count, 4) * 45000
            + min(5, max(filing_count - 4, 0)) * 32500
            + max(filing_count - 9, 0) * 25000)
    subtotal = retainer_cents + fees
    if posture in ("IMPAIRED", "DELINQUENT"):
        surcharge = min(money(Decimal(subtotal) * Decimal("0.15")), 150000)
    else:
        surcharge = 0
    capped = min(subtotal + surcharge, 1200000)
    return max(capped, 300000)


# ------------------------------------------------------------ risk score pass
def risk_score_and_tier(late_count, missed_count, delinquent_count, persisted_tier):
    base = Decimal(12 * late_count + 20 * missed_count + 15 * delinquent_count)
    raw = round_half_up(base * TIER_MULTIPLIER.get(persisted_tier, Decimal("1.00")), 2)
    score = min(Decimal("100.00"), raw)
    if score >= Decimal("75.00"):
        tier = "TIER_3"
    elif score >= Decimal("50.00"):
        tier = "TIER_2"
    elif score >= Decimal("25.00"):
        tier = "TIER_1"
    else:
        tier = "TIER_0"
    return float(score), tier


def compliance_posture(score, delinquent_count):
    if delinquent_count >= 1:
        return "DELINQUENT"
    if Decimal(str(score)) >= Decimal("50.00"):
        return "IMPAIRED"
    if Decimal(str(score)) >= Decimal("25.00"):
        return "WATCH"
    return "COMPLIANT"


# ------------------------------------------------------- monitoring lapse days
def monitoring_lapse_days(engagement):
    base = engagement["last_calendar_ack_date"] or engagement["effective_date"]
    return day_diff(clock_date(), parse_date_str(base))
