"""Recipe-related business logic: allergen profile recompute (PRD §3.2)."""
import db


def bom_lines_for_recipe(recipe_id):
    return [b for b in db.bom_lines.values() if b["recipe_id"] == recipe_id]


def recompute_allergen_profile(recipe):
    """Union of allergens across the recipe's INGREDIENT BomLines' components.

    Packaging/label lines do not contribute. Defaults to empty set. Order is
    not significant; we emit a sorted list for determinism.
    """
    allergens = set()
    for line in bom_lines_for_recipe(recipe["id"]):
        comp = db.components.get(line["component_id"])
        if comp is None:
            continue
        if comp["kind"] == "INGREDIENT":
            for a in comp.get("allergens", []):
                allergens.add(a)
    recipe["allergen_profile"] = sorted(allergens)
