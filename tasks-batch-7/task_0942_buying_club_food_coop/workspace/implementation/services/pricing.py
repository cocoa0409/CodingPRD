"""price_binding and split_unit_price (SCAFFOLD §1.3, PRD §3.4 hop 2)."""

from decimal import Decimal

from core import clock
from core.constants import SPLIT_CASE_FEE_MIN_CENTS, SPLIT_CASE_FEE_PCT
from core.money import ceil_div, round_half_up
from core.store import DB, ordered


def price_versions_for(item_id):
    return ordered([p for p in DB.price_versions.values() if p["item_id"] == item_id])


def bound_price_version(item_id, instant):
    """The PriceVersion with the greatest effective_from satisfying
    effective_from <= instant (INCLUSIVE).  effective_from is unique per item,
    so no tie-break is needed."""
    best = None
    best_at = None
    for pv in price_versions_for(item_id):
        eff = clock.parse(pv["effective_from"])
        if eff <= instant:
            if best_at is None or eff > best_at:
                best = pv
                best_at = eff
    return best


def split_unit_price(case_price_cents, case_pack_units, qty_units):
    """Returns (base, is_split_unit, split_fee_per_unit_cents, unit_price_cents).

    The ceiling on `base` happens FIRST; the 12 percent fee is computed from the
    already-ceilinged base; only then are the two added.
    """
    base = ceil_div(case_price_cents, case_pack_units)
    if case_pack_units > 0 and qty_units % case_pack_units == 0:
        return base, False, 0, base
    fee = max(SPLIT_CASE_FEE_MIN_CENTS,
              round_half_up(Decimal(base) * Decimal(SPLIT_CASE_FEE_PCT)))
    return base, True, fee, base + fee


def live_unit_price(item, qty_units):
    """The unit price at the prices *currently in force* — i.e. the price
    version in force as of the current logical clock reading.  Used only for the
    live pre-lock DropRun.subtotal_cents; the bound price at lock is a separate
    computation keyed on the cycle's cutoff_at."""
    pv = bound_price_version(item["id"], clock.now())
    if pv is None:
        return 0
    _, _, _, unit_price = split_unit_price(pv["case_price_cents"],
                                           item["case_pack_units"], qty_units)
    return unit_price
