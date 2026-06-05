"""Money/weight/percentage calculations (PRD §3, scaffold §1.3).

All money is integer cents. Decimal + ROUND_HALF_UP everywhere rounding occurs.
"""
from decimal import Decimal, ROUND_HALF_UP

# --- PAYT constants ---
FREE_ALLOWANCE_LBS = {
    "RESIDENTIAL": Decimal("100"),
    "COMMERCIAL_SMALL": Decimal("0"),
    "COMMERCIAL_LARGE": Decimal("0"),
}
RATE_PER_LB_CENTS = {
    "RESIDENTIAL": {"t1": Decimal("5"), "t2": Decimal("8"), "t3": Decimal("12")},
    "COMMERCIAL_SMALL": {"t1": Decimal("7"), "t2": Decimal("10"), "t3": Decimal("15")},
    "COMMERCIAL_LARGE": {"t1": Decimal("6"), "t2": Decimal("9"), "t3": Decimal("13")},
}
TIER1_UPPER_LBS = Decimal("200")
TIER2_UPPER_LBS = Decimal("500")

# --- contamination constants ---
SEVERITY_RATE_PER_LB_CENTS = {
    "MINOR": Decimal("2"),
    "MAJOR": Decimal("5"),
    "REJECT": Decimal("10"),
}
SEVERITY_FLAT_CENTS = {
    "MINOR": Decimal("500"),
    "MAJOR": Decimal("1500"),
    "REJECT": Decimal("4000"),
}
SEVERITY_RANK = {"MINOR": 1, "MAJOR": 2, "REJECT": 3}

# --- special pickup fee constants ---
BASE_FEE_CENTS = {"BULK": Decimal("3500"), "HAZARDOUS": Decimal("8000")}
HAZARD_MULT = {
    "FLAMMABLE": Decimal("1.5"),
    "CORROSIVE": Decimal("1.75"),
    "TOXIC": Decimal("2.0"),
    "EWASTE": Decimal("1.25"),
}

# --- credit constants ---
CREDIT_FLAT_CENTS_PICKUP = Decimal("1500")
SPECIAL_REFUND_PCT = Decimal("0.5")

# --- diversion penalty ---
PENALTY_CENTS_PER_PCT_POINT = Decimal("100")


def _round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def net_weight_lbs(gross_weight_lbs, tare_weight_lbs):
    """max(0, gross - tare), rounded to 3 decimals round-half-up."""
    gross = Decimal(str(gross_weight_lbs))
    tare = Decimal(str(tare_weight_lbs))
    net = gross - tare
    if net < 0:
        net = Decimal("0")
    net = net.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    # Return as float for JSON; the value is an exact 3-dp decimal.
    return float(net)


def payt_weight_charge_cents(trash_net_weights, rate_class):
    """Marginal-tiered PAYT charge. trash_net_weights: list of net lbs (floats).

    Sum-then-round: sum per-tier cents (as Decimal), round once at the end.
    """
    total_net = sum((Decimal(str(w)) for w in trash_net_weights), Decimal("0"))
    allowance = FREE_ALLOWANCE_LBS[rate_class]
    billable = total_net - allowance
    if billable < 0:
        billable = Decimal("0")

    rates = RATE_PER_LB_CENTS[rate_class]
    t1_lbs = min(billable, TIER1_UPPER_LBS)
    t2_lbs = Decimal("0")
    t3_lbs = Decimal("0")
    if billable > TIER1_UPPER_LBS:
        t2_lbs = min(billable, TIER2_UPPER_LBS) - TIER1_UPPER_LBS
    if billable > TIER2_UPPER_LBS:
        t3_lbs = billable - TIER2_UPPER_LBS

    cents = (
        t1_lbs * rates["t1"]
        + t2_lbs * rates["t2"]
        + t3_lbs * rates["t3"]
    )
    return _round_half_up_int(cents)


def contamination_surcharge_cents(pickup_lines):
    """Round-per-line-item-then-sum.

    pickup_lines: list of (net_weight_lbs, highest_severity) tuples.
    """
    total = 0
    for net_lbs, severity in pickup_lines:
        net = Decimal(str(net_lbs))
        rate = SEVERITY_RATE_PER_LB_CENTS[severity]
        flat = SEVERITY_FLAT_CENTS[severity]
        line = net * rate + flat
        total += _round_half_up_int(line)
    return total


def special_pickup_fee_cents(kind, hazard_class):
    if kind == "BULK":
        return _round_half_up_int(BASE_FEE_CENTS["BULK"])
    base = BASE_FEE_CENTS["HAZARDOUS"]
    mult = HAZARD_MULT[hazard_class]
    return _round_half_up_int(base * mult)


def missed_credit_amount_cents(source_type, quoted_fee_cents=0):
    if source_type == "PICKUP":
        return _round_half_up_int(CREDIT_FLAT_CENTS_PICKUP)
    return _round_half_up_int(Decimal(str(quoted_fee_cents)) * SPECIAL_REFUND_PCT)


def diversion_rate_pct(diverted_weight_lbs, total_weight_lbs):
    total = Decimal(str(total_weight_lbs))
    if total == 0:
        return 0.0
    diverted = Decimal(str(diverted_weight_lbs))
    rate = (Decimal("100") * diverted / total).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(rate)


def diversion_penalty_cents(diversion_floor_pct, diversion_rate):
    floor = Decimal(str(diversion_floor_pct))
    rate = Decimal(str(diversion_rate))
    shortfall = floor - rate
    if shortfall <= 0:
        return 0
    return _round_half_up_int(shortfall * PENALTY_CENTS_PER_PCT_POINT)


def invoice_total_cents(base_fee, weight_charge, contamination, diversion_penalty, credit):
    charges = base_fee + weight_charge + contamination + diversion_penalty
    total = charges - credit
    if total < 0:
        total = 0
    return total
