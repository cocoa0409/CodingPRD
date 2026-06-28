"""Calculation rules (scaffold §1.3 / PRD §2.7, §3.3, §3.5, §3.6, §3.7).

All money is integer cents. Decimal + ROUND_HALF_UP for any rounding; never
float arithmetic for monetary or score rounding.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value, places=0):
    """Round a Decimal/number half-up to the given number of decimal places."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    quant = Decimal(1).scaleb(-places)  # 10**-places as a Decimal
    return d.quantize(quant, rounding=ROUND_HALF_UP)


def scaled_score(raw_correct, total_items, baseline_scale_max):
    """practice_test_scaled_score (scaffold §1.3 / PRD §3.5).

    ratio = raw_correct / total_items as an EXACT rational; raw_scaled =
    ratio * baseline_scale_max; round the single product half-up to an integer.
    Round ONCE at the end — do not round the ratio first.
    """
    ratio = Decimal(raw_correct) / Decimal(total_items)
    raw_scaled = ratio * Decimal(baseline_scale_max)
    return int(round_half_up(raw_scaled, 0))


def percentile(scaled, baseline_scale_max):
    """percentile = round_half_up((scaled / baseline_scale_max) * 100, 1).

    Returned as a float carried to one decimal place (PRD §2.7).
    """
    pct = (Decimal(scaled) / Decimal(baseline_scale_max)) * Decimal(100)
    return float(round_half_up(pct, 1))


def enrollment_net_price(list_price_cents, coupon_code):
    """enrollment_net_price (scaffold §1.3 / PRD §3.3).

    EARLYBIRD -> 15% of list price rounded half-up to whole cents.
    REFER50   -> flat 5000 cents.
    None      -> 0 discount.
    price = max(base - discount, 0).
    Coupon-validity is checked upstream (ERR_INVALID_COUPON).
    """
    base = list_price_cents
    if coupon_code == "EARLYBIRD":
        discount = int(round_half_up(Decimal(base) * Decimal("0.15"), 0))
    elif coupon_code == "REFER50":
        discount = 5000
    else:
        discount = 0
    return max(base - discount, 0)


def installment_schedule(total_financed_cents, num_installments):
    """installment_schedule waterfall allocation (scaffold §1.3 / PRD §3.6).

    base_each = floor(total / N); remainder cents (0 <= r < N) allocated one cent
    each to the EARLIEST installments (lowest index first). Sum == total exactly.
    Returns the list of per-installment cent amounts (index 0 = first/earliest).
    """
    N = num_installments
    total = total_financed_cents
    base_each = total // N
    remainder = total - base_each * N
    return [base_each + (1 if i < remainder else 0) for i in range(N)]


def first_installment_amount(total_financed_cents, num_installments):
    """The amount of the earliest installment (index 0) of the schedule."""
    return installment_schedule(total_financed_cents, num_installments)[0]
