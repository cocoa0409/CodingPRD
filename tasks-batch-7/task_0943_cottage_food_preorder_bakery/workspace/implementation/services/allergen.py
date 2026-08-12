"""Recursive allergen union, tree depth, cycle detection, cross-contact advisory.

calculations.allergen_union / calculations.cross_contact_advisory, PRD 3.2.
"""

import config
from db import DB
from errors import ApiError


def components_of(recipe_id, extra=None):
    """Components of a recipe in ascending created_at order (PRD 3.2 walk order).

    `extra` is an optional prospective component dict used by rung 28 so a
    component attachment can be tested WITHOUT mutating anything.
    """
    out = [c for c in DB.values("recipe_components") if c["recipe_id"] == recipe_id]
    if extra is not None and extra.get("recipe_id") == recipe_id:
        out = out + [extra]
    return out


def _walk(recipe_id, depth, stack, extra, acc, lots, comps):
    if depth > config.ALLERGEN_TREE_MAX_DEPTH:
        raise ApiError("ERR_RECIPE_CYCLE_DETECTED",
                       "The sub-recipe tree exceeds the maximum depth of %d."
                       % config.ALLERGEN_TREE_MAX_DEPTH)
    if recipe_id in stack:
        raise ApiError("ERR_RECIPE_CYCLE_DETECTED",
                       "The sub-recipe closure is cyclic.")
    stack = stack + (recipe_id,)
    max_child_depth = 0
    for comp in components_of(recipe_id, extra):
        comps.append(comp)
        for a in comp.get("declared_allergens") or []:
            if isinstance(a, str):
                acc.add(a.lower())
        lot_id = comp.get("ingredient_lot_id")
        if lot_id:
            lot = DB.get("ingredient_lots", lot_id)
            if lot is not None:
                lots.append(lot)
                for a in lot.get("allergens") or []:
                    if isinstance(a, str):
                        acc.add(a.lower())
        sub_id = comp.get("sub_recipe_id")
        if sub_id:
            sub = DB.get("recipes", sub_id)
            if sub is None:
                continue
            child_depth = _walk(sub_id, depth + 1, stack, extra, acc, lots, comps)
            if child_depth > max_child_depth:
                max_child_depth = child_depth
    return 1 + max_child_depth


def profile(recipe_id, extra=None):
    """(allergen_union, tree_depth, lots_in_closure, components_in_closure).

    Raises ERR_RECIPE_CYCLE_DETECTED on a cycle or on depth > 5.
    """
    acc = set()
    lots = []
    comps = []
    depth = _walk(recipe_id, 1, (), extra, acc, lots, comps)
    return sorted(acc), depth, lots, comps


def union_only(recipe_id):
    """The sorted allergen union, tolerating a broken tree (returns [] then)."""
    try:
        allergens, _d, _l, _c = profile(recipe_id)
    except ApiError:
        return []
    return allergens


def advisory_applies(recipe_id, baker):
    """cross_contact_advisory: shared kitchen, or any lot in the closure flags
    cross contact.  Derived SEPARATELY from allergen_union (PRD 3.2)."""
    if baker is not None and baker.get("shared_kitchen"):
        return True
    try:
        _a, _d, lots, _c = profile(recipe_id)
    except ApiError:
        return False
    for lot in lots:
        if lot.get("cross_contact_allergens"):
            return True
    return False


def advisory_text(recipe_id, baker):
    return config.CROSS_CONTACT_ADVISORY_TEXT if advisory_applies(recipe_id, baker) else None


def closure_recalled(recipe_id, extra=None):
    """Rung 27: any component in the closure flagged recalled_component, or any
    referenced lot in lot_status RECALLED."""
    try:
        _a, _d, lots, comps = profile(recipe_id, extra)
    except ApiError:
        # a broken tree cannot be scanned; rung 28 will own that rejection
        return False
    for comp in comps:
        if comp.get("recalled_component"):
            return True
    for lot in lots:
        if lot.get("lot_status") == "RECALLED":
            return True
    return False


def recompute_recipe(recipe):
    """Recompute allergen_union / tree_depth / cross_contact_advisory in place."""
    baker = DB.get("bakers", recipe.get("baker_id"))
    try:
        allergens, depth, lots, _c = profile(recipe["id"])
    except ApiError:
        return
    recipe["allergen_union"] = allergens
    recipe["tree_depth"] = depth
    applies = bool(baker is not None and baker.get("shared_kitchen"))
    if not applies:
        for lot in lots:
            if lot.get("cross_contact_allergens"):
                applies = True
                break
    recipe["cross_contact_advisory"] = (
        config.CROSS_CONTACT_ADVISORY_TEXT if applies else None
    )


def recompute_menu_item_summaries(recipe_id):
    """PRD 3.2: publication recomputes allergen_summary on every menu item
    backed by this recipe.  The summary is a snapshot, not a version bump of
    the item -- the declared side effect names only the recompute."""
    for item in DB.coll("menu_items").values():
        if item.get("recipe_id") == recipe_id:
            item["allergen_summary"] = union_only(recipe_id)
