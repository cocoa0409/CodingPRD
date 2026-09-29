"""Premium build-up: technical premium, gross-up, bind adjustment, tail and return
premium (PRD 3.3, 3.4, 3.6)."""

import clock
from money import ZERO, dec, floor_div, q2

MILLION = dec("1000000")

EXPOSURE_BANDS = (
    (dec("5000000"), dec("1.00")),
    (dec("5000000"), dec("0.65")),
    (dec("10000000"), dec("0.45")),
    (None, dec("0.30")),
)

BAND_RATE = {
    "LOW": dec("9000"),
    "MODERATE": dec("14000"),
    "ELEVATED": dec("22000"),
    "SEVERE": dec("34000"),
}

SIDE_C_LOAD = {"LISTED": dec("0.20"), "PRIVATE": dec("0.08"), "NONE": dec("0.00")}

RETENTION_BLOCK = dec("250000")
RETENTION_CREDIT_STEP = dec("0.05")
RETENTION_CREDIT_CAP = dec("0.35")
PREMIUM_FLOOR = dec("25000")
PREMIUM_CEILING = dec("2500000")
COMMISSION_RATE = dec("0.125")
PREMIUM_TAX_RATE = dec("0.035")

TAIL_FACTOR = {1: dec("0.75"), 2: dec("1.10"), 3: dec("1.45"), 6: dec("2.25")}
SEVERITY_LOAD = dec("0.20")
DAYS_IN_YEAR = dec("365")


def exposure_units(limit_usd):
    """Increased-limit exposure measure, in millions, held unrounded."""
    remaining = dec(limit_usd)
    consumed = ZERO
    total = ZERO
    for width, factor in EXPOSURE_BANDS:
        if remaining <= 0:
            break
        if width is None:
            slice_amount = remaining
        else:
            slice_amount = width if remaining > width else remaining
        total += (slice_amount / MILLION) * factor
        remaining -= slice_amount
        consumed += slice_amount
    return total


def side_c_load(sublimit_usd, exchange_listing):
    if dec(sublimit_usd) == 0:
        return ZERO
    return SIDE_C_LOAD[exchange_listing]


def retention_credit(retention_usd):
    blocks = floor_div(retention_usd, RETENTION_BLOCK)
    credit = RETENTION_CREDIT_STEP * dec(blocks)
    return credit if credit < RETENTION_CREDIT_CAP else RETENTION_CREDIT_CAP


def net_premium(limit_usd, retention_usd, sublimit_usd, risk_band, exchange_listing):
    base = exposure_units(limit_usd) * BAND_RATE[risk_band]
    loaded = base * (dec(1) + side_c_load(sublimit_usd, exchange_listing))
    credited = loaded * (dec(1) - retention_credit(retention_usd))
    if credited < PREMIUM_FLOOR:
        credited = PREMIUM_FLOOR
    elif credited > PREMIUM_CEILING:
        credited = PREMIUM_CEILING
    return q2(credited)


def grossup(net):
    """Commission is the residual so net + commission == gross exactly."""
    net = q2(net)
    gross = q2(dec(net) / (dec(1) - COMMISSION_RATE))
    commission = q2(gross - net)
    tax = q2(gross * PREMIUM_TAX_RATE)
    total = q2(gross + tax)
    return {
        "gross_premium_usd": gross,
        "broker_commission_usd": commission,
        "premium_tax_usd": tax,
        "total_payable_usd": total,
    }


def bound_premium(quote_gross, terms):
    """Sum the agreed impacts first, multiply once, round once."""
    impact = ZERO
    for term in terms:
        if term["status"] == "AGREED":
            impact += dec(term["premium_impact_pct"])
    return q2(dec(quote_gross) * (dec(1) + impact))


def clamped_unexpired_days(start, period_end):
    days = clock.whole_days_between(start, period_end)
    if days < 0:
        return 0
    if days > 365:
        return 365
    return days


def unexpired_credit(gross_premium, start, period_end):
    days = clamped_unexpired_days(start, period_end)
    return q2(dec(gross_premium) * (dec(days) / DAYS_IN_YEAR))


def runoff_premium(gross_premium, tail_years, has_live_claim, runoff_start, period_end):
    tail_factor = TAIL_FACTOR[tail_years]
    severity = SEVERITY_LOAD if has_live_claim else ZERO
    base = q2(dec(gross_premium) * tail_factor * (dec(1) + severity))
    credit = unexpired_credit(gross_premium, runoff_start, period_end)
    net = q2(base - credit)
    if net < 0:
        net = q2(ZERO)
    return {
        "tail_factor_applied": tail_factor,
        "severity_load_applied": severity,
        "unexpired_premium_credit_usd": credit,
        "runoff_premium_usd": net,
    }
