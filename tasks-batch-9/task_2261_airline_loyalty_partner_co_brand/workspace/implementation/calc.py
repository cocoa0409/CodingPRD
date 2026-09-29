"""Every calculation rule and constant (SCAFFOLD 1.3 / PRD 3).

All arithmetic is integer; every division closes with an explicit round-half-up
at the exact position the specification names.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 80

# --------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------


def rhu(numerator, denominator=1):
    """round_half_up: exactly-half values move away from zero."""
    if denominator == 0:
        raise ZeroDivisionError("round_half_up denominator is zero")
    quotient = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(quotient.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floordiv(numerator, denominator):
    return int(numerator) // int(denominator)


def clamp(value, low, high):
    return max(low, min(high, value))


# --------------------------------------------------------------------------
# Enumerations / orderings
# --------------------------------------------------------------------------

TIERS = ("BASE", "SILVER", "GOLD", "PLATINUM")
TIER_RANK = {name: index for index, name in enumerate(TIERS)}

# --------------------------------------------------------------------------
# mile_purchase_order_pricing
# --------------------------------------------------------------------------

VOLUME_OVERDRAW_TOLERANCE_BPS = 11000
CENTICENTS_PER_CENT = 100


def volume_ceiling(committed_volume_miles):
    return rhu(committed_volume_miles * VOLUME_OVERDRAW_TOLERANCE_BPS, 10000)


def tier_for(tier_schedule, drawn_miles):
    """LAST entry whose threshold_miles <= drawn_miles (inclusive lower bound)."""
    chosen = tier_schedule[0]
    for entry in tier_schedule:
        if entry["threshold_miles"] <= drawn_miles:
            chosen = entry
        else:
            break
    return chosen


def provisional_pricing(tier_schedule, drawn_miles_before, order_miles):
    """PROVISIONAL_AT_ORDER -- one tier price applied to the whole order."""
    tier = tier_for(tier_schedule, drawn_miles_before)
    price = tier["price_per_mile_centicents"]
    gross_amount_cents = rhu(order_miles * price, CENTICENTS_PER_CENT)
    return price, gross_amount_cents


def final_pricing(tier_schedule, drawn_miles_before, order_miles):
    """FINAL_AT_INVOICE -- cut [start, start+miles) at every threshold, round
    each slice to whole cents individually, then sum."""
    total_cents = 0
    position = drawn_miles_before
    remaining = order_miles
    while remaining > 0:
        index = 0
        for i, entry in enumerate(tier_schedule):
            if entry["threshold_miles"] <= position:
                index = i
            else:
                break
        price = tier_schedule[index]["price_per_mile_centicents"]
        if index + 1 < len(tier_schedule):
            boundary = tier_schedule[index + 1]["threshold_miles"]
            end = min(position + remaining, boundary)
        else:
            end = position + remaining
        slice_miles = end - position
        if slice_miles <= 0:  # defensive; thresholds strictly increase
            slice_miles = remaining
            end = position + remaining
        total_cents += rhu(slice_miles * price, CENTICENTS_PER_CENT)
        remaining -= slice_miles
        position = end
    return total_cents


# --------------------------------------------------------------------------
# Issuer utilisation
# --------------------------------------------------------------------------

ISSUER_UTILIZATION_ALERT_BPS = 9000


def issuer_alert_threshold(annual_cap_miles):
    return rhu(annual_cap_miles * ISSUER_UTILIZATION_ALERT_BPS, 10000)


# --------------------------------------------------------------------------
# earning_credit_with_multipliers
# --------------------------------------------------------------------------

TIER_BONUS_BPS = {"BASE": 0, "SILVER": 2500, "GOLD": 5000, "PLATINUM": 10000}
CARD_SPEND_CENTS_PER_BASE_MILE = 100
CARD_SPEND_QUALIFYING_MILE_CAP = 15000
PER_MEMBER_PROMO_CAP_MILES = 25000
MIN_PROMO_MULTIPLIER_BPS = 10000
MAX_PROMO_MULTIPLIER_BPS = 50000

EARN_TYPES = ("FLIGHT_EARN", "CARD_SPEND_EARN", "PARTNER_EARN")
TXN_TYPES = ("FLIGHT_EARN", "CARD_SPEND_EARN", "PARTNER_EARN",
             "REDEEM", "REVERSAL", "EXPIRY", "ADJUSTMENT")
CHANNEL_FOR_TXN = {
    "FLIGHT_EARN": "FLIGHT",
    "CARD_SPEND_EARN": "CARD_SPEND",
    "PARTNER_EARN": "PARTNER",
}


def earn_credit(txn_type, base_miles, qualifying_spend_cents, segments,
                elite_tier, campaign):
    """Returns a dict of the computed ledger-row fields."""
    # STEP 1 -- base resolution
    if txn_type == "CARD_SPEND_EARN":
        base = floordiv(qualifying_spend_cents, CARD_SPEND_CENTS_PER_BASE_MILE)
    else:
        base = base_miles

    # STEP 2 -- elite tier bonus
    tier_bps = TIER_BONUS_BPS[elite_tier]
    tier_bonus_miles = rhu(base * tier_bps, 10000)

    # STEP 3 -- promotional multiplier
    if campaign is None:
        promo_multiplier_bps = MIN_PROMO_MULTIPLIER_BPS
        stacking_mode_applied = None
    else:
        promo_multiplier_bps = campaign["multiplier_bps"]
        stacking_mode_applied = campaign["stacking_mode"]

    # STEP 4 -- gross total by stacking mode
    m = promo_multiplier_bps
    t = tier_bps
    if stacking_mode_applied is None:
        total_gross = base + tier_bonus_miles
    elif stacking_mode_applied == "EXCLUSIVE":
        total_gross = rhu(base * m, 10000)
        tier_bonus_miles = 0
    elif stacking_mode_applied == "ADDITIVE":
        total_gross = rhu(base * (10000 + t + (m - 10000)), 10000)
    else:  # MULTIPLICATIVE -- inner subtotal rounded BEFORE the outer multiply
        inner = rhu(base * (10000 + t), 10000)
        total_gross = rhu(inner * m, 10000)

    # STEP 5 -- promotional bonus, capped
    raw_bonus = max(0, total_gross - base - tier_bonus_miles)
    if campaign is None:
        bonus_miles = 0
    else:
        candidates = [raw_bonus, PER_MEMBER_PROMO_CAP_MILES]
        if campaign.get("bonus_cap_miles") is not None:
            room = max(0, campaign["bonus_cap_miles"] - campaign["accrued_bonus_miles"])
            candidates.append(room)
        bonus_miles = min(candidates)

    # STEP 6 -- totals
    total_miles = base + tier_bonus_miles + bonus_miles

    # STEP 7 -- qualifying credit
    if txn_type == "FLIGHT_EARN":
        qualifying_miles_credited = base
    elif txn_type == "CARD_SPEND_EARN":
        qualifying_miles_credited = min(base, CARD_SPEND_QUALIFYING_MILE_CAP)
    else:
        qualifying_miles_credited = 0

    return {
        "base": base,
        "tier_bonus_miles": tier_bonus_miles,
        "promo_multiplier_bps": promo_multiplier_bps,
        "stacking_mode_applied": stacking_mode_applied,
        "bonus_miles": bonus_miles,
        "total_miles": total_miles,
        "qualifying_miles_credited": qualifying_miles_credited,
    }


# --------------------------------------------------------------------------
# award_dynamic_pricing
# --------------------------------------------------------------------------

AWARD_CHART_MILES = {
    "ECONOMY": {"SAVER": 12500, "FLEX": 25000},
    "PREMIUM": {"SAVER": 25000, "FLEX": 45000},
    "BUSINESS": {"SAVER": 50000, "FLEX": 85000},
    "FIRST": {"SAVER": 90000, "FLEX": 140000},
}
CABINS = ("ECONOMY", "PREMIUM", "BUSINESS", "FIRST")
FARE_CLASSES = ("SAVER", "FLEX")

PARTNER_UPLIFT_BPS = {"OWN_METAL": 10000, "FIXED_CHART": 10000, "DISTANCE_BAND": 11500}

SURCHARGE_CENTS = {"SURCHARGE_LOW": 560, "SURCHARGE_MID": 1120, "SURCHARGE_HIGH": 2240}

ELITE_DISCOUNT_BPS = {
    "BASE": {"SURCHARGE_LOW": 0, "SURCHARGE_MID": 0, "SURCHARGE_HIGH": 0},
    "SILVER": {"SURCHARGE_LOW": 0, "SURCHARGE_MID": 250, "SURCHARGE_HIGH": 500},
    "GOLD": {"SURCHARGE_LOW": 250, "SURCHARGE_MID": 500, "SURCHARGE_HIGH": 1000},
    "PLATINUM": {"SURCHARGE_LOW": 500, "SURCHARGE_MID": 1000, "SURCHARGE_HIGH": 1500},
}

MAX_SEATS_PER_BOOKING = 9
HOLD_HOURS = 72

CAPACITY_CONSTRAINED_BPS = 7500
CAPACITY_CLOSED_BPS = 10000


def load_factor_bps(authorized_seats, seats_held, seats_confirmed):
    if authorized_seats == 0:
        return 0
    return rhu(10000 * (seats_held + seats_confirmed), authorized_seats)


def demand_multiplier_bps(load_bps):
    if load_bps < 5000:
        return 9000
    if load_bps < 7500:
        return 10000
    if load_bps < 9000:
        return 12500
    return 16000


def capacity_control_state(load_bps):
    if load_bps < CAPACITY_CONSTRAINED_BPS:
        return "OPEN"
    if load_bps < CAPACITY_CLOSED_BPS:
        return "CONSTRAINED"
    return "CLOSED"


def surcharge_band(gross_per_seat):
    if gross_per_seat < 25000:
        return "SURCHARGE_LOW"
    if gross_per_seat < 75000:
        return "SURCHARGE_MID"
    return "SURCHARGE_HIGH"


def saver_allotment(authorized_seats, saver_seat_share_bps):
    return rhu(authorized_seats * saver_seat_share_bps, 10000)


def price_award_booking(window, fare_class, partner, elite_tier, seats):
    """The seven pinned steps of award_dynamic_pricing."""
    # STEP 1 -- pre-booking load factor (requested seats NOT included)
    pre_load_bps = load_factor_bps(
        window["authorized_seats"], window["seats_held"], window["seats_confirmed"])

    # STEP 2 -- demand multiplier
    demand_bps = demand_multiplier_bps(pre_load_bps)

    # STEP 3 -- chart
    chart_miles_per_seat = AWARD_CHART_MILES[window["cabin"]][fare_class]

    # STEP 4 -- partner uplift
    if partner is None:
        uplift_bps = PARTNER_UPLIFT_BPS["OWN_METAL"]
    elif partner["award_pricing_mode"] == "DYNAMIC_PASSTHROUGH":
        uplift_bps = demand_bps
    else:
        uplift_bps = PARTNER_UPLIFT_BPS[partner["award_pricing_mode"]]

    # STEP 5 -- gross per seat
    gross_per_seat = rhu(chart_miles_per_seat * demand_bps * uplift_bps, 100000000)

    # STEP 6 -- surcharge band from the PRE-discount gross
    band = surcharge_band(gross_per_seat)
    cash_surcharge_cents = SURCHARGE_CENTS[band] * seats

    # STEP 7 -- elite discount, rounded PER SEAT then multiplied by seats
    discount_bps = ELITE_DISCOUNT_BPS[elite_tier][band]
    per_seat_miles = rhu(gross_per_seat * (10000 - discount_bps), 10000)
    quoted_miles = per_seat_miles * seats

    if partner is None:
        partner_settlement_cents = 0
    else:
        partner_settlement_cents = rhu(
            quoted_miles * partner["settlement_rate_centicents_per_mile"], 100)

    return {
        "chart_miles_per_seat": chart_miles_per_seat,
        "demand_multiplier_bps_applied": demand_bps,
        "partner_uplift_bps_applied": uplift_bps,
        "surcharge_band": band,
        "elite_discount_bps_applied": discount_bps,
        "quoted_miles": quoted_miles,
        "cash_surcharge_cents": cash_surcharge_cents,
        "partner_settlement_cents": partner_settlement_cents,
    }


# --------------------------------------------------------------------------
# elite_qualification_and_rollover
# --------------------------------------------------------------------------

TIER_THRESHOLDS = {
    "SILVER": {"miles": 25000, "segments": 30, "spend_cents": 300000},
    "GOLD": {"miles": 75000, "segments": 75, "spend_cents": 900000},
    "PLATINUM": {"miles": 150000, "segments": 120, "spend_cents": 1500000},
}
ROLLOVER_CAP_MILES = 40000


def qualify(qualifying_miles_ytd, rollover_carried_in, qualifying_segments_ytd,
            qualifying_spend_cents_ytd):
    effective_miles = qualifying_miles_ytd + rollover_carried_in
    awarded = "BASE"
    for tier in ("PLATINUM", "GOLD", "SILVER"):
        thresholds = TIER_THRESHOLDS[tier]
        miles_arm = effective_miles >= thresholds["miles"]
        segment_arm = (qualifying_segments_ytd >= thresholds["segments"]
                       and qualifying_spend_cents_ytd >= thresholds["spend_cents"])
        if miles_arm or segment_arm:
            awarded = tier
            break
    consumed = 0 if awarded == "BASE" else TIER_THRESHOLDS[awarded]["miles"]
    rollover_carried_out = min(ROLLOVER_CAP_MILES, max(0, effective_miles - consumed))
    return awarded, rollover_carried_out


# --------------------------------------------------------------------------
# partner_settlement_run
# --------------------------------------------------------------------------

RECIPROCITY_FACTOR_BPS = {"FULL": 10000, "INBOUND_ONLY": 10000, "OUTBOUND_ONLY": 5000}
RECIPROCITY_MODES = ("FULL", "INBOUND_ONLY", "OUTBOUND_ONLY", "SUSPENDED")
AWARD_PRICING_MODES = ("FIXED_CHART", "DISTANCE_BAND", "DYNAMIC_PASSTHROUGH")


# --------------------------------------------------------------------------
# fraud_risk_and_clawback
# --------------------------------------------------------------------------

RISK_WATCH_THRESHOLD = 40
RISK_FREEZE_THRESHOLD = 70
CLAWBACK_LOOKBACK_DAYS = 90
CASE_TYPES = ("ACCOUNT_TAKEOVER", "MILE_BROKERING", "VELOCITY_ANOMALY")


def detection_score(login_geo_velocity, redemption_velocity_24h,
                    brokering_pattern_hits, dormancy_days):
    a = min(100, login_geo_velocity * 10)
    b = min(100, redemption_velocity_24h * 20)
    c = min(100, brokering_pattern_hits * 25)
    d = min(100, floordiv(dormancy_days, 4))
    blended = rhu(3500 * a + 3000 * b + 2500 * c + 1000 * d, 10000)
    return min(100, blended)


def clawback_for(case_type, mile_balance, basis):
    if case_type == "MILE_BROKERING":
        return min(mile_balance, basis)
    if case_type == "VELOCITY_ANOMALY":
        return min(mile_balance, floordiv(basis, 2))
    return 0


# --------------------------------------------------------------------------
# breakage_and_deferred_revenue
# --------------------------------------------------------------------------

BREAKAGE_TRAILING_MONTHS = 24
BREAKAGE_RATE_FLOOR_HISTORICAL_BPS = 0
BREAKAGE_RATE_FLOOR_FORWARD_BPS = 200
BREAKAGE_RATE_CEILING_BPS = 3500
BREAKAGE_METHODS = ("HISTORICAL_ATTRITION", "FORWARD_EXPECTATION")


def breakage_rate(method, expired, redeemed, issued):
    if method == "HISTORICAL_ATTRITION":
        denominator = expired + redeemed
        raw = 0 if denominator == 0 else rhu(10000 * expired, denominator)
        return clamp(raw, BREAKAGE_RATE_FLOOR_HISTORICAL_BPS, BREAKAGE_RATE_CEILING_BPS)
    if issued == 0:
        raw = BREAKAGE_RATE_CEILING_BPS
    else:
        raw = rhu(10000 * (issued - redeemed), issued)
    return clamp(raw, BREAKAGE_RATE_FLOOR_FORWARD_BPS, BREAKAGE_RATE_CEILING_BPS)


# --------------------------------------------------------------------------
# member_reaction_index
# --------------------------------------------------------------------------

SEVERITY_POINTS = {"EARN_STRUCTURE": 40, "AWARD_PRICING": 50,
                   "ELITE_THRESHOLD": 30, "EXPIRY_POLICY": 20}
CHANGE_TYPES = ("EARN_STRUCTURE", "AWARD_PRICING", "ELITE_THRESHOLD", "EXPIRY_POLICY")
GRANDFATHER_FULL_YEAR_DAYS = 365
EXPOSURE_POINTS_PER_MEMBER_BPS = 100
EXPOSURE_UPLIFT_CAP_BPS = 5000
REACTION_RISK_BLOCK_THRESHOLD = 70


def lead_time_factor_bps(notice_days):
    if notice_days >= 180:
        return 10000
    if notice_days >= 90:
        return 12500
    if notice_days >= 30:
        return 15000
    return 20000


def grandfather_relief(grandfather_until, effective_at):
    if grandfather_until is None:
        return 0
    from datetime import timedelta
    if grandfather_until >= effective_at + timedelta(days=GRANDFATHER_FULL_YEAR_DAYS):
        return 30
    if grandfather_until >= effective_at:
        return 15
    return 0


def reaction_index(change_type, notice_days, grandfather_until, effective_at,
                   exposed_member_count):
    severity = SEVERITY_POINTS[change_type]
    lead_bps = lead_time_factor_bps(notice_days)
    relief = grandfather_relief(grandfather_until, effective_at)
    exposure_bps = 10000 + min(
        EXPOSURE_UPLIFT_CAP_BPS, exposed_member_count * EXPOSURE_POINTS_PER_MEMBER_BPS)
    core = max(0, rhu(severity * lead_bps, 10000) - relief)
    return min(100, rhu(core * exposure_bps, 10000))
