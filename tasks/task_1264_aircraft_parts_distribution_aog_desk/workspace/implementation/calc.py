"""Calculation rules (SCAFFOLD 1.3). Money is integer cents; Decimal only."""

from decimal import Decimal

from util import rhu, ceil_div

TRACE_RANK = {
    "TRACE_MISSING": 0,
    "TEARDOWN_REPORT": 1,
    "FAA_8130": 2,
    "EASA_FORM1": 3,
    "DUAL_RELEASE": 4,
}

TIER_CAPS = {"STANDARD": 24, "PRIORITY": 48, "PLATINUM": 72}
TIER_FEE_PCT = {
    "STANDARD": Decimal("0.06"),
    "PRIORITY": Decimal("0.03"),
    "PLATINUM": Decimal("0"),
}

DAY_S = 86400
MONTH_S = 30 * DAY_S


def line_total_cents(unit_price_cents, quantity, discount_pct):
    """round_half_up per line; the summation of these is the quote subtotal."""
    d = Decimal(str(discount_pct))
    return rhu(Decimal(unit_price_cents) * Decimal(quantity) * (Decimal(1) - d))


def quote_pricing(lines, tier):
    """Pinned order: per-line round -> subtotal -> handling bracket on the
    PRE-FEE subtotal -> tier fee on (subtotal + handling) -> total."""
    subtotal = 0
    for ln in lines:
        subtotal += line_total_cents(ln["unit_price_cents"], ln["quantity"],
                                     ln["discount_pct"])
    if subtotal < 100000:
        handling = 9500
    elif subtotal <= 1000000:
        handling = 4500
    else:
        handling = 0
    tier_fee = rhu(Decimal(subtotal + handling) * TIER_FEE_PCT[tier])
    total = subtotal + handling + tier_fee
    return subtotal, handling, tier_fee, total


def freight_cost(mode, distance_km, weight_kg, hazmat, escalated):
    if mode == "CHARTER":
        base = max(750000, 2900 * distance_km)
        premium = 0
    else:
        if weight_kg <= 5:
            per = 1200
        elif weight_kg <= 20:
            per = 900
        elif weight_kg <= 100:
            per = 650
        else:
            per = 480
        if distance_km < 1000:
            mult = Decimal("1.0")
        elif distance_km <= 4000:
            mult = Decimal("1.35")
        else:
            mult = Decimal("1.8")
        base = Decimal(per) * Decimal(weight_kg) * mult
        premium = 250000 if mode == "HOT_SHOT" else 0
    subtotal = Decimal(base) + Decimal(premium)
    if hazmat:
        subtotal = subtotal * Decimal("1.25")
    if escalated:
        subtotal = subtotal * Decimal("1.25")
    return rhu(subtotal)  # round exactly once, at the very end


def core_penalty_final(core_value_cents, days_overdue):
    d = days_overdue
    accrual = (Decimal("0.005") * core_value_cents * min(d, 7)
               + Decimal("0.01") * core_value_cents * max(0, min(d, 21) - 7))
    late_fee = 25000 if d >= 1 else 0
    return min(core_value_cents, late_fee + rhu(accrual))


def loan_settlement(loan, returned_at):
    """Return the total billed_cents target per LOAN / LEASE variant."""
    start = loan["_start_dt"]
    due = loan["_due_dt"]
    rate = loan["daily_rate_cents"]
    actual_days = max(1, ceil_div((returned_at - start).total_seconds(), DAY_S))
    if loan["loan_type"] == "LOAN":
        window_days = int((due - start).total_seconds()) // DAY_S
        on_time = min(actual_days, window_days)
        late = max(0, actual_days - on_time)
        return (on_time * rate
                + rhu(Decimal(late) * Decimal(rate) * Decimal("1.5")))
    # LEASE: whole periods, partial period rounds up, no late multiplier
    periods_used = ceil_div(actual_days, 30)
    return max(loan["lease_periods"], periods_used) * 30 * rate


def warranty_coverage(months_in_service):
    if months_in_service <= 6:
        return Decimal("1")
    if months_in_service <= 12:
        return Decimal("0.75")
    if months_in_service <= 24:
        return Decimal("0.5")
    return Decimal("0")


def restock_fee(line_total, days_since_delivery):
    pct = Decimal("0.10") if days_since_delivery <= 7 else Decimal("0.20")
    return rhu(Decimal(line_total) * pct)


DEBIT_TYPES = {
    "INVOICE_DEBIT", "CORE_DEPOSIT_DEBIT", "FREIGHT_DEBIT", "LOAN_DEBIT",
    "LEASE_DEBIT", "MANUAL_DEBIT",
}
CREDIT_TYPES = {
    "CORE_REFUND_CREDIT", "WARRANTY_CREDIT", "RESTOCK_CREDIT", "WAIVER_CREDIT",
    "PAYMENT_CREDIT", "MANUAL_CREDIT",
}
