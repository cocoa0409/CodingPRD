"""Calculation rules (scaffold 1.3 / PRD 3): exact formulas, precision, boundaries."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import db
from util import CLOCK, parse_datetime, sub_months

# ---------------------------------------------------------------------------
# violation_time_weight: 3 / 2 / 1 / 0 by age in calendar months.
# [as_of-6mo, as_of] -> 3 ; [as_of-12mo, as_of-6mo) -> 2 ;
# [as_of-24mo, as_of-12mo) -> 1 ; older -> 0. Interval starts inclusive.
# ---------------------------------------------------------------------------

TIER1_MONTHS = 6
TIER2_MONTHS = 12
TIER3_MONTHS = 24


def time_weight(occurred: datetime, as_of: datetime) -> int:
    if occurred > as_of:
        # Future occurrences are rejected at intake; treat defensively as newest.
        return 3
    if occurred >= sub_months(as_of, TIER1_MONTHS):
        return 3
    if occurred >= sub_months(as_of, TIER2_MONTHS):
        return 2
    if occurred >= sub_months(as_of, TIER3_MONTHS):
        return 1
    return 0


# ---------------------------------------------------------------------------
# crash_severity_points / dot_reportable
# ---------------------------------------------------------------------------

def crash_points(fatalities: int, injuries: int, tow_away: bool) -> int:
    return (4 if fatalities >= 1 else 0) + (2 if injuries >= 1 else 0) + (1 if tow_away else 0)


def dot_reportable(fatalities: int, injuries: int, tow_away: bool) -> bool:
    return fatalities >= 1 or injuries >= 1 or bool(tow_away)


# ---------------------------------------------------------------------------
# category_measure + percentile_from_measure (2dp round-half-up; floor percentile)
# ---------------------------------------------------------------------------

def category_points(carrier_id: str, category: dict, variant: str) -> int:
    """Sum of weighted points for the carrier in the category.

    official: violations in ACTIVE or CHALLENGED; provisional: ACTIVE only.
    REMOVED excluded in both. CRASH_INDICATOR additionally adds
    crash_points x time_weight over DOT-reportable accidents (both variants).
    Violation time weights must already be refreshed against the cycle as_of.
    """
    statuses = ("ACTIVE", "CHALLENGED") if variant == "official" else ("ACTIVE",)
    points = 0
    for v in db["inspection_violations"].values():
        if v["category_id"] != category["id"] or v["status"] not in statuses:
            continue
        insp = db["roadside_inspections"].get(v["inspection_id"])
        if not insp or insp["carrier_id"] != carrier_id:
            continue
        if v["time_weight_multiplier"] > 0:
            points += v["weighted_points"]
    if category["category_code"] == "CRASH_INDICATOR":
        as_of = CLOCK.now()
        for a in db["accident_records"].values():
            if a["carrier_id"] != carrier_id or not a["dot_reportable"]:
                continue
            w = time_weight(parse_datetime(a["occurred_at"]), as_of)
            if w > 0:
                points += a["crash_points"] * w
    return points


def measure_from_points(points: int, fleet_size: int) -> Decimal:
    """Points per power unit, 2 decimals round_half_up."""
    return (Decimal(points) / Decimal(fleet_size)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def percentile_from_measure(measure: Decimal, benchmark_measure) -> int:
    """min(100, floor(measure / benchmark_measure x 100))."""
    b = Decimal(str(benchmark_measure))
    raw = (measure / b) * Decimal(100)
    p = int(raw.to_integral_value(rounding=ROUND_FLOOR))
    return min(100, p)


# ---------------------------------------------------------------------------
# carrier_posture ladder (first matching rule wins)
# ---------------------------------------------------------------------------

POSTURE_OOS = "OUT_OF_SERVICE_PROPOSED"
POSTURE_PRIORITY = "INTERVENTION_PRIORITY"
POSTURE_WATCH = "INTERVENTION_WATCH"
POSTURE_NORMAL = "NORMAL"


def latest_alerted_category_codes(carrier: dict) -> set:
    """Alerted-official category codes from the carrier's LATEST measurement cycle."""
    last = carrier.get("last_cycle_date")
    if not last:
        return set()
    codes = set()
    for s in db["measurement_snapshots"].values():
        if s["carrier_id"] == carrier["id"] and s["cycle_date"] == last and s["alerted_official"]:
            cat = db["violation_categories"].get(s["category_id"])
            codes.add(cat["category_code"] if cat else s["category_id"])
    return codes


def compute_posture(carrier: dict) -> str:
    if carrier["safety_rating"] == "UNSATISFACTORY" or carrier["new_entrant_status"] == "FAILED":
        return POSTURE_OOS
    alerted = latest_alerted_category_codes(carrier)
    if len(alerted) >= 2 or "CONTROLLED_SUBSTANCES_ALCOHOL" in alerted:
        return POSTURE_PRIORITY
    if len(alerted) == 1:
        return POSTURE_WATCH
    return POSTURE_NORMAL


# ---------------------------------------------------------------------------
# driver_risk_score (floor 0) and risk_tier (LOW <10, MEDIUM 10-19, HIGH >=20)
# ---------------------------------------------------------------------------

COACHING_CREDIT = 2
CREDIT_WINDOW_MONTHS = 24
TIER_MEDIUM_MIN = 10
TIER_HIGH_MIN = 20


def driver_risk(driver: dict, as_of: datetime):
    score = 0
    for v in db["inspection_violations"].values():
        if (v["driver_id"] == driver["id"] and v["status"] in ("ACTIVE", "CHALLENGED")
                and v["time_weight_multiplier"] > 0):
            score += v["weighted_points"]
    for a in db["accident_records"].values():
        if (a["driver_id"] == driver["id"] and a["preventability_status"] == "PREVENTABLE"
                and a["dot_reportable"]):
            w = time_weight(parse_datetime(a["occurred_at"]), as_of)
            if w > 0:
                score += a["crash_points"] * w
    credit_from = sub_months(as_of, CREDIT_WINDOW_MONTHS)
    credits = 0
    for c in db["coaching_assignments"].values():
        if c["driver_id"] == driver["id"] and c["status"] == "COMPLETED" and c.get("completed_at"):
            ca = parse_datetime(c["completed_at"])
            if credit_from <= ca <= as_of:
                credits += 1
    score = max(0, score - COACHING_CREDIT * credits)
    if score < TIER_MEDIUM_MIN:
        tier = "LOW"
    elif score < TIER_HIGH_MIN:
        tier = "MEDIUM"
    else:
        tier = "HIGH"
    return score, tier


# ---------------------------------------------------------------------------
# insurance_premium (single final round_half_up to whole cents)
# ---------------------------------------------------------------------------

RATING_FACTORS = {
    "NONE": Decimal("1.05"),
    "SATISFACTORY": Decimal("1.00"),
    "CONDITIONAL": Decimal("1.25"),
    "UNSATISFACTORY": Decimal("1.60"),
}

# Rating ladder: SATISFACTORY ranks above CONDITIONAL above UNSATISFACTORY.
RATING_BADNESS = {"SATISFACTORY": 1, "CONDITIONAL": 2, "UNSATISFACTORY": 3}

SCORE_LOADING_PER_ALERT = 3
SCORE_LOADING_CAP = 15
CRASH_LOADING_PER_ACCIDENT = 5
CRASH_LOADING_CAP = 25
CRASH_WINDOW_MONTHS = 36
DRIVER_LOADING_PER_HIGH = 2
DRIVER_LOADING_CAP = 10


def compute_premium(fields: dict, carrier: dict) -> dict:
    """fields carries scenario / assume_* / base_rate_cents_per_unit."""
    as_of = CLOCK.now()
    # 2. rating factor
    if fields.get("scenario") == "PROJECTED" and fields.get("assume_rating"):
        factor = RATING_FACTORS[fields["assume_rating"]]
    else:
        factor = RATING_FACTORS[carrier["safety_rating"]]
    # 3. score loading from latest-cycle official alerts
    alerted = latest_alerted_category_codes(carrier)
    if fields.get("scenario") == "PROJECTED":
        cleared = set(fields.get("assume_cleared_category_codes") or [])
        alerted = alerted - cleared
    score_pct = min(SCORE_LOADING_CAP, SCORE_LOADING_PER_ALERT * len(alerted))
    # 4. crash loading: PREVENTABLE + reportable + occurred within [as_of-36mo, as_of]
    crash_from = sub_months(as_of, CRASH_WINDOW_MONTHS)
    n_prev = 0
    for a in db["accident_records"].values():
        if (a["carrier_id"] == carrier["id"] and a["preventability_status"] == "PREVENTABLE"
                and a["dot_reportable"]):
            occ = parse_datetime(a["occurred_at"])
            if crash_from <= occ <= as_of:
                n_prev += 1
    if fields.get("scenario") == "PROJECTED":
        n_prev = max(0, n_prev - (fields.get("assume_removed_preventable_accidents") or 0))
    crash_pct = min(CRASH_LOADING_CAP, CRASH_LOADING_PER_ACCIDENT * n_prev)
    # 5. driver loading: ACTIVE + HIGH risk tier
    n_high = sum(
        1 for d in db["drivers"].values()
        if d["carrier_id"] == carrier["id"]
        and d["employment_status"] == "ACTIVE"
        and d["risk_tier"] == "HIGH"
    )
    driver_pct = min(DRIVER_LOADING_CAP, DRIVER_LOADING_PER_HIGH * n_high)
    # 1. + 6. base x factor x (1 + total loading), single final round_half_up
    base_amount = carrier["fleet_size"] * fields["base_rate_cents_per_unit"]
    total_pct = score_pct + crash_pct + driver_pct
    amount = (Decimal(base_amount) * factor
              * (Decimal(1) + Decimal(total_pct) / Decimal(100)))
    cents = int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {
        "rating_factor_used": float(factor),
        "score_loading_pct": score_pct,
        "crash_loading_pct": crash_pct,
        "driver_loading_pct": driver_pct,
        "computed_premium_cents": cents,
    }


# ---------------------------------------------------------------------------
# audit_outcome_rating
# ---------------------------------------------------------------------------

def audit_outcome(audit_type: str, acute_count: int, critical_count: int) -> str:
    if audit_type == "NEW_ENTRANT":
        return "FAIL" if (acute_count >= 1 or critical_count >= 3) else "PASS"
    # COMPLIANCE_REVIEW
    if acute_count >= 2 or critical_count >= 4:
        return "UNSATISFACTORY"
    if acute_count == 0 and critical_count <= 1:
        return "SATISFACTORY"
    return "CONDITIONAL"


# ---------------------------------------------------------------------------
# random_testing_quota (ceil; exact multiples do not round up)
# ---------------------------------------------------------------------------

def required_drug_tests(avg_driver_count: int) -> int:
    # ceil(avg x 0.25)
    return (avg_driver_count * 25 + 99) // 100


def required_alcohol_tests(avg_driver_count: int) -> int:
    # ceil(avg x 0.10)
    return (avg_driver_count * 10 + 99) // 100


def completed_counts(period: dict):
    """Live counters: MRO_VERIFIED (verdict not CANCELLED) RANDOM tests of the
    carrier's drivers collected within [year-01-01, (year+1)-01-01)."""
    year = period["program_year"]
    lo = datetime(year, 1, 1, tzinfo=timezone.utc)
    hi = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    drug = 0
    alcohol = 0
    for t in db["drug_alcohol_tests"].values():
        if t["test_type"] != "RANDOM" or t["status"] != "MRO_VERIFIED":
            continue
        if t["mro_verdict"] not in ("VERIFIED_NEGATIVE", "VERIFIED_POSITIVE", "VERIFIED_REFUSAL"):
            continue
        drv = db["drivers"].get(t["driver_id"])
        if not drv or drv["carrier_id"] != period["carrier_id"]:
            continue
        collected = parse_datetime(t["collected_at"])
        if not (lo <= collected < hi):
            continue
        if t["substance"] == "DRUG":
            drug += 1
        elif t["substance"] == "ALCOHOL":
            alcohol += 1
    return drug, alcohol


# ---------------------------------------------------------------------------
# retention_until: filed_at + retention_months calendar months (day clamped)
# ---------------------------------------------------------------------------

RETENTION_MONTHS = {
    "INSPECTION_REPORT": 12,
    "DQ_FILE": 36,
    "ACCIDENT_REGISTER_ENTRY": 36,
    "TRAINING_CERTIFICATE": 36,
    "DRUG_TEST_RECORD": 60,
    "ALCOHOL_TEST_RECORD": 60,
}


# ---------------------------------------------------------------------------
# suspension_hold_evaluation
# ---------------------------------------------------------------------------

def suspension_hold_count(driver: dict) -> int:
    holds = 0
    for c in db["coaching_assignments"].values():
        if c["driver_id"] == driver["id"] and c["status"] == "ESCALATED":
            holds += 1
    tests = [t for t in db["drug_alcohol_tests"].values() if t["driver_id"] == driver["id"]]
    for t in tests:
        if (t["status"] == "MRO_VERIFIED"
                and t["mro_verdict"] in ("VERIFIED_POSITIVE", "VERIFIED_REFUSAL")):
            verified_at = parse_datetime(t["verified_at"])
            cleared = any(
                r["test_type"] == "RETURN_TO_DUTY"
                and r["status"] == "MRO_VERIFIED"
                and r["mro_verdict"] == "VERIFIED_NEGATIVE"
                and parse_datetime(r["collected_at"]) > verified_at
                for r in tests
            )
            if not cleared:
                holds += 1
    return holds
