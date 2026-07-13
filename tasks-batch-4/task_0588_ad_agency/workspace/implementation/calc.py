"""Money, minutes and rounding discipline (PRD 2.6 and section 3 calculations)."""
from decimal import Decimal, ROUND_HALF_UP

# --- constants (SCAFFOLD 1.3) ----------------------------------------------
OVERTIME_THRESHOLD_MINUTES = 480
OVERTIME_MULTIPLIER = Decimal("1.5")
MAX_DAILY_MINUTES = 600
MAX_REVISION_ROUNDS = 3

MEDIA_TIER1_CENTS = 5000000
MEDIA_TIER2_CENTS = 20000000
MIN_COMMISSION_CENTS = 50000
MAX_COMMISSION_CENTS = 2500000

DISCOUNT_TIER1_CENTS = 10000000
DISCOUNT_TIER2_CENTS = 25000000
ADMIN_FEE_PCT = Decimal("0.03")

_ONE = Decimal("1")
_TENTH = Decimal("0.1")


def rhu(value):
    """Round half up to a whole cent (away from zero at exactly one half)."""
    return int(Decimal(value).quantize(_ONE, rounding=ROUND_HALF_UP))


def pct1(value):
    """Round half up to one decimal place; reported percentages (PRD 2.6)."""
    return float(Decimal(value).quantize(_TENTH, rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


# --- time entry -------------------------------------------------------------
def straight_line_cents(minutes, rate_cents_per_hour):
    return rhu(Decimal(minutes) * Decimal(rate_cents_per_hour) / Decimal(60))


def overtime_split(minutes, prior_minutes):
    regular = max(0, min(minutes, OVERTIME_THRESHOLD_MINUTES - prior_minutes))
    return regular, minutes - regular


def billable_amount(regular_minutes, overtime_minutes, rate):
    """Round per leg, then sum (PRD 2.6)."""
    reg = rhu(Decimal(regular_minutes) * Decimal(rate) / Decimal(60))
    ot = rhu(Decimal(overtime_minutes) * Decimal(rate) * OVERTIME_MULTIPLIER / Decimal(60))
    return reg + ot


# --- vendor markup ----------------------------------------------------------
def markup_lines(bases, markup_pct):
    """Round per line, then sum (PRD 2.6/3.6)."""
    factor = _ONE + dec(markup_pct)
    base_total = sum(bases)
    marked_up = sum(rhu(Decimal(b) * factor) for b in bases)
    return base_total, marked_up


# --- media commission -------------------------------------------------------
def media_commission(gross):
    if gross == 0:
        return 0
    if gross < MEDIA_TIER1_CENTS:
        rate = Decimal("0.15")
    elif gross < MEDIA_TIER2_CENTS:
        rate = Decimal("0.12")
    else:
        rate = Decimal("0.10")
    raw = rhu(Decimal(gross) * rate)
    return min(max(raw, MIN_COMMISSION_CENTS), MAX_COMMISSION_CENTS)


# --- invoice total ----------------------------------------------------------
def discount_rate(subtotal):
    if subtotal < DISCOUNT_TIER1_CENTS:
        return Decimal("0.00")
    if subtotal < DISCOUNT_TIER2_CENTS:
        return Decimal("0.05")
    return Decimal("0.08")


def invoice_total(labor_cents, vendor_marked_up_cents, media_commission_cents):
    subtotal = labor_cents + vendor_marked_up_cents + media_commission_cents
    pct = discount_rate(subtotal)
    discount = rhu(Decimal(subtotal) * pct)
    admin_fee = rhu(ADMIN_FEE_PCT * (Decimal(subtotal) - Decimal(discount)))
    total = subtotal - discount + admin_fee
    return {
        "subtotal_cents": subtotal,
        "discount_pct": float(pct),
        "discount_cents": discount,
        "admin_fee_cents": admin_fee,
        "total_cents": total,
    }
