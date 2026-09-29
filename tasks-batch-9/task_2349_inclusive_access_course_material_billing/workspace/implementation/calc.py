"""Pure calculation primitives -- PRD 2.6 rounding discipline and scaffold 1.3.

All money is integer cents.  Every ratio the system stores or reuses is rounded
half up to exactly 4 decimals BEFORE it feeds a later multiplication.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

# Named constants from scaffold 1.3
MIN_OPT_OUT_DAYS = 5
MIN_PARTICIPATION_RATE = Decimal("0.5000")
STATE_MIN_SAVINGS_PCT = Decimal("0.3000")
VARIANCE_TOLERANCE_CENTS = 500
MAX_OPT_OUT_CYCLES = 2
RATIO_DECIMALS = Decimal("0.0001")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rh_cents(value):
    """Round half up to whole cents."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rh4(value):
    """Round half up to exactly 4 decimal places."""
    return D(value).quantize(RATIO_DECIMALS, rounding=ROUND_HALF_UP)


def floor_cents(value):
    """Discard any fractional cent (round down)."""
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def ratio4(numerator, denominator):
    if denominator == 0:
        return Decimal("0.0000")
    return rh4(D(numerator) / D(denominator))


def total_term_days(term_start, term_end):
    return (term_end - term_start).days + 1


def gross_from_tier(per_student_price_cents, admin_fee_pct, list_price_cents,
                    max_list_price_pct, price_floor_cents):
    """Three-step per-student price (PRD 3.5).  Order is fixed:
    fee-inclusive price (half up) -> list cap (rounded DOWN) -> min -> floor last."""
    fee_applied = rh_cents(D(per_student_price_cents) * (Decimal(1) + D(admin_fee_pct)))
    list_cap = floor_cents(D(list_price_cents) * D(max_list_price_pct))
    return max(int(price_floor_cents), min(fee_applied, list_cap))


def proration_pct(enrolled_on, term_start, add_drop_deadline, term_days):
    """PRD 3.5 proration.  Ratio rounded to 4 decimals first."""
    if enrolled_on <= add_drop_deadline:
        return Decimal("1.0000")
    elapsed_days = (enrolled_on - term_start).days
    remaining = term_days - elapsed_days
    return ratio4(remaining, term_days)


def opt_out_deadline(posted_dt, opt_out_window_days, add_drop_deadline):
    """PRD 3.5: max( min(window_end, add/drop end-of-day), posted+MIN_OPT_OUT_DAYS )."""
    window_end = posted_dt + timedelta(days=int(opt_out_window_days))
    addrop_end = datetime(
        add_drop_deadline.year, add_drop_deadline.month, add_drop_deadline.day,
        23, 59, 59, 999000, tzinfo=timezone.utc,
    )
    floor_end = posted_dt + timedelta(days=MIN_OPT_OUT_DAYS)
    return max(min(window_end, addrop_end), floor_end)


def publisher_share(net_cents, bookstore_margin_pct):
    return rh_cents(D(net_cents) * (Decimal(1) - D(bookstore_margin_pct)))


def drop_refund(net_cents, dropped_on, term_start, add_drop_deadline, term_days):
    """PRD 3.7.  retained_pct rounded to 4 decimals before the multiplication."""
    if dropped_on <= add_drop_deadline:
        return int(net_cents)
    retained_pct = ratio4((dropped_on - term_start).days, term_days)
    refund = rh_cents(D(net_cents) * (Decimal(1) - retained_pct))
    return min(refund, int(net_cents))


def rebate_and_settlement(gross_invoice_cents, rebate_threshold_cents, rebate_pct):
    """PRD 3.8: the threshold is tested against the GROSS invoice and never
    re-tested against the settlement amount."""
    if gross_invoice_cents >= int(rebate_threshold_cents):
        rebate = rh_cents(D(gross_invoice_cents) * D(rebate_pct))
    else:
        rebate = 0
    return rebate, gross_invoice_cents - rebate
