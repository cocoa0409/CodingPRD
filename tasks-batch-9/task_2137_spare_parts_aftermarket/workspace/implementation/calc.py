"""Calculation rules C1..C8 with pinned rounding discipline (PRD sections 2.7, 3.3-3.9)."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

# ------------------------------------------------------------- constants ---
ANNUAL_REPLACEMENT_RATE = Decimal("0.20")
BLEND_WEIGHT_WO = Decimal("0.60")
DEFAULT_LOOKBACK_DAYS = 365

DEMAND_SCORE_CAP = Decimal(40)
DEMAND_UNITS_MULTIPLIER = Decimal(2)
DOWNTIME_SCORE_MAX = Decimal(30)
LEAD_TIME_LONG_DAYS = 60
LEAD_TIME_MED_DAYS = 30
COVERAGE_HIGH_UNITS = 4
COVERAGE_MED_UNITS = 2
VITAL_THRESHOLD = Decimal(70)
ESSENTIAL_THRESHOLD = Decimal(40)
SERVICE_FACTOR = {
    "VITAL": Decimal("1.65"),
    "ESSENTIAL": Decimal("1.28"),
    "DESIRABLE": Decimal("0.84"),
}

SCARCITY_UPLIFT_PCT = {
    "ACTIVE": Decimal("0.00"),
    "PHASE_OUT": Decimal("0.04"),
    "LTB_OPEN": Decimal("0.08"),
    "LTB_CLOSED": Decimal("0.15"),
    "OBSOLETE": Decimal("0.15"),
    "SUPERSEDED": Decimal("0.00"),
}

DOWNTIME_RATE_CENTS_PER_DAY = {"MACHINE_DOWN": 250000, "DEGRADED": 60000, "PLANNED": 0}
AIR_RATE_CENTS_PER_KG = 2000
AIR_HANDLING_FEE_CENTS = 10000
AIR_MIN_CHARGE_CENTS = 45000
HAZMAT_SURCHARGE_CENTS = 30000
AIR_APPROVAL_THRESHOLD_CENTS = 100000

DECAY_FACTOR = Decimal("0.85")
MAX_COVERAGE_YEARS = 15

TIER_WEIGHT = {"PLATINUM": 50, "GOLD": 30, "SILVER": 10}
INSTALLED_WEIGHT_CAP = 30
CREDIT_PENALTY = 20
FAIR_SHARE_PCT = Decimal("0.50")

BASE_FEE_PCT = {
    "WRONG_PART": Decimal("0.00"),
    "UNUSED_SURPLUS": Decimal("0.15"),
    "DEFECTIVE": Decimal("0.00"),
    "CORE_RETURN": Decimal("0.00"),
}
AGE_TIER_1_DAYS = 30
AGE_TIER_2_DAYS = 90
RETURN_WINDOW_DAYS = 180
RESTOCK_FEE_CAP_PCT = Decimal("0.50")
REBATE_TIER_MID_CENTS = 200000
REBATE_TIER_HIGH_CENTS = 500000

DOWNTIME_RANK = {"MACHINE_DOWN": 0, "DEGRADED": 1, "PLANNED": 2}

LTB_COOLDOWN_DAYS = 30


# --------------------------------------------------------------- rounding --
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


_QUANT = {0: Decimal("1"), 2: Decimal("0.01"), 4: Decimal("0.0001")}


def round_half_up(value, places=0):
    q = _QUANT.get(places) or Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def money(value):
    """Whole cents, round half up."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def floor_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


# ------------------------------------------------------- C3 price uplift ---
def price_uplift(unit_cost_cents, lifecycle_state, rule, qty):
    """Returns the six pricing figures for a quantity."""
    scarcity = SCARCITY_UPLIFT_PCT.get(lifecycle_state, Decimal("0.00"))
    base = dec(rule["base_uplift_pct"])
    cap = dec(rule["max_uplift_pct"])
    total = base + scarcity
    effective = round_half_up(min(cap, total), 4)

    cost = Decimal(unit_cost_cents)
    list_unit = money(cost * (Decimal(1) + effective))
    list_total = list_unit * qty
    quoted_total = money(cost * qty * (Decimal(1) + effective))
    delta = list_total - quoted_total
    extended_cost = cost * qty
    if quoted_total == 0:
        margin = Decimal("0.0000")
    else:
        margin = round_half_up(
            (Decimal(quoted_total) - extended_cost) / Decimal(quoted_total), 4)
    return {
        "effective_uplift_pct": effective,
        "list_unit_price_cents": list_unit,
        "list_line_total_cents": list_total,
        "quoted_line_total_cents": quoted_total,
        "variant_delta_cents": delta,
        "margin_pct": margin,
    }


# ------------------------------------------- C4 emergency air freight ------
def air_freight_cost(weight_kg, qty, hazmat):
    billable_kg = ceil_int(dec(weight_kg) * Decimal(qty))
    raw = billable_kg * AIR_RATE_CENTS_PER_KG + AIR_HANDLING_FEE_CENTS
    if hazmat:
        raw += HAZMAT_SURCHARGE_CENTS
    return max(AIR_MIN_CHARGE_CENTS, raw)


def air_freight_decision(available_units, qty, lead_time_days, downtime_priority,
                         weight_kg, hazmat, lifecycle_state, dealer_tier):
    expected_wait_days = 0 if available_units >= qty else lead_time_days
    downtime_cost = DOWNTIME_RATE_CENTS_PER_DAY[downtime_priority] * expected_wait_days
    air_cost = air_freight_cost(weight_kg, qty, hazmat)
    net_benefit = downtime_cost - air_cost

    if available_units >= qty:
        mode = "STOCK"
    elif lifecycle_state == "OBSOLETE":
        mode = "BACKORDER"
    elif dealer_tier == "PLATINUM" and downtime_priority == "MACHINE_DOWN":
        mode = "AIR_FREIGHT"
    elif net_benefit > AIR_APPROVAL_THRESHOLD_CENTS:
        mode = "AIR_FREIGHT"
    else:
        mode = "BACKORDER"

    return {
        "fulfillment_mode": mode,
        "decision_net_benefit_cents": net_benefit,
        "air_freight_cost_cents": air_cost,
        "freight_cost_cents": air_cost if mode == "AIR_FREIGHT" else 0,
    }


# ------------------------------------------------- C5 lifetime buy sizing --
def ltb_quantity(method, annual_demand_units, coverage_years, cover):
    if method == "FLAT_RATE":
        requirement = annual_demand_units * coverage_years
    else:
        total = 0
        for year in range(1, coverage_years + 1):
            total += int(round_half_up(
                Decimal(annual_demand_units) * (DECAY_FACTOR ** (year - 1)), 0))
        requirement = total
    return max(0, requirement - cover)


# -------------------------------------------- C7 return fee and credit -----
def return_credit(charged_amount_cents, qty_returned, qty_consumed, age_days,
                  return_reason, lifecycle_state):
    gross = money(Decimal(charged_amount_cents) * Decimal(qty_returned) / Decimal(qty_consumed))

    base_fee = BASE_FEE_PCT[return_reason]
    if age_days <= AGE_TIER_1_DAYS:
        age_surcharge = Decimal("0.00")
    elif age_days <= AGE_TIER_2_DAYS:
        age_surcharge = Decimal("0.10")
    else:
        age_surcharge = Decimal("0.25")
    obsolete_surcharge = (Decimal("0.20")
                          if lifecycle_state in ("LTB_CLOSED", "OBSOLETE")
                          else Decimal("0.00"))
    fee_pct = round_half_up(
        min(RESTOCK_FEE_CAP_PCT, base_fee + age_surcharge + obsolete_surcharge), 4)
    restocking_fee = money(Decimal(gross) * fee_pct)

    net_before_rebate = max(0, gross - restocking_fee)

    if net_before_rebate >= REBATE_TIER_HIGH_CENTS:
        rebate_pct = Decimal("0.05")
    elif net_before_rebate >= REBATE_TIER_MID_CENTS:
        rebate_pct = Decimal("0.02")
    else:
        rebate_pct = Decimal("0.00")
    rebate_pct = round_half_up(rebate_pct, 4)
    loyalty_rebate = money(Decimal(net_before_rebate) * rebate_pct)
    final_credit = net_before_rebate + loyalty_rebate

    return {
        "gross_credit_cents": gross,
        "fee_pct": fee_pct,
        "restocking_fee_cents": restocking_fee,
        "net_before_rebate_cents": net_before_rebate,
        "rebate_pct": rebate_pct,
        "loyalty_rebate_cents": loyalty_rebate,
        "final_credit_cents": final_credit,
    }


# ------------------------------------------------ C6 allocation ranking ----
def priority_score(tier, dealer_installed_units, credit_hold):
    tier_weight = TIER_WEIGHT[tier]
    installed_weight = min(INSTALLED_WEIGHT_CAP, (dealer_installed_units // 2) * 3)
    penalty = CREDIT_PENALTY if credit_hold else 0
    return max(0, tier_weight + installed_weight - penalty)
