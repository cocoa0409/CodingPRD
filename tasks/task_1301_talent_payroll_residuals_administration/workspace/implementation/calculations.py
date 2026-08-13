"""Calculation rules from scaffold 1.3 / PRD 3.5-3.16.

All monetary values are integer cents. Rounding is round-half-up applied per
component before summing (never on the final aggregate).
"""

from decimal import Decimal

import db
from helpers import new_id, now_timestamp, round_half_up

# Constants
MEAL_WINDOW_MINUTES = 360        # first meal must begin within 6h of call
MIN_REST_MINUTES = 30            # meal break shorter than 30 min is a REST violation
HOURS_PER_DAY_RATE = 8
MAX_GARNISH_PCT = Decimal("0.25")
WINDOW_STEP_DISCOUNT = Decimal("0.10")
WINDOW_DISCOUNT_FLOOR = Decimal("0.50")


def find_tier(agreement: dict, tier_code: str):
    for tier in agreement.get("rate_tiers", []):
        if tier.get("tier_code") == tier_code:
            return tier
    return None


def compute_worked_minutes(call_time, first_meal_out, first_meal_in, wrap_time) -> int:
    """(wrap - call) - (first_meal_in - first_meal_out), whole minutes."""
    total = (wrap_time - call_time).total_seconds()
    meal = (first_meal_in - first_meal_out).total_seconds()
    return int((total - meal) // 60)


def compute_overtime_minutes(worked_minutes: int, tier: dict) -> int:
    return max(0, worked_minutes - int(tier["ot_daily_threshold_minutes"]))


def provisional_penalty_cents(scheduled_hours, agreement: dict) -> int:
    """Provisional estimate from scheduled_hours only.

    MEAL units = 1 if scheduled_hours > 6 else 0; REST = 0; TURNAROUND = 0.
    """
    meal_units = 1 if float(scheduled_hours) > 6 else 0
    return meal_units * int(agreement["meal_penalty_cents"])


def daily_gross_cents(worked_minutes: int, tier: dict) -> int:
    """Final day gross from actual worked minutes.

    hourly_cents = day_rate_cents / 8 (exact rational); each component
    (regular, overtime) is rounded half-up BEFORE summing.
    """
    threshold = int(tier["ot_daily_threshold_minutes"])
    regular = min(worked_minutes, threshold)
    ot = max(0, worked_minutes - threshold)
    day_rate = Decimal(str(tier["day_rate_cents"]))
    hourly = day_rate / Decimal(HOURS_PER_DAY_RATE)
    ot_multiplier = Decimal(str(tier["ot_multiplier"]))
    regular_component = round_half_up(Decimal(regular) / Decimal(60) * hourly)
    ot_component = round_half_up(Decimal(ot) / Decimal(60) * hourly * ot_multiplier)
    return regular_component + ot_component


def final_penalty_assessment(timecard: dict, engagement: dict, agreement: dict):
    """Final penalty evaluation from actual timestamps.

    Returns (final_penalty_cents, violations) where violations is a list of
    (penalty_type, units, amount_cents) with units > 0 only.
    """
    tier = find_tier(agreement, engagement["tier_code"])
    violations = []

    call = timecard["_call_time"]
    meal_out = timecard["_first_meal_out"]
    meal_in = timecard["_first_meal_in"]

    # MEAL: delay from call to first_meal_out > 360 minutes => 1 unit
    meal_delay_minutes = (meal_out - call).total_seconds() / 60.0
    meal_units = 1 if meal_delay_minutes > MEAL_WINDOW_MINUTES else 0
    meal_amount = meal_units * int(agreement["meal_penalty_cents"])
    if meal_units > 0:
        violations.append(("MEAL", meal_units, meal_amount))

    # REST: break duration < 30 minutes => 1 unit
    rest_minutes = (meal_in - meal_out).total_seconds() / 60.0
    rest_units = 1 if rest_minutes < MIN_REST_MINUTES else 0
    rest_amount = rest_units * int(agreement["rest_penalty_cents"])
    if rest_units > 0:
        violations.append(("REST", rest_units, rest_amount))

    # TURNAROUND: gap vs previous timecard of the same engagement
    prev = _previous_timecard(timecard)
    turnaround_units = 0
    if prev is not None:
        gap_seconds = (call - prev["_wrap_time"]).total_seconds()
        gap_hours = Decimal(str(gap_seconds)) / Decimal(3600)
        shortfall = Decimal(str(agreement["turnaround_min_hours"])) - gap_hours
        if shortfall > 0:
            # ceil of the fractional-hour shortfall; exact equality is NOT a violation
            turnaround_units = int(shortfall.to_integral_value(rounding="ROUND_CEILING"))
    turnaround_price = round_half_up(Decimal(str(tier["day_rate_cents"])) / Decimal(8))
    turnaround_amount = turnaround_units * turnaround_price
    if turnaround_units > 0:
        violations.append(("TURNAROUND", turnaround_units, turnaround_amount))

    total = meal_amount + rest_amount + turnaround_amount
    return total, violations


def _previous_timecard(timecard: dict):
    """Latest timecard of the same engagement with work_date strictly before."""
    candidates = [
        tc
        for tc in db.timecards.values()
        if tc["engagement_id"] == timecard["engagement_id"]
        and tc["work_date"] < timecard["work_date"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda tc: tc["work_date"])
    return candidates[-1]


def create_penalty_assessments(timecard: dict, violations):
    """Create one CONFIRMED PenaltyAssessment per violation (units > 0)."""
    now = now_timestamp()
    for penalty_type, units, amount in violations:
        row = {
            "id": new_id(),
            "created_at": now,
            "timecard_id": timecard["id"],
            "penalty_type": penalty_type,
            "units": units,
            "amount_cents": amount,
            "status": "CONFIRMED",
        }
        db.penalty_assessments[row["id"]] = row


def recompute_engagement_accrued_penalty(engagement: dict):
    """Sum of CONFIRMED PenaltyAssessment.amount_cents over this engagement's timecards."""
    timecard_ids = {
        tc["id"] for tc in db.timecards.values() if tc["engagement_id"] == engagement["id"]
    }
    total = sum(
        pa["amount_cents"]
        for pa in db.penalty_assessments.values()
        if pa["timecard_id"] in timecard_ids and pa["status"] == "CONFIRMED"
    )
    engagement["accrued_penalty_cents"] = total


def recompute_engagement_accrued_adjustment(engagement: dict):
    """Sum of PayLine.gross_cents where source_type == GRIEVANCE_ADJUSTMENT."""
    total = sum(
        pl["gross_cents"]
        for pl in db.pay_lines.values()
        if pl["engagement_id"] == engagement["id"]
        and pl["source_type"] == "GRIEVANCE_ADJUSTMENT"
    )
    engagement["accrued_adjustment_cents"] = total


def recompute_engagement_ytd_paid(engagement: dict):
    """Sum of PayLine.net_cents for this engagement where status == PAID."""
    total = sum(
        pl["net_cents"]
        for pl in db.pay_lines.values()
        if pl["engagement_id"] == engagement["id"] and pl["status"] == "PAID"
    )
    engagement["ytd_paid_cents"] = total


def recompute_performer_ytd(performer: dict):
    """Sum gross/garnished over PAID pay lines whose engagement belongs to performer."""
    engagement_ids = {
        e["id"] for e in db.engagements.values() if e["performer_id"] == performer["id"]
    }
    gross = 0
    garnished = 0
    for pl in db.pay_lines.values():
        if pl["status"] == "PAID" and pl["engagement_id"] in engagement_ids:
            gross += pl["gross_cents"]
            garnished += pl["garnished_cents"]
    performer["ytd_gross_cents"] = gross
    performer["ytd_garnished_cents"] = garnished


def jurisdiction_tax_cents(gross_cents: int, engagement: dict, production: dict,
                           performer: dict, source_type: str,
                           timecard_jurisdiction_code=None) -> int:
    """Withholding per jurisdiction_tax_calculation; 0 for LOAN_OUT."""
    if engagement["payee_type"] == "LOAN_OUT":
        return 0
    if source_type == "TIMECARD":
        jurisdiction = timecard_jurisdiction_code
    else:
        jurisdiction = performer["tax_residency_state"]
    tax_pct = 0
    for jrow in production.get("jurisdictions", []):
        if jrow.get("jurisdiction_code") == jurisdiction:
            tax_pct = jrow.get("tax_pct", 0)
            break
    return round_half_up(Decimal(gross_cents) * Decimal(str(tax_pct)))


def phw_contribution_cents(gross_cents: int, agreement: dict) -> int:
    """Employer-side PHW: per-component round-half-up BEFORE summing."""
    pension = round_half_up(Decimal(gross_cents) * Decimal(str(agreement["phw_pension_pct"])))
    health = round_half_up(Decimal(gross_cents) * Decimal(str(agreement["phw_health_pct"])))
    welfare = round_half_up(Decimal(gross_cents) * Decimal(str(agreement["phw_welfare_pct"])))
    return pension + health + welfare


def window_discount(window_sequence: int) -> Decimal:
    """max(floor, 1 - 0.10 * (sequence - 1))."""
    value = Decimal(1) - WINDOW_STEP_DISCOUNT * (window_sequence - 1)
    return max(WINDOW_DISCOUNT_FLOOR, value)


def residual_provisional_amount(tier: dict, base_pct) -> int:
    """round_half_up(tier.day_rate_cents * base_pct)."""
    return round_half_up(Decimal(str(tier["day_rate_cents"])) * Decimal(str(base_pct)))


def residual_final_amount(reported_gross_receipts_cents: int, base_pct,
                          window_sequence: int) -> int:
    """round_half_up(receipts * base_pct * discount)."""
    discount = window_discount(window_sequence)
    value = (
        Decimal(reported_gross_receipts_cents)
        * Decimal(str(base_pct))
        * discount
    )
    return round_half_up(value)


def assign_window_sequence(engagement_id: str, reuse_market: str,
                           window_start: str, created_at: str) -> int:
    """1-based ordinal among the engagement's windows for the same market,
    ordered by window_start ASC, tie-break created_at ASC."""
    siblings = [
        r
        for r in db.residual_obligations.values()
        if r["engagement_id"] == engagement_id and r["reuse_market"] == reuse_market
    ]
    siblings.append(
        {
            "window_start": window_start,
            "created_at": created_at,
        }
    )
    siblings.sort(key=lambda r: (r["window_start"], r["created_at"]))
    for idx, row in enumerate(siblings, start=1):
        if row["window_start"] == window_start and row["created_at"] == created_at:
            return idx
    return len(siblings)


def remittance_aggregation(pay_batch_id: str, union_agreement_id: str):
    """Per-line round-half-up then sum, for lines whose engagement uses the agreement."""
    agreement = db.union_agreements.get(union_agreement_id)
    pension = health = welfare = 0
    for line in db.pay_lines.values():
        if line["pay_batch_id"] != pay_batch_id:
            continue
        engagement = db.engagements.get(line["engagement_id"])
        if engagement is None or engagement["union_agreement_id"] != union_agreement_id:
            continue
        gross = Decimal(line["gross_cents"])
        pension += round_half_up(gross * Decimal(str(agreement["phw_pension_pct"])))
        health += round_half_up(gross * Decimal(str(agreement["phw_health_pct"])))
        welfare += round_half_up(gross * Decimal(str(agreement["phw_welfare_pct"])))
    return pension, health, welfare
