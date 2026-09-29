"""Every arithmetic rule in PRD 2.5, 3.3, 3.6-3.10.

Money is integer cents throughout; rates are integer basis points;
percentages carry exactly two decimals.  Rounding is half up (away from zero)
except for the two pinned exceptions: the rate-optimisation ceiling truncates
toward zero and a funder's available capital is floored at zero.
"""

from decimal import Decimal, ROUND_HALF_UP

DAY_COUNT_BASIS = 360
BPS_DIVISOR = 10000
MIN_PROGRAM_APR_BPS = 200
MAX_COUNTER_ROUNDS = 3
MAX_MICRO_DEPOSIT_ATTEMPTS = 3
SESSION_COOLDOWN_MINUTES = 60
VALUE_DATE_LAG_DAYS = 2

TWO_PLACES = Decimal("0.01")


def rhu(value):
    """Round a Decimal half up to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_div(numerator, denominator):
    return rhu(Decimal(numerator) / Decimal(denominator))


def pct(numerator, denominator):
    """Percentage with exactly two decimals; 0.00 when the denominator is 0."""
    if denominator == 0:
        return Decimal("0.00")
    value = (Decimal(100) * Decimal(numerator)) / Decimal(denominator)
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def trunc_div(numerator, denominator):
    """Truncate toward zero."""
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.to_integral_value(rounding="ROUND_DOWN"))


# --------------------------------------------------------------------------
# invoice pricing (PRD 3.3)
# --------------------------------------------------------------------------

def price_lines(lines):
    """lines: iterable of (line_no, line_amount_cents, tax_rate_bps) in
    ascending line_no order.  Round each line's tax first, then sum."""
    priced = []
    face = 0
    for line_no, amount, tax_rate_bps in lines:
        tax = rhu_div(Decimal(amount) * Decimal(tax_rate_bps), BPS_DIVISOR)
        total = amount + tax
        priced.append(
            {
                "line_no": line_no,
                "line_amount_cents": amount,
                "tax_rate_bps": tax_rate_bps,
                "line_tax_cents": tax,
                "line_total_cents": total,
            }
        )
        face += total
    return face, priced


def micro_deposit_code(routing_number, account_last4):
    """Last three digits of the routing number concatenated with the first
    three digits of the account last four, as a zero padded 6 digit decimal."""
    return "%s%s" % (routing_number[-3:], account_last4[:3])


# --------------------------------------------------------------------------
# early payment arithmetic (PRD 3.8)
# --------------------------------------------------------------------------

def days_early(net_due_date, basis_dt):
    """Whole calendar days between the basis date and net_due_date."""
    return (net_due_date.date() - basis_dt.date()).days


def discount_cents(face_amount_cents, accepted_apr_bps, days):
    return rhu_div(
        Decimal(face_amount_cents) * Decimal(accepted_apr_bps) * Decimal(days),
        Decimal(BPS_DIVISOR) * Decimal(DAY_COUNT_BASIS),
    )


def fee_tier_bps(pre_fee_net_cents):
    """Tier keyed on the pre-fee net (face minus discount), never post-fee."""
    if pre_fee_net_cents < 5000000:
        return 45
    if pre_fee_net_cents < 25000000:
        return 30
    return 18


def funder_fee_cents(pre_fee_net_cents, funding_source, funder):
    if funding_source == "BUYER_SELF" or funder is None:
        return 0
    effective = fee_tier_bps(pre_fee_net_cents) + funder["fee_spread_bps"]
    return rhu_div(Decimal(pre_fee_net_cents) * Decimal(effective), BPS_DIVISOR)


def net_payment_cents(face, discount, fee):
    return face - discount - fee


def default_accounting_status(funding_source, days, accepted_apr_bps, buyer):
    """Computed once at reservation and never recomputed (PRD 3.9)."""
    if funding_source == "BUYER_SELF":
        return "TRADE_PAYABLE"
    if days > buyer["reclass_days_threshold"]:
        return "DEBT_RECLASSIFIED"
    if accepted_apr_bps > buyer["reclass_apr_threshold_bps"]:
        return "DEBT_RECLASSIFIED"
    return "TRADE_PAYABLE"


# --------------------------------------------------------------------------
# funder capital (PRD 3.7)
# --------------------------------------------------------------------------

def committed_at(commitments, target_date):
    """Sum of committed_amount_cents over the funder's ACTIVE tranches whose
    closed effective interval contains target_date."""
    total = 0
    for row in commitments:
        if row["status"] != "ACTIVE":
            continue
        if row["_effective_from"].date() <= target_date <= row["_effective_to"].date():
            total += row["committed_amount_cents"]
    return total


def available_capital(committed, encumbered):
    return max(0, committed - encumbered)


def funder_score(funder, accepted_apr_bps, headroom, pre_fee_net):
    spread = accepted_apr_bps - funder["min_apr_bps"]
    score = 2 * min(400, spread) - 3 * funder["fee_spread_bps"]
    if headroom >= 2 * pre_fee_net:
        score += 150
    return score


# --------------------------------------------------------------------------
# analytics (PRD 3.10)
# --------------------------------------------------------------------------

ELIGIBLE_STATUSES = ("ELIGIBLE", "OFFERED", "AWARDED", "EARLY_PAID")


def rate_posture(adoption_pct):
    if adoption_pct < Decimal("25.00"):
        return "DISCOVERY"
    if adoption_pct < Decimal("60.00"):
        return "OPTIMISED"
    return "THROTTLED"


def weighted_avg_apr(rows):
    """rows: iterable of (accepted_apr_bps, face_amount_cents)."""
    numerator = 0
    denominator = 0
    for apr, face in rows:
        numerator += apr * face
        denominator += face
    if denominator == 0:
        return 0
    return rhu_div(numerator, denominator)


def ceiling_candidate(posture, weighted_avg, current_ceiling):
    if posture == "DISCOVERY":
        return current_ceiling
    if posture == "OPTIMISED":
        return max(MIN_PROGRAM_APR_BPS, trunc_div(weighted_avg * 90, 100))
    return max(MIN_PROGRAM_APR_BPS, trunc_div(weighted_avg * 75, 100))


def tightened_ceiling(current_ceiling, posture, weighted_avg):
    """The ceiling is monotone: it only ever tightens."""
    return min(current_ceiling, ceiling_candidate(posture, weighted_avg, current_ceiling))


def clearing_apr(rows):
    """Face weighted mean APR over offers exactly ACCEPTED at close."""
    numerator = 0
    denominator = 0
    for apr, face in rows:
        numerator += apr * face
        denominator += face
    if denominator == 0:
        return 0
    return rhu_div(numerator, denominator)


def advice_number(invoice_number, existing_count):
    return "RA-%s-%02d" % (invoice_number, existing_count + 1)
