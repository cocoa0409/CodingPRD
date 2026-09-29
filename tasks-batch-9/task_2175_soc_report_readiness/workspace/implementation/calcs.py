"""Constants and pure calculation routines (PRD 3.3, 3.5, 3.6, 3.7, 3.9)."""
import math
from decimal import Decimal

import store

SEVERITY_POINTS = {"LOW": 1, "MODERATE": 3, "HIGH": 8, "CRITICAL": 20}
TIER_1_MAX_BASE = 10
TIER_2_MAX_BASE = 25
TIER_1_RATE = Decimal("0.00")
TIER_2_RATE = Decimal("0.15")
TIER_3_RATE = Decimal("0.30")

FROZEN_DEBT_THRESHOLD = Decimal("26.00")
RESTRICTED_DEBT_THRESHOLD = Decimal("11.00")
FROZEN_EXCEPTION_THRESHOLD = 3
RESTRICTED_EXCEPTION_THRESHOLD = 1

FREQUENCY_BASE = {"DAILY": 25, "WEEKLY": 15, "MONTHLY": 5, "QUARTERLY": 2, "ANNUAL": 1, "ADHOC": 8}
AUTOMATION_FACTOR = Decimal("0.4")
RISK_BUMP = {"LOW": 0, "MODERATE": 2, "HIGH": 5}
SOC1_ADDENDUM = 1
ALLOWED_DEVIATION_RATE = Decimal("0.10")

PRECISION_ALLOWANCE = {"LOW": 0, "MODERATE": 1, "HIGH": 2}
PERVASIVE_THRESHOLD_PCT = Decimal("0.20")

PERIOD_DAYS = {"DAILY": 1, "WEEKLY": 7, "MONTHLY": 30, "QUARTERLY": 91, "ANNUAL": 365}
GRACE_DAYS = 5
MISSED_INEFFECTIVE_THRESHOLD = 2

MAX_BRIDGE_DAYS = 120
SUBSERVICE_BUFFER_DAYS = 1

RISK_SEVERITY = {"LOW": "LOW", "MODERATE": "MODERATE", "HIGH": "HIGH"}
DISPOSITION_SEVERITY = {"ISOLATED": "MODERATE", "PERVASIVE": "CRITICAL"}

CATEGORIES = ("SECURITY", "AVAILABILITY", "CONFIDENTIALITY", "PROCESSING_INTEGRITY", "PRIVACY")
REPORT_TYPES = ("SOC_1_TYPE_2", "SOC_2_TYPE_2")

GAP_LIVE_STATUSES = ("OPEN", "PLANNED", "REOPENED")


def sample_size_determination(control, engagement):
    """Returns (population, sample_size, allowed_deviations, zero_population)."""
    population = int(control["population_size"])
    base = FREQUENCY_BASE[control["frequency"]]
    if control["automation"] == "AUTOMATED":
        base = max(1, int(math.ceil(Decimal(base) * AUTOMATION_FACTOR)))
    raw = base + RISK_BUMP[control["risk_rating"]]
    if engagement["report_type"] == "SOC_1_TYPE_2":
        raw = raw + SOC1_ADDENDUM
    sample_size = min(raw, population)
    allowed = int(math.floor(Decimal(sample_size) * ALLOWED_DEVIATION_RATE))
    return population, sample_size, allowed, population == 0


def deviation_rate(sample):
    if sample["sample_size"] == 0:
        return Decimal("0.0000")
    return store.round_half_up(
        Decimal(sample["items_failed"]) / Decimal(sample["sample_size"]), 4
    )


def projected_failures(rate, population):
    return store.round_half_up(rate * Decimal(population), 2)


def projected_failures_upper(rate, population, risk_rating):
    return int(math.ceil(rate * Decimal(population))) + PRECISION_ALLOWANCE[risk_rating]


def pervasive_recommended(upper, population):
    return Decimal(upper) > PERVASIVE_THRESHOLD_PCT * Decimal(population)


def debt_tier_rate(base_debt):
    if base_debt <= TIER_1_MAX_BASE:
        return TIER_1_RATE
    if base_debt <= TIER_2_MAX_BASE:
        return TIER_2_RATE
    return TIER_3_RATE


def debt_decomposition(base_debt):
    """Returns (base_debt, surcharge Decimal, total Decimal)."""
    rate = debt_tier_rate(base_debt)
    surcharge = store.round_half_up(Decimal(base_debt) * rate, 2)
    total = store.round_half_up(Decimal(base_debt) + surcharge, 2)
    return base_debt, surcharge, total


def bridge_coverage_days(coverage_start, as_of_date):
    return store.floor_days(as_of_date, coverage_start) + 1


def calendar_periods(engagement, control):
    """Returns a list of (period_start, period_end) datetimes."""
    start = store.parse_iso(engagement["observation_period_start"])
    end = store.parse_iso(engagement["observation_period_end"])
    if control["frequency"] == "ADHOC":
        return [(start, end)]
    step = PERIOD_DAYS[control["frequency"]]
    span_days = int(engagement["observation_period_days"])
    count = span_days // step
    out = []
    for i in range(count):
        out.append((store.add_days(start, i * step), store.add_days(start, (i + 1) * step)))
    return out
