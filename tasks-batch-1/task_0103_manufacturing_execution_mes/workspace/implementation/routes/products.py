"""Product + BOM-line endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
import lookups
import validators as V
from middleware import authenticate, authorize, get_json_body
from response import object_response, array_response
from serialize import public, public_list

bp = Blueprint("products", __name__)

PRODUCT_TYPES = {"FINISHED_GOOD", "SUBASSEMBLY", "RAW_MATERIAL"}

_SKU_ALNUM = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@bp.route("/products", methods=["POST"])
def create_product():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "PlantAdmin"])
    body = get_json_body()

    sku = V.as_string(V.require(body, "sku"), "sku")
    name = V.as_string(V.require(body, "name"), "name")
    product_type = V.as_enum(V.require(body, "product_type"), "product_type", PRODUCT_TYPES)

    # sku: uppercase alphanumeric, 3-32 chars
    if len(sku) < 3 or len(sku) > 32 or any(c not in _SKU_ALNUM for c in sku):
        raise errors.invalid_request("sku must be uppercase alphanumeric, 3-32 chars.")

    unit_cost = 0
    if "unit_cost_cents" in body and body["unit_cost_cents"] is not None:
        unit_cost = V.as_int(body["unit_cost_cents"], "unit_cost_cents")
        if unit_cost < 0:
            raise errors.invalid_request("unit_cost_cents must be >= 0.")

    lot_controlled = False
    if "lot_controlled" in body and body["lot_controlled"] is not None:
        lot_controlled = V.as_bool(body["lot_controlled"], "lot_controlled")

    with db.LOCK:
        # sku unique across all products
        for p in db.products.values():
            if p["sku"] == sku:
                raise errors.invalid_request("sku must be unique across all products.")
        rec = db.new_record()
        rec.update({
            "sku": sku,
            "name": name,
            "product_type": product_type,
            "unit_cost_cents": unit_cost,
            "lot_controlled": lot_controlled,
        })
        db.products[rec["id"]] = rec
        return object_response(public(rec), 201)


@bp.route("/products/<rid>", methods=["GET"])
def get_product(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    rec = lookups.product(rid)
    return object_response(public(rec))


# ---------------------------------------------------------------------------
# BOM lines
# ---------------------------------------------------------------------------
def _would_create_cycle(parent_id, component_id):
    """True if adding edge parent -> component creates a cycle (component can
    already reach parent via existing BomLines)."""
    # Walk down from component; if we reach parent, a cycle would form.
    children = {}
    for bl in db.bom_lines.values():
        children.setdefault(bl["parent_product_id"], []).append(bl["component_product_id"])
    seen = set()
    stack = [component_id]
    while stack:
        cur = stack.pop()
        if cur == parent_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children.get(cur, []))
    return False


@bp.route("/bom-lines", methods=["POST"])
def create_bom_line():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "PlantAdmin"])
    body = get_json_body()

    parent_id = V.as_string(V.require(body, "parent_product_id"), "parent_product_id")
    component_id = V.as_string(V.require(body, "component_product_id"), "component_product_id")
    quantity_per = V.as_number(V.require(body, "quantity_per"), "quantity_per")

    scrap = 0
    if "scrap_factor_pct" in body and body["scrap_factor_pct"] is not None:
        scrap = V.as_number(body["scrap_factor_pct"], "scrap_factor_pct")

    with db.LOCK:
        # Existence (priority 3) before business rules / well-formedness ranges.
        lookups.product(parent_id)
        lookups.product(component_id)

        # ERR_BOM_CYCLE (priority 11): self-loop OR cycle.
        if parent_id == component_id or _would_create_cycle(parent_id, component_id):
            raise errors.ApiError(errors.ERR_BOM_CYCLE,
                                  "BOM line would create a self-loop or cycle.", 409)

        # Field range constraints (well-formedness).
        if quantity_per <= 0:
            raise errors.invalid_request("quantity_per must be > 0.")
        if scrap < 0 or scrap >= 100:
            raise errors.invalid_request("scrap_factor_pct must be >= 0 and < 100.")

        rec = db.new_record()
        rec.update({
            "parent_product_id": parent_id,
            "component_product_id": component_id,
            "quantity_per": quantity_per,
            "scrap_factor_pct": scrap,
        })
        db.bom_lines[rec["id"]] = rec
        return object_response(public(rec), 201)


@bp.route("/bom-lines/<rid>", methods=["GET"])
def get_bom_line(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "PlantAdmin"])
    rec = lookups.bom_line(rid)
    return object_response(public(rec))


@bp.route("/bom-lines", methods=["GET"])
def list_bom_lines():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "PlantAdmin"])
    limit, offset = V.parse_pagination(request.args)
    parent = request.args.get("parent_product_id")
    component = request.args.get("component_product_id")

    rows = list(db.bom_lines.values())
    if parent is not None:
        rows = [r for r in rows if r["parent_product_id"] == parent]
    if component is not None:
        rows = [r for r in rows if r["component_product_id"] == component]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)
