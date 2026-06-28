"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

All money is integer cents. round_half_up applied at each PINNED step using
decimal.Decimal — never float for money.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# --- constants -------------------------------------------------------------
RUSH_PCT = {"NONE": Decimal("0.00"), "EXPRESS": Decimal("0.20"), "SAME_DAY": Decimal("0.50")}
SLA_HOURS = {"NONE": 120, "EXPRESS": 48, "SAME_DAY": 8}

BRANDING_RISK = {"NONE": 0, "REBUILT": 25, "FLOOD": 40, "SALVAGE": 55, "LEMON": 70}
BRANDING_RANK = {"NONE": 0, "REBUILT": 1, "FLOOD": 2, "SALVAGE": 3, "LEMON": 4}

FAIL_CEILING = Decimal("50")
CONDITIONAL_CEILING = Decimal("80")
ROLLBACK_TOLERANCE_MILES = 100


def _round_half_up_cents(value):
    """Round a Decimal to a whole integer number of cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# fee math (fee_estimated / fee_final) — shared subtotal+surcharge, PINNED order
# ---------------------------------------------------------------------------
def fee_components(fee_schedule, include_vin_history, dispatch_miles, rush_tier,
                   rush_discount_pct):
    """Compute (subtotal, rush_surcharge_after_discount) with pinned rounding.

    step 1: base + vin_add + round(dispatch)   -> subtotal
    step 2: round(subtotal * rush_pct)         -> rush_surcharge
    step 3: round(rush_surcharge * (1 - disc)) -> rush_surcharge_after_discount
    """
    base = int(fee_schedule["base_fee_cents"])
    vin_add = int(fee_schedule["vin_history_fee_cents"]) if include_vin_history else 0
    per_mile = int(fee_schedule["per_mile_dispatch_cents"])
    miles = Decimal(str(dispatch_miles if dispatch_miles is not None else 0))
    dispatch = _round_half_up_cents(Decimal(per_mile) * miles)
    subtotal = base + vin_add + dispatch

    rush_pct = RUSH_PCT[rush_tier]
    rush_surcharge = _round_half_up_cents(Decimal(subtotal) * rush_pct)

    disc = Decimal(str(rush_discount_pct if rush_discount_pct is not None else 0))
    rush_after_discount = _round_half_up_cents(Decimal(rush_surcharge) * (Decimal(1) - disc))

    return subtotal, rush_after_discount


def fee_estimated(fee_schedule, include_vin_history, dispatch_miles, rush_tier,
                  rush_discount_pct):
    subtotal, rush_after_discount = fee_components(
        fee_schedule, include_vin_history, dispatch_miles, rush_tier, rush_discount_pct
    )
    return subtotal + rush_after_discount


def fee_final(fee_schedule, include_vin_history, dispatch_miles, rush_tier,
              rush_discount_pct, late):
    """Final fee at delivery: on-time == estimated; late credits the full surcharge."""
    subtotal, rush_after_discount = fee_components(
        fee_schedule, include_vin_history, dispatch_miles, rush_tier, rush_discount_pct
    )
    if late:
        return subtotal
    return subtotal + rush_after_discount


def rush_surcharge_billed(fee_schedule, include_vin_history, dispatch_miles, rush_tier,
                          rush_discount_pct, late):
    """Rush surcharge actually billed on the order (0 if late-credited).

    Used as the LATE_DELIVERY dispute reason cap.
    """
    if late:
        return 0
    _, rush_after_discount = fee_components(
        fee_schedule, include_vin_history, dispatch_miles, rush_tier, rush_discount_pct
    )
    return rush_after_discount


# ---------------------------------------------------------------------------
# turnaround SLA
# ---------------------------------------------------------------------------
def sla_deadline(ordered_at_dt, rush_tier):
    return ordered_at_dt + timedelta(hours=SLA_HOURS[rush_tier])


def is_late(current_clock, deadline_dt):
    # strictly greater than (> not >=); exactly at deadline is on time.
    return current_clock > deadline_dt


# ---------------------------------------------------------------------------
# condition_score & outcome
# ---------------------------------------------------------------------------
def condition_score_and_outcome(points_total, points_failed, road_test_done,
                                critical_count):
    """Return (condition_score_float, outcome). Caller guards points_total >= 1."""
    pass_ratio = Decimal(points_total - points_failed) / Decimal(points_total)
    raw = pass_ratio * Decimal(100)
    road_test_bonus = Decimal(5) if road_test_done else Decimal(0)
    critical_penalty = Decimal(min(40, critical_count * 15))
    score = raw + road_test_bonus - critical_penalty
    # clamp 0..100
    if score < Decimal(0):
        score = Decimal(0)
    elif score > Decimal(100):
        score = Decimal(100)
    # round half up to 2 decimals; ceilings compared on the rounded value
    score = score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if critical_count >= 1 or score < FAIL_CEILING:
        outcome = "FAIL"
    elif score < CONDITIONAL_CEILING:
        outcome = "CONDITIONAL"
    else:
        outcome = "PASS"

    # represent as float for JSON; keep 2-decimal value
    return float(score), outcome


# ---------------------------------------------------------------------------
# VIN report derivations
# ---------------------------------------------------------------------------
def worst_branding(branding_records):
    """argmax by severity rank over BRANDING branding_code; NONE if none."""
    worst = "NONE"
    worst_rank = 0
    for rec in branding_records:
        code = rec.get("branding_code", "NONE")
        rank = BRANDING_RANK.get(code, 0)
        if rank > worst_rank:
            worst_rank = rank
            worst = code
    return worst


def odometer_rollback(odometer_records):
    """Chronological replay: flag if a later reading is > tolerance below running max."""
    ordered = sorted(
        odometer_records,
        key=lambda r: (r.get("event_date_dt"), r.get("_seq", 0)),
    )
    running_max = None
    rollback = False
    for rec in ordered:
        value = int(rec.get("odometer_value", 0))
        if running_max is not None and value < running_max - ROLLBACK_TOLERANCE_MILES:
            rollback = True
        if running_max is None or value > running_max:
            running_max = value
    return rollback


def vin_risk_score(worst_brand, title_count, rollback, open_recall_count):
    branding_pts = BRANDING_RISK.get(worst_brand, 0)
    owner_pts = min(title_count, 5) * 6
    rollback_pts = 30 if rollback else 0
    recall_pts = min(open_recall_count, 3) * 5
    return min(100, branding_pts + owner_pts + rollback_pts + recall_pts)


# ---------------------------------------------------------------------------
# dispute refund (waterfall, pinned order)
# ---------------------------------------------------------------------------
def dispute_refund(reason, claimed_cents, fee_total_cents, already_refunded,
                   late_delivery, rush_surcharge_billed_cents):
    """approved = max(0, min(claimed, reason_cap, refundable_ceiling))."""
    if reason == "MISSED_DEFECT":
        reason_cap = int(
            (Decimal(fee_total_cents) * Decimal("0.50")).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
    elif reason == "LATE_DELIVERY":
        reason_cap = 0 if late_delivery else rush_surcharge_billed_cents
    elif reason == "WRONG_VEHICLE":
        reason_cap = fee_total_cents
    else:
        reason_cap = 0

    refundable_ceiling = max(0, fee_total_cents - already_refunded)
    approved = min(int(claimed_cents), reason_cap, refundable_ceiling)
    return max(0, approved)
