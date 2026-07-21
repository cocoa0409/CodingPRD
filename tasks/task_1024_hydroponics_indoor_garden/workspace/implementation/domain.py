"""Domain side-effects: derived-field reconciliation, inventory waterfall,
credit and loyalty reconciliation (SCAFFOLD §1.2, §1.3 / PRD §2.7, §3.x).

All recompute helpers are PURE writes of derived values (no version bump); the
caller performs `touch()` once per mutated entity so version increments stay at
the granularity the PRD specifies.
"""
from store import store, touch
from calc import loyalty_tier_for


# ---------------------------------------------------------------- inventory ---
def set_lot_derived(lot):
    """quantity_available = on_hand - reserved; ACTIVE<->DEPLETED by availability
    (QUARANTINED lots are never auto-transitioned)."""
    lot["quantity_available"] = lot["quantity_on_hand"] - lot["quantity_reserved"]
    if lot["status"] != "QUARANTINED":
        lot["status"] = "DEPLETED" if lot["quantity_available"] == 0 else "ACTIVE"


def product_lots(product_id):
    return [l for l in store.inventory_lots.values() if l["product_id"] == product_id]


def set_product_derived(product):
    total = sum(
        l["quantity_available"]
        for l in product_lots(product["id"])
        if l["status"] == "ACTIVE"
    )
    product["total_available_units"] = total
    product["reorder_flag"] = total < product["reorder_threshold"]


def ordered_lots(product_id):
    """Waterfall order: created_at ASC then lot_code ASC (never id)."""
    lots = [
        l for l in store.inventory_lots.values()
        if l["product_id"] == product_id and l["status"] in ("ACTIVE", "DEPLETED")
    ]
    return sorted(lots, key=lambda l: (l["created_at"], l["lot_code"]))


def reserve_for_order(order):
    """Reserve each line's quantity across the product's lots. Records the
    per-lot reservation on the order and touches every mutated entity once."""
    reservations = {}  # lot_id -> qty
    touched_lots = set()
    touched_products = set()
    for line in order["lines"]:
        remaining = line["quantity"]
        for lot in ordered_lots(line["product_id"]):
            if remaining <= 0:
                break
            take = min(remaining, lot["quantity_available"])
            if take <= 0:
                continue
            lot["quantity_reserved"] += take
            set_lot_derived(lot)
            reservations[lot["id"]] = reservations.get(lot["id"], 0) + take
            remaining -= take
            touched_lots.add(lot["id"])
        touched_products.add(line["product_id"])
    order["_reservations"] = reservations
    for lot_id in touched_lots:
        touch(store.inventory_lots[lot_id])
    for pid in touched_products:
        p = store.products[pid]
        set_product_derived(p)
        touch(p)


def release_for_order(order):
    """Release a CONFIRMED order's reservations back to their lots."""
    reservations = order.get("_reservations", {})
    touched_products = set()
    for lot_id, qty in reservations.items():
        lot = store.inventory_lots.get(lot_id)
        if not lot:
            continue
        lot["quantity_reserved"] -= qty
        set_lot_derived(lot)
        touch(lot)
        touched_products.add(lot["product_id"])
    for pid in touched_products:
        p = store.products.get(pid)
        if p:
            set_product_derived(p)
            touch(p)
    order["_reservations"] = {}


def consume_for_order(order):
    """Ship: decrement on_hand and reserved by the shipped amount per lot."""
    reservations = order.get("_reservations", {})
    for lot_id, qty in reservations.items():
        lot = store.inventory_lots.get(lot_id)
        if not lot:
            continue
        lot["quantity_on_hand"] -= qty
        lot["quantity_reserved"] -= qty
        set_lot_derived(lot)
        touch(lot)
    order["_reservations"] = {}


# ------------------------------------------------------------------- credit ---
def set_credit_used(account):
    """Sum total_cents over the account's CONFIRMED/SHIPPED orders."""
    total = 0
    for o in store.orders.values():
        if o.get("commercial_account_id") == account["id"] and o["fulfillment_status"] in ("CONFIRMED", "SHIPPED"):
            total += o["total_cents"]
    account["credit_used_cents"] = total


# ------------------------------------------------------------------ loyalty ---
def apply_loyalty_tier(customer):
    customer["loyalty_tier"] = loyalty_tier_for(customer["loyalty_points"])


# ------------------------------------------------------------------- seats ----
def set_seats_taken(session):
    session["seats_taken"] = sum(
        1 for r in store.workshop_registrations.values()
        if r["session_id"] == session["id"] and r["status"] == "REGISTERED"
    )
