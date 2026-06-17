"""Work-order pricing engine (PRD §3.6 / calculations.work_order_total).

A work order's price is rebuilt from scratch — never patched incrementally —
every time its inputs change. All amounts are integer cents; the steps run
strictly in the documented order. round_half_up at each per-line discount and
at the final tax step; the cap is a plain floor.
"""
import db
from common import round_half_up, floor_int


def _non_voided_lines(work_order_id: str):
    return [ln for ln in db.work_order_lines.values()
            if ln["work_order_id"] == work_order_id and not ln["voided"]]


def recompute_pricing(w: dict) -> None:
    """Recompute all pricing fields of a work order in place.

    Does NOT touch version/updated_at — the caller stamps the mutation where the
    PRD declares a version bump (e.g. add-line). Pure derived reconciliation
    (e.g. a fleet suspend re-price) is stamped by its own caller.
    """
    shop = db.shops[w["shop_id"]]
    vehicle = db.vehicles[w["vehicle_id"]]

    # --- base ---
    package_price = w["package_price_cents"]
    lines = _non_voided_lines(w["id"])
    lines_total = sum(ln["price_cents"] for ln in lines)
    subtotal = package_price + lines_total

    # --- coupon component (PER-LINE rounding for PERCENT; package = one line) ---
    coupon = _resolve_coupon(w, subtotal)
    if coupon is None:
        coupon_discount = 0
    elif coupon["discount_type"] == "PERCENT":
        pct = coupon["percent_value"]
        coupon_discount = round_half_up(package_price * pct)
        for ln in lines:
            coupon_discount += round_half_up(ln["price_cents"] * pct)
    else:  # FLAT
        coupon_discount = min(coupon["flat_cents"], subtotal)

    # --- fleet component ---
    fleet_acct = None
    if vehicle.get("fleet_account_id"):
        fleet_acct = db.fleet_accounts.get(vehicle["fleet_account_id"])
    if fleet_acct is None or fleet_acct["status"] != "ACTIVE":
        fleet_discount = 0
    else:
        fleet_discount = round_half_up(subtotal * fleet_acct["discount_pct"])

    # --- stacking rule, then cap ---
    if coupon is not None and coupon["stackable_with_fleet"]:
        raw_discount = coupon_discount + fleet_discount
    else:
        raw_discount = max(coupon_discount, fleet_discount)
    cap = floor_int(subtotal * shop["max_discount_pct"])
    total_discount = min(raw_discount, cap)

    # --- tax on discounted base, then total ---
    taxable_base = subtotal - total_discount
    tax = round_half_up(taxable_base * shop["tax_rate"])
    total = taxable_base + tax

    w["lines_total_cents"] = lines_total
    w["subtotal_cents"] = subtotal
    w["coupon_discount_cents"] = coupon_discount
    w["fleet_discount_cents"] = fleet_discount
    w["total_discount_cents"] = total_discount
    w["tax_cents"] = tax
    w["total_cents"] = total


def _resolve_coupon(w: dict, subtotal: int):
    """Return the eligible coupon for pricing, or None.

    Per the formula's input_set: coupon contributes only when present, status is
    ACTIVE, and subtotal >= min_subtotal_cents. (Apply-time eligibility errors
    are enforced separately at apply-coupon; here we silently treat an
    ineligible coupon as a zero component, per §3.6.)
    """
    code = w.get("coupon_code")
    if not code:
        return None
    coupon = _find_coupon(code, w["shop_id"])
    if coupon is None:
        return None
    if coupon["status"] != "ACTIVE":
        return None
    if subtotal < coupon["min_subtotal_cents"]:
        return None
    return coupon


def _find_coupon(code: str, shop_id: str):
    for c in db.coupons.values():
        if c["code"] == code and c["shop_id"] == shop_id:
            return c
    return None


def find_coupon(code: str, shop_id: str):
    return _find_coupon(code, shop_id)
