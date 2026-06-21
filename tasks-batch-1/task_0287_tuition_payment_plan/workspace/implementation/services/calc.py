"""Calculation rules (PRD §3.4, §3.5, §3.7, §3.8, §3.9).

All monetary values are integer cents. Non-integer intermediates round HALF UP.
"""
from decimal import Decimal, ROUND_HALF_UP

# late_fee_assessment constants (PRD §3.7)
FLAT_FEE_CENTS = 2500
MIN_FEE_CENTS = 2500
MAX_FEE_CENTS = 7500
MAX_TOTAL_LATE_FEE_CENTS = 30000

# delinquency_evaluation thresholds (PRD §3.8)
DELINQUENCY_COUNT_LIMIT = 3
DELINQUENCY_AMOUNT_LIMIT = 150000

# refund_proration brackets (PRD §3.9)
BRACKET_0_DAYS = 7
BRACKET_25_DAYS = 21
BRACKET_50_DAYS = 42


def round_half_up(value):
    """Round a numeric value to a whole integer with round-half-up (PRD §2.6)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_product(amount_cents, fraction):
    """round_half_up(amount_cents * fraction) using exact decimal arithmetic."""
    result = Decimal(int(amount_cents)) * Decimal(str(fraction))
    return int(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def installment_schedule(net_after_aid, down_payment_pct, installment_count,
                         term_total_days, term_start, add_days):
    """PRD §3.4 installment schedule. Returns (down_payment_cents,
    financed_principal, [(sequence_index, amount_cents, due_date), ...]).
    """
    net = max(0, net_after_aid)
    down_payment_cents = round_half_up_product(net, down_payment_pct)
    financed_principal = net - down_payment_cents
    n = installment_count
    base = financed_principal // n
    remainder = financed_principal - base * n  # 0 <= remainder < n
    cadence_days = term_total_days // (n + 1)
    rows = []
    for k in range(1, n + 1):
        amount = base + (1 if k <= remainder else 0)
        due_date = add_days(term_start, k * cadence_days)
        rows.append((k, amount, due_date))
    return down_payment_cents, financed_principal, rows


def respread_delta(delta_financed, scheduled_installments):
    """PRD §3.5 re-spread. scheduled_installments is a list of installment dicts
    in ascending sequence_index. Mutates each dict's amount_cents in place.

    Positive delta: base+remainder onto EARLIEST.
    Negative delta: reduce from LATEST first.
    """
    asc = sorted(scheduled_installments, key=lambda i: i["sequence_index"])
    m = len(asc)
    if delta_financed >= 0:
        base = delta_financed // m
        rem = delta_financed - base * m
        for j, inst in enumerate(asc):  # j 0-based ascending
            inst["amount_cents"] += base + (1 if j < rem else 0)
    else:
        credit = -delta_financed
        for inst in reversed(asc):  # descending sequence_index
            take = min(inst["amount_cents"], credit)
            inst["amount_cents"] -= take
            credit -= take
            if credit == 0:
                break


def late_fee_amount(overdue, days_late, late_fee_balance_cents):
    """PRD §3.7 late fee assessment. Returns the assessed fee in cents."""
    if days_late < 1:
        return 0
    elif days_late < 10:
        pct = "0.02"
    elif days_late < 30:
        pct = "0.04"
    else:
        pct = "0.06"
    pct_amount = round_half_up_product(overdue, pct)
    fee = max(FLAT_FEE_CENTS, pct_amount)
    fee = max(MIN_FEE_CENTS, min(MAX_FEE_CENTS, fee))
    remaining_cap = MAX_TOTAL_LATE_FEE_CENTS - late_fee_balance_cents
    fee = max(0, min(fee, remaining_cap))
    return fee


def delinquency_tripped(count, total_overdue):
    """PRD §3.8 thresholds. Returns (tripped, reason)."""
    count_tripped = count >= DELINQUENCY_COUNT_LIMIT
    amount_tripped = total_overdue >= DELINQUENCY_AMOUNT_LIMIT
    tripped = count_tripped or amount_tripped
    reason = "DELINQUENCY_COUNT" if count_tripped else "DELINQUENCY_AMOUNT"
    return tripped, reason


def schedule_based_bracket_pct(days_elapsed):
    """PRD §3.9 SCHEDULE_BASED step function. Returns a Decimal fraction."""
    if days_elapsed <= BRACKET_0_DAYS:
        return Decimal("0")
    elif days_elapsed <= BRACKET_25_DAYS:
        return Decimal("0.25")
    elif days_elapsed <= BRACKET_50_DAYS:
        return Decimal("0.50")
    else:
        return Decimal("1")


def refund_proration(variant, gross_charges_cents, total_aid_cents,
                     paid_principal_cents, days_elapsed, term_total_days):
    """PRD §3.9 refund proration. Returns (retained_charges_cents,
    net_owed_after_withdrawal_cents, refund_to_student_cents).
    """
    if variant == "DATE_BASED":
        fraction = Decimal(days_elapsed) / Decimal(term_total_days)
        retained = round_half_up_product(gross_charges_cents, fraction)
    else:  # SCHEDULE_BASED
        bracket_pct = schedule_based_bracket_pct(days_elapsed)
        retained = round_half_up_product(gross_charges_cents, bracket_pct)

    aid_offset = max(0, retained - total_aid_cents)
    net_owed = max(0, retained - total_aid_cents - paid_principal_cents)
    refund = max(0, paid_principal_cents - aid_offset)
    return retained, net_owed, refund
