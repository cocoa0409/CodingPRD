"""Calculation rules (scaffold 1.3 / PRD 2.7, 3.x).

All arithmetic is decimal and every rounding is ROUND_HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

ZERO = Decimal("0")

# ------------------------------------------------------------------ constants

SEASON_FACTOR = {
    "WINTER": Decimal("1.00"),
    "SPRING": Decimal("0.95"),
    "SUMMER": Decimal("1.10"),
    "FALL": Decimal("0.98"),
}

INSTRUMENT_DELTA = {
    "SWAP": Decimal("1.00"),
    "COLLAR": Decimal("0.65"),
    "CALL_OPTION": Decimal("0.50"),
}

MARGIN_RATE_PER_GAL = {
    "SWAP": Decimal("0.06"),
    "COLLAR": Decimal("0.04"),
    "CALL_OPTION": Decimal("0.02"),
}

ADVERSE_MTM_FACTOR = Decimal("1.10")

WATCH_PCT = Decimal("70")
CONSTRAINED_PCT = Decimal("90")
BREACH_PCT = Decimal("100")

RESERVE_GALLONS = Decimal("900")
LBS_PER_GAL = Decimal("6.7")

FLEET_TANKER_BURN_FACTOR = {
    "NARROWBODY": Decimal("0.030"),
    "WIDEBODY": Decimal("0.024"),
    "REGIONAL": Decimal("0.038"),
}
PAYLOAD_RATIO_THRESHOLD = Decimal("0.85")
PAYLOAD_PENALTY_SLOPE = Decimal("2.0")

EFFECTIVENESS_MIN = Decimal("0.8000")
EFFECTIVENESS_MAX = Decimal("1.2500")

CHANGEOVER_BUFFER_DAYS = 7

FLEET_TYPES = ("NARROWBODY", "WIDEBODY", "REGIONAL")
ROUTE_GROUPS = ("DOMESTIC_SHORT", "DOMESTIC_LONG", "TRANSATLANTIC", "TRANSPACIFIC", "LATAM")
SEASONS = ("WINTER", "SPRING", "SUMMER", "FALL")
INSTRUMENT_TYPES = ("SWAP", "COLLAR", "CALL_OPTION")
CREDIT_RATINGS = ("AA", "A", "BBB", "BB")
INDEX_BASES = ("PLATTS_USGC", "PLATTS_NWE", "PLATTS_SGP")
COLLATERAL_TYPES = ("CASH", "LETTER_OF_CREDIT")
REASON_CODES = ("COVERAGE_LIMIT", "COUNTERPARTY_CONCENTRATION",
                "EARNINGS_VOLATILITY_BREACH", "TANKERING_UNECONOMIC", "INVENTORY_SHORT")


# ------------------------------------------------------------------- rounding

def rnd(value, places):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def r0(value):
    return rnd(value, 0)


def r1(value):
    return rnd(value, 1)


def r2(value):
    return rnd(value, 2)


def r4(value):
    return rnd(value, 4)


def dec(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# --------------------------------------------------- counterparty credit tiers

def credit_posture(utilization_pct):
    if utilization_pct < WATCH_PCT:
        return "NORMAL"
    if utilization_pct < CONSTRAINED_PCT:
        return "WATCH"
    if utilization_pct < BREACH_PCT:
        return "CONSTRAINED"
    return "BREACH"


def utilization_pct(utilized_credit_usd, credit_limit_usd):
    if credit_limit_usd is None or credit_limit_usd == 0:
        return r2(0)
    return r2(utilized_credit_usd / credit_limit_usd * Decimal(100))


def margin_addon_rate(concentration_pct):
    if concentration_pct < Decimal("50"):
        return Decimal("0.00")
    if concentration_pct < Decimal("75"):
        return Decimal("0.10")
    if concentration_pct < Decimal("90"):
        return Decimal("0.25")
    return Decimal("0.50")


def base_margin(notional_gallons, instrument_type, mtm_value_usd):
    adverse = -mtm_value_usd if mtm_value_usd is not None and mtm_value_usd < 0 else ZERO
    return r2(notional_gallons * MARGIN_RATE_PER_GAL[instrument_type]
              + adverse * ADVERSE_MTM_FACTOR)


def margin_requirement(notional_gallons, instrument_type, mtm_value_usd,
                       pre_addon_exposure_usd, credit_limit_usd):
    """Pinned six-step margin calculation (PRD 3.4)."""
    base = base_margin(notional_gallons, instrument_type, mtm_value_usd)
    if credit_limit_usd is None or credit_limit_usd == 0:
        concentration = r2(0)
    else:
        concentration = r2(pre_addon_exposure_usd / credit_limit_usd * Decimal(100))
    addon = margin_addon_rate(concentration)
    return r2(base * (Decimal(1) + addon))


# ------------------------------------------------------------- station posture

def consortium_entitlement(station):
    if not station.get("consortium_member"):
        return r2(0)
    return r2(station["consortium_share_pct"] / Decimal(100) * station["consortium_pool_gallons"])


def station_supply(station, min_days_cover):
    entitlement = consortium_entitlement(station)
    effective = r2(station["inventory_gallons"] + entitlement)
    days = r2(effective / station["avg_daily_liftings_gallons"])
    min_days = dec(min_days_cover) if min_days_cover is not None else Decimal("0")
    if days < min_days:
        posture = "SHORT"
    elif days < (min_days * Decimal(2)):
        posture = "WATCH"
    else:
        posture = "NORMAL"
    return effective, days, posture


# ------------------------------------------------------------- tankering rules

def uplift_cap(leg, policy_max_uplift):
    tank_headroom = leg["tank_capacity_gallons"] - leg["planned_burn_gallons"] - RESERVE_GALLONS
    weight_headroom = (leg["max_landing_weight_lbs"] - leg["landing_weight_lbs"]) / LBS_PER_GAL
    terms = [tank_headroom, weight_headroom]
    if policy_max_uplift is not None:
        terms.append(dec(policy_max_uplift))
    cap = r2(min(terms))
    if cap < 0:
        cap = r2(0)
    return cap


def burn_penalty(leg, uplift_gallons, block_minutes):
    payload_ratio = r4((leg["payload_lbs"] + uplift_gallons * LBS_PER_GAL)
                       / leg["max_takeoff_payload_lbs"])
    excess = payload_ratio - PAYLOAD_RATIO_THRESHOLD
    if excess < 0:
        excess = ZERO
    multiplier = r4(Decimal(1) + excess * PAYLOAD_PENALTY_SLOPE)
    raw = (uplift_gallons
           * FLEET_TANKER_BURN_FACTOR[leg["fleet_type"]]
           * (dec(block_minutes) / Decimal(60)))
    return r1(raw * multiplier)


def net_savings(uplift_gallons, penalty_gallons, price_origin, price_destination):
    gross = r2(uplift_gallons * (price_destination - price_origin))
    penalty_cost = r2(penalty_gallons * price_origin)
    net = r2(gross - penalty_cost)
    return gross, penalty_cost, net


# ------------------------------------------------------------ mark-to-market

def instrument_mtm(instrument, index):
    itype = instrument["instrument_type"]
    notional = instrument["notional_gallons"]
    if itype == "SWAP":
        exact = notional * (index - instrument["strike_usd_per_gal"])
    elif itype == "COLLAR":
        upper = index - instrument["cap_strike_usd_per_gal"]
        if upper < 0:
            upper = ZERO
        lower = instrument["floor_strike_usd_per_gal"] - index
        if lower < 0:
            lower = ZERO
        exact = notional * (upper - lower)
    else:  # CALL_OPTION
        upper = index - instrument["strike_usd_per_gal"]
        if upper < 0:
            upper = ZERO
        exact = notional * upper - instrument["premium_usd"]
    return r2(exact)


# ---------------------------------------------------------------- effectiveness

def effectiveness(hedge_change, item_change, cum_hedge, cum_item):
    period_ratio = r4(abs(hedge_change / item_change))
    new_cum_hedge = cum_hedge + hedge_change
    new_cum_item = cum_item + item_change
    if new_cum_item == 0:
        cumulative_ratio = r4(0)
    else:
        cumulative_ratio = r4(abs(new_cum_hedge / new_cum_item))
    result = "PASS" if EFFECTIVENESS_MIN <= cumulative_ratio <= EFFECTIVENESS_MAX else "FAIL"
    return period_ratio, cumulative_ratio, result, new_cum_hedge, new_cum_item
