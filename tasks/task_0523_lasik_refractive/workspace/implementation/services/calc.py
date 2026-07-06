import math
from decimal import Decimal, ROUND_HALF_UP

from db import (
    OPTICAL_ZONE_MM,
    DEPTH_PER_DIOPTER_UM,
    FLAP_THICKNESS_UM,
    GUARANTEE_FEE_CENTS,
)


def ablation_depth_um(refractive_error_diopters):
    """Munnerlyn-style estimate, sum-then-round half-up to whole microns.
    raw = (OPTICAL_ZONE_MM ** 2) * error * DEPTH_PER_DIOPTER_UM
    """
    raw = Decimal(str(OPTICAL_ZONE_MM)) ** 2 * Decimal(str(refractive_error_diopters)) * Decimal(str(DEPTH_PER_DIOPTER_UM))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def residual_stromal_bed_um(corneal_thickness_um, ablation_um):
    return int(corneal_thickness_um) - FLAP_THICKNESS_UM - int(ablation_um)


def amortized_installment_cents(base_price_cents, down_payment_cents, term_months, apr_bps):
    """Financed remainder amortized; ceil to whole cents. Computed once at creation."""
    principal = base_price_cents - down_payment_cents
    monthly_rate = apr_bps / 10000 / 12
    if monthly_rate == 0:
        raw = principal / term_months
    else:
        factor = (1 + monthly_rate) ** term_months
        raw = principal * monthly_rate * factor / (factor - 1)
    return int(math.ceil(raw))


def refund_payout_cents(refund_mode, amount_settled_cents, deposit_cents):
    if refund_mode == "PRO_RATA":
        return max(0, amount_settled_cents - deposit_cents)
    elif refund_mode == "DEPOSIT_FORFEIT":
        return max(0, amount_settled_cents - deposit_cents - GUARANTEE_FEE_CENTS)
    return 0
