"""Product-centric derived-field maintenance.

These helpers keep on_hand_units / needs_reorder consistent and propagate
unit_cost changes into recipe costs and menu pour-cost percentages, per:
  - PRD §2.4: derived recomputations are mutations (bump version + updated_at).
  - PRD §2.8: needs_reorder recomputed on every on_hand_units change and on par
    supersession; false when no ACTIVE par setting.
  - PRD §3.3 / §3.4: recipe_cost_cents and pour_cost_pct recompute when a
    referenced product's unit_cost_cents changes.
"""
from db import db, touch
from money import D, round_cents, round_half_up, to_number


def active_par(product_id):
    for p in db.par_settings.values():
        if p["product_id"] == product_id and p["status"] == "ACTIVE":
            return p
    return None


def recompute_needs_reorder(product):
    """needs_reorder is true exactly when on_hand_units is strictly less than the
    reorder_point_units of the product's ACTIVE par setting; false when there is
    no active par setting (PRD §2.8). Caller is responsible for touch()."""
    par = active_par(product["id"])
    if par is None:
        product["needs_reorder"] = False
    else:
        product["needs_reorder"] = D(product["on_hand_units"]) < D(par["reorder_point_units"])


def set_on_hand(product, new_value):
    """Overwrite on_hand_units (count finalize) and recompute needs_reorder.
    Bumps version/updated_at because a derived-field change is a mutation."""
    product["on_hand_units"] = to_number(round_half_up(D(new_value), 3))
    recompute_needs_reorder(product)
    touch(product)


def adjust_on_hand(product, delta, floor_zero=False):
    """Add delta (may be negative) to on_hand_units, optionally floored at 0,
    then recompute needs_reorder and bump the version."""
    new_val = D(product["on_hand_units"]) + D(delta)
    if floor_zero and new_val < 0:
        new_val = D(0)
    product["on_hand_units"] = to_number(round_half_up(new_val, 3))
    recompute_needs_reorder(product)
    touch(product)


def recompute_needs_reorder_only(product):
    """Recompute needs_reorder without changing on_hand (used on par supersede).
    Bumps version because the flag is a derived field (PRD §2.4)."""
    recompute_needs_reorder(product)
    touch(product)


# ---- Recipe cost propagation (compute_recipe_cost, PRD §3.3) -----------------

def line_cost(product, pour_ml):
    """line_cost_cents = round_half_up(unit_cost_cents * pour_ml / container_volume_ml)."""
    numer = D(product["unit_cost_cents"]) * D(pour_ml)
    return round_cents(numer / D(product["container_volume_ml"]))


def recompute_recipe_cost(recipe):
    """recipe_cost_cents = sum of per-line line_cost_cents (round-per-line then
    sum), lines considered in created_at ASC order. Recomputes each line's
    line_cost_cents against the current product unit_cost (PRD §3.3)."""
    lines = [rl for rl in db.recipe_lines.values() if rl["recipe_id"] == recipe["id"]]
    lines.sort(key=lambda rl: (rl["created_at"], rl["_seq"]))
    total = 0
    for rl in lines:
        product = db.products.get(rl["product_id"])
        if product is None:
            lc = rl.get("line_cost_cents", 0)
        else:
            lc = line_cost(product, rl["pour_ml"])
            rl["line_cost_cents"] = lc
        total += lc
    recipe["recipe_cost_cents"] = total
    touch(recipe)


def recompute_pour_cost_pct(menu_item):
    """pour_cost_pct = recipe_cost_cents / menu_price_cents * 100, 2dp (PRD §3.4)."""
    recipe = db.recipes.get(menu_item["recipe_id"])
    recipe_cost = recipe["recipe_cost_cents"] if recipe else 0
    price = D(menu_item["menu_price_cents"])
    pct = round_half_up(D(recipe_cost) / price * D(100), 2)
    menu_item["pour_cost_pct"] = to_number(pct)
    touch(menu_item)


def propagate_unit_cost_change(product_id):
    """When a product's unit_cost_cents changes (invoice post), recompute every
    recipe that pours it, and every menu item on those recipes (PRD §3.3/§3.4)."""
    affected_recipe_ids = set()
    for rl in db.recipe_lines.values():
        if rl["product_id"] == product_id:
            affected_recipe_ids.add(rl["recipe_id"])
    for rid in affected_recipe_ids:
        recipe = db.recipes.get(rid)
        if recipe is None:
            continue
        recompute_recipe_cost(recipe)
        for mi in db.menu_items.values():
            if mi["recipe_id"] == rid:
                recompute_pour_cost_pct(mi)
