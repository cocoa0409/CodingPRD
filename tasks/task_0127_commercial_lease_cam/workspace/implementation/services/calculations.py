"""Calculation engine (SCAFFOLD §1.3 / PRD §3.2, §3.4, §3.5, §3.7).

All monetary amounts are integer cents. Every money figure rounds to whole cents
using round-half-up (PRD §2.5). Pinned rounding orders are honored exactly.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import APIError, ERR_EMPTY_DENOMINATOR


def round_half_up(value) -> int:
    """Round a numeric (cents) value to a whole integer cent, half-up (PRD §2.5)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# gross_up_pool — recompute ExpensePool.total_recoverable_cents
# (PRD §3.2 / SCAFFOLD calculations.gross_up_pool)
# ---------------------------------------------------------------------------
def _line_items_for_pool(pool_id: str) -> list:
    """Line items on a pool walked in created_at (then _seq) order (PRD §2.4)."""
    items = [li for li in db.expense_line_items.values() if li["pool_id"] == pool_id]
    items.sort(key=lambda x: (x["created_at"], x.get("_seq", 0)))
    return items


def _gross_up_factor(prop: dict) -> Decimal:
    """gross_up_occupancy_pct / actual_occupancy, full precision."""
    total = prop["total_rentable_sqft"]
    occupied = prop["occupied_sqft"]
    # actual_occ = occupied / total; factor = gross_up_occupancy_pct / actual_occ
    #            = gross_up_occupancy_pct * total / occupied
    if occupied <= 0:
        # No occupancy → variable gross-up factor undefined. Variable items have a
        # zero actual-occupancy denominator; guard so recompute does not crash.
        # In practice a pool is locked only via a reconciliation post, which already
        # rejects a zero denominator with ERR_EMPTY_DENOMINATOR upstream.
        return None
    gop = Decimal(str(prop["gross_up_occupancy_pct"]))
    return gop * Decimal(total) / Decimal(occupied)


def _grossed_amount(item: dict, factor) -> int:
    """Per-line grossed amount: variable items grossed+rounded, fixed at face."""
    base = item["amount_cents"]
    if item["is_variable"]:
        if factor is None:
            # Zero-occupancy edge: treat variable gross-up factor as 0 multiplier is
            # wrong; instead fall back to face value so the pool total stays finite.
            # (A real post path is blocked by ERR_EMPTY_DENOMINATOR first.)
            return base
        return round_half_up(Decimal(base) * factor)
    return base


def compute_total_recoverable_cents(pool: dict) -> int:
    """Gross-up + admin fee per PRD §3.2.

    Walk RECOVERABLE and CAPPED_CONTROLLABLE items in created_at order; gross up each
    variable line (rounded per line) and sum; then apply admin_fee_pct rounded once on
    the sum. NON_RECOVERABLE items are skipped entirely.
    """
    prop = db.properties.get(pool["property_id"])
    factor = _gross_up_factor(prop) if prop else None
    recoverable = 0
    for item in _line_items_for_pool(pool["id"]):
        if item["recoverability"] not in ("RECOVERABLE", "CAPPED_CONTROLLABLE"):
            continue
        recoverable += _grossed_amount(item, factor)
    admin_fee = round_half_up(Decimal(recoverable) * Decimal(str(pool["admin_fee_pct"])))
    return recoverable + admin_fee


def _capped_slice_grossed(pool: dict) -> int:
    """Sum of grossed amounts over CAPPED_CONTROLLABLE items, NO admin fee (PRD §3.7)."""
    prop = db.properties.get(pool["property_id"])
    factor = _gross_up_factor(prop) if prop else None
    total = 0
    for item in _line_items_for_pool(pool["id"]):
        if item["recoverability"] == "CAPPED_CONTROLLABLE":
            total += _grossed_amount(item, factor)
    return total


# ---------------------------------------------------------------------------
# pro_rata_share (PRD §3.7 / SCAFFOLD calculations.pro_rata_share)
# ---------------------------------------------------------------------------
def compute_share(lease: dict, pool: dict) -> Decimal:
    """leased_sqft / pool-property denominator, full precision.

    Denominator is the POOL's property (pool.property_id), not the lease's, selected
    by pool.pro_rata_denominator. A non-positive denominator raises
    ERR_EMPTY_DENOMINATOR (PRD §3.7).
    """
    prop = db.properties.get(pool["property_id"])
    if prop is None:
        raise APIError(ERR_EMPTY_DENOMINATOR, 422, "Pool property not found")
    if pool["pro_rata_denominator"] == "TOTAL_RENTABLE":
        denom = prop["total_rentable_sqft"]
    else:  # OCCUPIED
        denom = prop["occupied_sqft"]
    if denom is None or denom <= 0:
        raise APIError(ERR_EMPTY_DENOMINATOR, 422, "Pro-rata denominator is zero")
    return Decimal(lease["leased_sqft"]) / Decimal(denom)


# ---------------------------------------------------------------------------
# controllable_cap (PRD §3.7 / SCAFFOLD calculations.controllable_cap)
# ---------------------------------------------------------------------------
def compute_controllable_cap(lease: dict, pool: dict, share: Decimal) -> dict:
    """Return {capped_pool, tenant_capped_share, allowed_capped}.

    The cap binds only when the tenant's capped share STRICTLY exceeds the ceiling;
    a share exactly equal to the ceiling is allowed in full.
    """
    capped_pool = _capped_slice_grossed(pool)
    tenant_capped_share = round_half_up(share * Decimal(capped_pool))
    cap_pct = Decimal(str(lease["controllable_cap_pct"]))
    prior_base = lease["prior_year_capped_base_cents"]
    if cap_pct > 0 and prior_base > 0:
        cap_ceiling = round_half_up(Decimal(prior_base) * (Decimal(1) + cap_pct))
        allowed_capped = min(tenant_capped_share, cap_ceiling)
    else:
        allowed_capped = tenant_capped_share
    return {
        "capped_pool": capped_pool,
        "tenant_capped_share": tenant_capped_share,
        "allowed_capped": allowed_capped,
    }


# ---------------------------------------------------------------------------
# reconciled_cam_true_up (PRD §3.7 / SCAFFOLD calculations.reconciled_cam_true_up)
# ---------------------------------------------------------------------------
def compute_true_up(lease: dict, pool: dict) -> dict:
    """Compute the four snapshot figures (raises ERR_EMPTY_DENOMINATOR on zero denom).

    Returns {pro_rata_share_pct, reconciled_cam_cents, estimated_cam_billed_cents,
             true_up_cents}.
    """
    share = compute_share(lease, pool)

    capped_pool = _capped_slice_grossed(pool)
    admin_fee_pct = Decimal(str(pool["admin_fee_pct"]))
    capped_admin = round_half_up(Decimal(capped_pool) * admin_fee_pct)
    # Non-capped pool = total_recoverable - capped grossed slice - admin fee on it.
    noncapped_pool = pool["total_recoverable_cents"] - capped_pool - capped_admin
    tenant_noncapped = round_half_up(share * Decimal(noncapped_pool))

    cap = compute_controllable_cap(lease, pool, share)
    allowed_capped = cap["allowed_capped"]
    capped_with_admin = allowed_capped + round_half_up(Decimal(allowed_capped) * admin_fee_pct)

    # Pinned: round each tenant slice, then sum (NOT sum-then-round).
    reconciled_cam_cents = tenant_noncapped + capped_with_admin
    estimated_cam_billed_cents = 12 * lease["estimated_cam_cents_monthly"]
    true_up_cents = reconciled_cam_cents - estimated_cam_billed_cents

    return {
        "pro_rata_share_pct": float(share),
        "reconciled_cam_cents": reconciled_cam_cents,
        "estimated_cam_billed_cents": estimated_cam_billed_cents,
        "true_up_cents": true_up_cents,
    }


# ---------------------------------------------------------------------------
# base_rent_escalation (PRD §3.4 / SCAFFOLD calculations.base_rent_escalation)
# ---------------------------------------------------------------------------
def compute_escalated_base(lease: dict, current_cpi_index) -> int:
    old_base = lease["base_rent_cents_annual"]
    etype = lease["escalation_type"]
    if etype == "NONE":
        return old_base
    if etype == "FIXED_PCT":
        rate = Decimal(str(lease["escalation_rate"]))
        return round_half_up(Decimal(old_base) * (Decimal(1) + rate))
    # CPI: indexed increase, floored at 0 then capped at escalation_rate (collar).
    base_index = Decimal(str(lease["cpi_base_index"]))
    cur = Decimal(str(current_cpi_index))
    raw_increase = (cur - base_index) / base_index
    if raw_increase < 0:
        raw_increase = Decimal(0)  # floor BEFORE cap
    applied = min(raw_increase, Decimal(str(lease["escalation_rate"])))
    return round_half_up(Decimal(old_base) * (Decimal(1) + applied))


# ---------------------------------------------------------------------------
# percentage_rent (PRD §3.5 / SCAFFOLD calculations.percentage_rent)
# ---------------------------------------------------------------------------
def latest_sales_report(lease_id: str, period_year: int):
    """Latest SalesReport for (lease_id, period_year) by created_at ASC tie-break.

    "Latest" = the most recently created report; created_at (then _seq) breaks ties.
    """
    matches = [
        r for r in db.sales_reports.values()
        if r["lease_id"] == lease_id and r["period_year"] == period_year
    ]
    if not matches:
        return None
    matches.sort(key=lambda x: (x["created_at"], x.get("_seq", 0)))
    return matches[-1]


def compute_percentage_rent(lease: dict, report: dict) -> int:
    excess = max(0, report["gross_sales_cents"] - lease["pct_rent_breakpoint_cents"])
    return round_half_up(Decimal(excess) * Decimal(str(lease["pct_rent_rate"])))
