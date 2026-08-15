"""Gift-set bill-of-material rows (PRD §3.1). Rows are immutable after
creation; the graph must stay acyclic and component allergens must already be
declared by the gift product's recipes."""
from flask import Blueprint

from db import new_id, now, store
from errors import ApiError
from middleware import auth, body, is_int, require_fields
from response import success_object
from serializers import gift_component_json

gift_components_bp = Blueprint("gift_components", __name__)


def _recipe_allergen_union(product_id):
    result = set()
    for r in store.recipes.values():
        if r["product_id"] == product_id:
            result.update(r["allergens"])
    return result


def _creates_cycle(gift_product_id, component_product_id):
    """Directed edges run gift -> component. A new edge gift -> component
    closes a cycle iff the component can already reach the gift."""
    if gift_product_id == component_product_id:
        return True
    adjacency = {}
    for gc in store.gift_components.values():
        adjacency.setdefault(gc["gift_product_id"], []).append(gc["component_product_id"])
    stack = [component_product_id]
    seen = set()
    while stack:
        node = stack.pop()
        if node == gift_product_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, ()))
    return False


@gift_components_bp.route("/gift-components", methods=["POST"])
def create_gift_component():
    auth(("ProductionPlanner",))
    b = body()
    # Existence: body FK references must resolve (ERR_NOT_FOUND).
    gift_id = b.get("gift_product_id")
    comp_id = b.get("component_product_id")
    if gift_id is not None and gift_id not in store.products:
        raise ApiError("ERR_NOT_FOUND", "gift_product_id references a non-existent resource.")
    if comp_id is not None and comp_id not in store.products:
        raise ApiError("ERR_NOT_FOUND", "component_product_id references a non-existent resource.")
    # Request shape (ERR_INVALID_REQUEST).
    require_fields(b, ["gift_product_id", "component_product_id", "qty_per_set"])
    if not is_int(b["qty_per_set"]) or b["qty_per_set"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "qty_per_set must be an integer > 0.")
    # Allergen and sanitation safety (ERR_UNDECLARED_ALLERGEN): every allergen
    # carried by any recipe of the component product must be declared by at
    # least one recipe of the gift product.
    component_allergens = _recipe_allergen_union(b["component_product_id"])
    gift_allergens = _recipe_allergen_union(b["gift_product_id"])
    if not component_allergens.issubset(gift_allergens):
        raise ApiError("ERR_UNDECLARED_ALLERGEN",
                       "The component product carries an allergen not declared by any recipe of the gift product.")
    # Structural: the gift-component graph must stay acyclic, self-loops
    # included (ERR_GIFT_CYCLE).
    if _creates_cycle(b["gift_product_id"], b["component_product_id"]):
        raise ApiError("ERR_GIFT_CYCLE",
                       "This gift-component edge would create a cycle in the gift-set graph.")
    g = {
        "id": new_id(),
        "gift_product_id": b["gift_product_id"],
        "component_product_id": b["component_product_id"],
        "qty_per_set": b["qty_per_set"],
        "created_at": now(),
    }
    store.gift_components[g["id"]] = g
    return success_object(gift_component_json(g), 201)
