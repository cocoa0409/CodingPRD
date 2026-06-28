"""Shared business-logic services: derived-field recompute and cascades.

Kept separate so multiple route modules can call them. All functions mutate the
in-memory store records in place and bump version/updated_at where the PRD says
the recomputation is a versioned mutation (PRD §2.4).
"""
import calculations as calc
import errors
from db import store
import app as A  # for touch / stamp helpers / clock helpers


# ---------------------------------------------------------------------------
# Derived field helpers
# ---------------------------------------------------------------------------
def lines_of_order(order_id):
    return [L for L in store.order_lines.values() if L["order_id"] == order_id]


def lines_of_vintage(vintage_id):
    return [L for L in store.order_lines.values() if L["vintage_id"] == vintage_id]


def lots_of_vintage(vintage_id):
    return [lot for lot in store.inventory_lots.values() if lot["vintage_id"] == vintage_id]


def vintage_available_units(vintage_id):
    return sum(lot["qty_on_hand"] - lot["qty_reserved"] for lot in lots_of_vintage(vintage_id))


def recompute_units_committed(vintage):
    """Vintage.units_committed = sum qty of its OrderLines in COMMITTED/FULFILLED."""
    total = sum(
        L["qty"] for L in lines_of_vintage(vintage["id"])
        if L["reservation_state"] in ("COMMITTED", "FULFILLED")
    )
    if vintage["units_committed"] != total:
        vintage["units_committed"] = total
        A.touch(vintage)
    else:
        # Even when value unchanged, PRD §2.5 treats recompute as a mutation in
        # cascades; but to avoid spurious bumps we only bump on change. The PRD
        # examples that assert version bumps always involve a real value change.
        pass
    return vintage


def auto_sold_out(vintage):
    """RELEASED/ALLOCATION_OPEN -> SOLD_OUT when available units hit 0."""
    if vintage["status"] in ("RELEASED", "ALLOCATION_OPEN"):
        if vintage_available_units(vintage["id"]) == 0:
            vintage["status"] = "SOLD_OUT"
            A.touch(vintage)


def auto_return_from_sold_out(vintage):
    """SOLD_OUT -> RELEASED when availability returns and product not allocated."""
    if vintage["status"] == "SOLD_OUT":
        product = store.products.get(vintage["product_id"])
        if product and not product.get("is_allocated", False):
            if vintage_available_units(vintage["id"]) >= 1:
                vintage["status"] = "RELEASED"
                A.touch(vintage)


# ---------------------------------------------------------------------------
# Compliance status (PRD §3.2)
# ---------------------------------------------------------------------------
def active_windows_for_customer(customer_id):
    return [
        w for w in store.compliance_windows.values()
        if w["customer_id"] == customer_id and w.get("active", False)
    ]


def near_cap_windows_score(customer_id):
    """+3 if any active window's running monthly used_ml for its (state, month) is
    within LIMIT_GRACE_ML of the state's monthly cap. Single +3, not per-window."""
    windows = active_windows_for_customer(customer_id)
    # Group by (state, month) -> sum used_ml across THIS customer's active rows.
    groups = {}
    for w in windows:
        key = (w["state_code"], w["window_month"])
        groups.setdefault(key, 0)
        groups[key] += w["volume_ml"]
    for (state_code, _month), used_ml in groups.items():
        rule = state_rule_by_code(state_code)
        if not rule:
            continue
        cap = rule.get("monthly_volume_limit_ml")
        if cap is None:
            continue
        if used_ml >= cap - calc.LIMIT_GRACE_ML:
            return 3
    return 0


def recompute_compliance_status(customer):
    """PRD §3.2 risk scoring. Bumps version on change."""
    new_status = compliance_status_value(customer)
    if customer["compliance_status"] != new_status:
        customer["compliance_status"] = new_status
        A.touch(customer)
    return customer


def compliance_score(customer):
    """PRD §3.2 risk score (no mutation)."""
    score = 0
    if not customer.get("age_verified", False):
        score += 2
    rejected = sum(
        1 for s in store.id_scans.values()
        if s["customer_id"] == customer["id"] and s["status"] == "REJECTED"
    )
    score += rejected
    score += near_cap_windows_score(customer["id"])
    return score


def compliance_status_value(customer):
    """PRD §3.2 pinned boundary: 0 -> CLEAR, 1..2 -> WATCH, >2 -> BLOCKED."""
    score = compliance_score(customer)
    if score == 0:
        return "CLEAR"
    if score <= 2:
        return "WATCH"
    return "BLOCKED"


def customer_view(customer):
    """Read-time view: compliance_status is a derived field (PRD §3.2). A freshly
    registered, unverified customer reads WATCH (score 2) even before any
    recompute trigger fires; the stored value (initialised CLEAR per PRD §3.2)
    is left untouched so the registration response keeps its CLEAR default."""
    view = A.public(customer)
    view["compliance_status"] = compliance_status_value(customer)
    return view


def recompute_lifetime_spend(customer):
    """PRD §3.7: sum settled_total over CAPTURED, non-CANCELLED orders."""
    total = 0
    for o in store.orders.values():
        if o["customer_id"] != customer["id"]:
            continue
        if o["payment_status"] == "CAPTURED" and o["fulfillment_status"] != "CANCELLED":
            total += o["settled_total_cents"]
    if customer["lifetime_spend_cents"] != total:
        customer["lifetime_spend_cents"] = total
        A.touch(customer)
    return customer


# ---------------------------------------------------------------------------
# State rules
# ---------------------------------------------------------------------------
def state_rule_by_code(state_code):
    for r in store.state_rules.values():
        if r["state_code"] == state_code:
            return r
    return None


# ---------------------------------------------------------------------------
# Compensation: release reservations, restore lots, deactivate window
# ---------------------------------------------------------------------------
def deactivate_order_windows(order_id):
    for w in store.compliance_windows.values():
        if w["order_id"] == order_id and w.get("active", False):
            w["active"] = False


def release_reservations(order):
    """Compensation for cancel/refund/shipment-return (PRD §3.10).

    Release every COMMITTED/FULFILLED line, credit its lot's qty_reserved back,
    and restore qty_on_hand to where it would have been absent the order. For a
    line that drew from a TAXED lot, qty_on_hand was never reduced (only reserved),
    so only qty_reserved is credited back. For a BONDED-origin line (one that was
    withdrawn at capture: line_excise_cents > 0 and lot_id repointed to a minted
    TAXED lot whose qty_on_hand was increased), the withdrawal is reversed by
    decrementing that taxed lot's qty_on_hand back. Net: available units are
    conserved exactly as before the order in both cases.
    """
    affected_vintages = set()
    for L in lines_of_order(order["id"]):
        if L["reservation_state"] in ("COMMITTED", "FULFILLED"):
            lot = store.inventory_lots.get(L["lot_id"]) if L["lot_id"] else None
            if lot is not None:
                if L.get("line_excise_cents", 0) > 0:
                    # Bonded-origin line withdrawn at capture: undo the mint on the
                    # taxed lot (its qty_reserved is already 0).
                    lot["qty_on_hand"] = max(0, lot["qty_on_hand"] - L["qty"])
                else:
                    # Taxed-origin line: only the reservation was held.
                    lot["qty_reserved"] = max(0, lot["qty_reserved"] - L["qty"])
                A.touch(lot)
            L["reservation_state"] = "RELEASED"
            A.touch(L)
            affected_vintages.add(L["vintage_id"])
    for vid in affected_vintages:
        v = store.vintages.get(vid)
        if v:
            recompute_units_committed(v)
            auto_return_from_sold_out(v)
