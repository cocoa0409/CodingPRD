"""Calculation rules (SCAFFOLD §1.3, PRD §3.5/§3.8/§3.9/§3.11/§3.12).

All monetary amounts are integer cents; all penalty/reliability figures are
integer points; ratings carry 2 decimal places. Rounding is round-half-up,
applied at EACH named rounding step (PRD §2.8).
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# Rank multipliers (PRD §3.5 / §3.9; SCAFFOLD constants).
RANK_MULTIPLIER = {
    "ROOKIE": Decimal("1.0"),
    "CERTIFIED": Decimal("1.25"),
    "SENIOR": Decimal("1.5"),
    "MASTER": Decimal("2.0"),
}
POSTSEASON_UPLIFT = Decimal("1.20")
RELIABILITY_DEDUCTION_THRESHOLD = 10
RELIABILITY_DEDUCTION_PCT = Decimal("0.10")

# Decline penalty constants.
LATE_HOURS = 24
SHORT_HOURS = 72
LATE_DECLINE_POINTS = 8
SHORT_DECLINE_POINTS = 4
STANDARD_DECLINE_POINTS = 1
ESCALATION_STEP_POINTS = 2
MAX_ESCALATION_STEPS = 3
POSTSEASON_PENALTY_MULT = Decimal("2.0")

# No-show penalty constants.
NOSHOW_BASE_POINTS = 15
NS_ESCALATION_POINTS = 5
NS_MAX_STEPS = 3
NS_POSTSEASON_MULT = Decimal("2.0")

EARTH_RADIUS_MILES = 3958.7613  # mean Earth radius in miles


def round_half_up(value, places=0):
    """Round a Decimal/number half-up to `places` decimal places.
    Returns an int when places==0, else a Decimal quantized to `places`."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    if places == 0:
        return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> Decimal('0.01')
    return d.quantize(q, rounding=ROUND_HALF_UP)


def great_circle_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles between two lat/lon points (haversine),
    carried to two decimal places (PRD §3.4)."""
    rlat1 = math.radians(float(lat1))
    rlon1 = math.radians(float(lon1))
    rlat2 = math.radians(float(lat2))
    rlon2 = math.radians(float(lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    miles = EARTH_RADIUS_MILES * c
    return float(round_half_up(Decimal(str(miles)), 2))


def mileage_cents(distance_miles, mileage_rate_cents_per_mile):
    """round_half_up(distance_miles) * league.mileage_rate_cents_per_mile."""
    whole_miles = round_half_up(Decimal(str(distance_miles)), 0)
    return whole_miles * int(mileage_rate_cents_per_mile)


def provisional_game_pay(rank, base_game_fee_cents, slot_fee_multiplier,
                         is_postseason, distance_miles,
                         mileage_rate_cents_per_mile):
    """Provisional Game Pay (PRD §3.5). Rank read at offer time (frozen)."""
    rank_mult = RANK_MULTIPLIER[rank]
    base = Decimal(str(base_game_fee_cents)) * Decimal(str(slot_fee_multiplier))
    game_pay = round_half_up(base * rank_mult, 0)
    if is_postseason:
        game_pay = round_half_up(Decimal(game_pay) * POSTSEASON_UPLIFT, 0)
    mil = mileage_cents(distance_miles, mileage_rate_cents_per_mile)
    return int(game_pay) + int(mil)


def finalized_settlement_pay(rank, penalty_points, base_game_fee_cents,
                             slot_fee_multiplier, is_postseason,
                             distance_miles, mileage_rate_cents_per_mile):
    """Finalized Settlement Pay (PRD §3.9). Rank + penalty_points read at
    settlement time; adds the reliability deduction absent from provisional."""
    rank_mult = RANK_MULTIPLIER[rank]
    base = Decimal(str(base_game_fee_cents)) * Decimal(str(slot_fee_multiplier))
    game_pay = round_half_up(base * rank_mult, 0)
    if is_postseason:
        game_pay = round_half_up(Decimal(game_pay) * POSTSEASON_UPLIFT, 0)
    if int(penalty_points) >= RELIABILITY_DEDUCTION_THRESHOLD:
        game_pay = round_half_up(
            Decimal(game_pay) * (Decimal("1") - RELIABILITY_DEDUCTION_PCT), 0)
    mil = mileage_cents(distance_miles, mileage_rate_cents_per_mile)
    return int(game_pay) + int(mil)


def decline_penalty(hours_to_game, prior_penalised_declines, is_postseason):
    """Decline Penalty (PRD §3.8). Tiered base by lead time + escalation by
    prior penalised declines, optionally doubled for postseason."""
    if hours_to_game < LATE_HOURS:
        base_pen = LATE_DECLINE_POINTS
    elif hours_to_game < SHORT_HOURS:
        base_pen = SHORT_DECLINE_POINTS
    else:
        base_pen = STANDARD_DECLINE_POINTS
    escalation = min(int(prior_penalised_declines), MAX_ESCALATION_STEPS) * ESCALATION_STEP_POINTS
    mult = POSTSEASON_PENALTY_MULT if is_postseason else Decimal("1.0")
    return int(round_half_up(Decimal(base_pen + escalation) * mult, 0))


def no_show_penalty(prior_noshows, is_postseason):
    """No-Show Penalty (PRD §3.8). Base 15 + escalation by prior no-shows,
    optionally doubled for postseason."""
    escalation = min(int(prior_noshows), NS_MAX_STEPS) * NS_ESCALATION_POINTS
    mult = NS_POSTSEASON_MULT if is_postseason else Decimal("1.0")
    return int(round_half_up(Decimal(NOSHOW_BASE_POINTS + escalation) * mult, 0))


def reliability_score(penalty_points):
    """max(0, 100 - penalty_points) (PRD §3.7)."""
    return max(0, 100 - int(penalty_points))


def mean_rating(scores):
    """round-per-item (2dp), then average, then round (2dp). None when empty.
    (PRD §3.11.)"""
    if not scores:
        return None
    per_item = [round_half_up(Decimal(str(s)), 2) for s in scores]
    total = sum(per_item, Decimal("0"))
    avg = total / Decimal(len(per_item))
    return float(round_half_up(avg, 2))
