"""Calculation rules from SCAFFOLD §1.3 / PRD §3.

All monetary values are integer cents. The only rounding is in the seller fee,
which uses sum-then-round half-up (PRD §2.7, §3.7).
"""
from decimal import Decimal, ROUND_HALF_UP

import constants as C


def bid_increment(p):
    """Minimum increment as a step function of price p (cents). PRD §3.3.

    Tier selected by lower-edge-inclusive comparison (>=).
      p <  10000        -> 100
      10000 <= p < 50000  -> 500
      50000 <= p < 100000 -> 1000
      p >= 100000       -> 2500
    """
    if p < C.T1_EDGE_CENTS:
        return C.INC_T0_CENTS
    if p < C.T2_EDGE_CENTS:
        return C.INC_T1_CENTS
    if p < C.T3_EDGE_CENTS:
        return C.INC_T2_CENTS
    return C.INC_T3_CENTS


def seller_fvf(gross_item_cents):
    """Marginal tiered final-value fee + insertion fee, capped. PRD §3.7.

    Marginal tiers (basis points on the slice in each tier):
      slice 0 .. 25000        -> 1255 bp
      slice 25000 .. 75000    -> 925 bp
      slice above 75000       -> 255 bp
    Sum-then-round: sum exact tier products, then round_half_up ONCE.
    Then + INSERTION_FEE_CENTS, then min(total, FVF_CAP_CENTS).
    """
    g = gross_item_cents
    if g < 0:
        g = 0

    t1_edge = C.FVF_T1_EDGE_CENTS
    t2_edge = C.FVF_T2_EDGE_CENTS

    slice1 = min(g, t1_edge)
    slice2 = max(0, min(g, t2_edge) - t1_edge)
    slice3 = max(0, g - t2_edge)

    # Exact products: slice_cents * bp / 10000
    prod1 = Decimal(slice1) * Decimal(C.FVF_BP_T1) / Decimal(10000)
    prod2 = Decimal(slice2) * Decimal(C.FVF_BP_T2) / Decimal(10000)
    prod3 = Decimal(slice3) * Decimal(C.FVF_BP_T3) / Decimal(10000)

    fvf_exact = prod1 + prod2 + prod3
    fvf_rounded = int(fvf_exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    total = fvf_rounded + C.INSERTION_FEE_CENTS
    total = min(total, C.FVF_CAP_CENTS)
    return total


def fvf_rate_basis_points(gross_item_cents):
    """Display-only audit figure: effective blended rate * 10000, rounded. PRD §3.7.

    blended rate = fvf (pre-insertion, pre-cap) / gross; *10000, rounded half up.
    """
    g = gross_item_cents
    if g <= 0:
        return 0
    t1_edge = C.FVF_T1_EDGE_CENTS
    t2_edge = C.FVF_T2_EDGE_CENTS
    slice1 = min(g, t1_edge)
    slice2 = max(0, min(g, t2_edge) - t1_edge)
    slice3 = max(0, g - t2_edge)
    prod1 = Decimal(slice1) * Decimal(C.FVF_BP_T1) / Decimal(10000)
    prod2 = Decimal(slice2) * Decimal(C.FVF_BP_T2) / Decimal(10000)
    prod3 = Decimal(slice3) * Decimal(C.FVF_BP_T3) / Decimal(10000)
    fvf_exact = prod1 + prod2 + prod3
    # blended rate = fvf_exact / g ; * 10000
    bp = (fvf_exact / Decimal(g)) * Decimal(10000)
    return int(bp.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
