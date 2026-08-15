"""Assessment billing: invoice line computation and delinquency penalty.

Rounding order is pinned: each line is rounded half-up to cents FIRST, then
penalty and total are computed from the ROUNDED lines.
"""
from decimal import Decimal

from db import D, round2
from services import ledger

ZERO = Decimal("0")
LATE_PENALTY_PCT = Decimal("10")  # 10 percent of (acreage + toll) lines


def compute_lines(account, season, alloc):
    """Return (acreage_line_amount, toll_line_amount) for a new invoice."""
    if season["billing_method"] == "PER_ACRE":
        acreage = round2(D(account["irrigated_acres"]) * D(season["assessment_rate_per_acre"]))
        return acreage, ZERO
    # PER_AF_DELIVERED: tiered water toll on season-to-date verified deliveries.
    if alloc is not None:
        ledger.recompute_allocation(alloc)
        d = D(alloc["delivered_af"])
        pool = ledger.entitlement_pool(alloc)
    else:
        d = ZERO
        pool = ZERO
    cap = D(season["toll_tier1_cap_af"])
    tier1_af = min(d, cap)
    tier2_af = max(ZERO, d - cap)
    over_af = max(ZERO, d - pool)
    toll = round2(D(season["toll_tier1_rate_per_af"]) * tier1_af
                  + D(season["toll_tier2_rate_per_af"]) * tier2_af
                  + D(season["overage_rate_per_af"]) * over_af)
    return ZERO, toll


def invoice_total(inv):
    return (D(inv["acreage_line_amount"]) + D(inv["toll_line_amount"])
            + D(inv["penalty_line_amount"]))


def apply_delinquency_penalty(inv):
    inv["penalty_line_amount"] = round2(
        LATE_PENALTY_PCT / Decimal("100")
        * (D(inv["acreage_line_amount"]) + D(inv["toll_line_amount"])))
    inv["total_amount"] = invoice_total(inv)
