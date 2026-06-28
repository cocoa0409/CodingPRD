"""FIFO inventory consumption, restoration, and menu-item availability flips.

Implements scaffold §1.3 fifo_inventory_consumption and menu_item_availability,
and PRD §3.6.
"""
from db import store
from services.common import touch


def lots_for(stall_id, ingredient_name, only_remaining=False):
    """Candidate lots at a stall for an ingredient, ordered FIFO:
    received_at ASC, then created_at ASC tiebreak (never id) — PRD §3.4.

    We use the monotonic creation sequence as the strict tiebreak for
    created_at, since created_at has only millisecond resolution and lots
    created within the same request must keep a deterministic FIFO order."""
    lots = [
        l for l in store.ingredient_lots.values()
        if l["stall_id"] == stall_id and l["ingredient_name"] == ingredient_name
    ]
    if only_remaining:
        lots = [l for l in lots if l["grams_remaining"] > 0]
    lots.sort(key=lambda l: (l["received_at"], l["created_at"], l["_seq"]))
    return lots


def total_remaining(stall_id, ingredient_name):
    return sum(
        l["grams_remaining"]
        for l in store.ingredient_lots.values()
        if l["stall_id"] == stall_id and l["ingredient_name"] == ingredient_name
    )


def components_for(menu_item_id):
    return [
        rc for rc in store.recipe_components.values()
        if rc["menu_item_id"] == menu_item_id
    ]


def needs_for_order(order, line_items_resolved):
    """Aggregate gram needs per ingredient_name across all line items.

    line_items_resolved: list of (menu_item, qty). Returns a dict
    {ingredient_name: total_grams_needed}."""
    needs = {}
    for menu_item, qty in line_items_resolved:
        for rc in components_for(menu_item["id"]):
            need = rc["quantity_grams"] * qty
            needs[rc["ingredient_name"]] = needs.get(rc["ingredient_name"], 0) + need
    return needs


def can_fully_satisfy(stall_id, needs):
    """True iff every ingredient need is coverable by available lots at stall."""
    for ingredient_name, need in needs.items():
        if total_remaining(stall_id, ingredient_name) < need:
            return False
    return True


def consume_fifo(order, stall_id, needs):
    """Deduct grams FIFO and record consumption slices on the order.

    Caller MUST have verified can_fully_satisfy first (no partial deduction).
    Records order['_consumption'] = list of {lot_id, grams, unit_cost} slices."""
    slices = []
    for ingredient_name, need in needs.items():
        outstanding = need
        for lot in lots_for(stall_id, ingredient_name, only_remaining=True):
            if outstanding <= 0:
                break
            take = min(lot["grams_remaining"], outstanding)
            if take <= 0:
                continue
            lot["grams_remaining"] -= take
            outstanding -= take
            touch(lot)
            slices.append({
                "lot_id": lot["id"],
                "grams": take,
                "unit_cost_cents_per_gram": lot["unit_cost_cents_per_gram"],
            })
    order["_consumption"] = slices
    return slices


def restore_consumption(order):
    """Credit back exact grams each lot gave up for this order (cancellation)."""
    for sl in order.get("_consumption", []):
        lot = store.ingredient_lots.get(sl["lot_id"])
        if lot is None:
            continue
        lot["grams_remaining"] += sl["grams"]
        touch(lot)
    order["_consumption"] = []


def can_make_one_unit(menu_item, stall_id):
    """True iff, for EVERY recipe component, the stall's remaining grams for
    that ingredient >= quantity_grams. Boundary inclusive (>=)."""
    for rc in components_for(menu_item["id"]):
        if total_remaining(stall_id, rc["ingredient_name"]) < rc["quantity_grams"]:
            return False
    return True


def reevaluate_availability(menu_item, stall_id):
    """Flip a single menu item AVAILABLE<->SOLD_OUT against a stall's inventory.
    Bumps the item version on a flip (PRD §3.6)."""
    makeable = can_make_one_unit(menu_item, stall_id)
    if not makeable and menu_item["availability"] == "AVAILABLE":
        menu_item["availability"] = "SOLD_OUT"
        touch(menu_item)
    elif makeable and menu_item["availability"] == "SOLD_OUT":
        menu_item["availability"] = "AVAILABLE"
        touch(menu_item)


def menu_items_using_ingredient_at_stall(ingredient_name, stall_id):
    """Menu items (across all brands) whose recipe uses `ingredient_name`.

    Availability is evaluated against the inventory at `stall_id`. The set of
    candidate items is determined purely by recipe membership; the stall scopes
    which lots are counted."""
    item_ids = {
        rc["menu_item_id"]
        for rc in store.recipe_components.values()
        if rc["ingredient_name"] == ingredient_name
    }
    return [store.menu_items[i] for i in item_ids if i in store.menu_items]


def reevaluate_for_ingredient(ingredient_name, stall_id):
    """Re-evaluate availability for all menu items whose recipe uses this
    ingredient, against this stall's inventory (used on lot receipt)."""
    for mi in menu_items_using_ingredient_at_stall(ingredient_name, stall_id):
        reevaluate_availability(mi, stall_id)


def reevaluate_for_needs(needs, stall_id):
    """Re-evaluate availability for all menu items touched by these ingredient
    needs, against this stall's inventory (used after route/cancel)."""
    seen = set()
    for ingredient_name in needs:
        for mi in menu_items_using_ingredient_at_stall(ingredient_name, stall_id):
            if mi["id"] not in seen:
                seen.add(mi["id"])
                reevaluate_availability(mi, stall_id)
