"""Monetary calculations: commission, net-to-seller, financing DTI."""
from decimal import Decimal, ROUND_HALF_UP

SELLER_CONCESSION_CENTS = 0
MAX_DTI = Decimal("0.43")
MONTHLY_PAYMENT_FACTOR = Decimal("0.005")


def round_half_up(value):
    """Round a Decimal to the nearest whole integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def total_commission(sale_price_cents, total_commission_pct):
    return round_half_up(Decimal(sale_price_cents) * Decimal(str(total_commission_pct)))


def commission_split(sale_price_cents, total_commission_pct, coop_split_pct):
    """Pinned nested rounding: round total first, then co-op off the rounded total."""
    total = total_commission(sale_price_cents, total_commission_pct)
    coop = round_half_up(Decimal(total) * Decimal(str(coop_split_pct)))
    listing_side = total - coop
    return {
        "total_commission_cents": total,
        "coop_commission_cents": coop,
        "listing_side_commission_cents": listing_side,
    }


def net_to_seller(basis_price_cents, total_commission_pct):
    total = total_commission(basis_price_cents, total_commission_pct)
    net = basis_price_cents - total - SELLER_CONCESSION_CENTS
    return {"total_commission_cents": total, "net_to_seller_cents": net}


def financing_passes(buyer, effective_price_cents):
    """Back-end DTI gate plus pre-qualification ceiling."""
    monthly_pi = round_half_up(Decimal(effective_price_cents) * MONTHLY_PAYMENT_FACTOR)
    income = buyer["monthly_income_cents"]
    # income is non-negative; guard divide-by-zero -> treated as failing the ratio
    if income <= 0:
        dti_ok = False
    else:
        back_end_dti = (Decimal(buyer["monthly_debt_cents"]) + Decimal(monthly_pi)) / Decimal(income)
        dti_ok = back_end_dti <= MAX_DTI
    prequal_ok = effective_price_cents <= buyer["prequalified_amount_cents"]
    return dti_ok and prequal_ok
