"""Component, ComponentLot, and variant-waiver endpoints."""
from flask import Blueprint, g, request

from core import (body, check_enum, check_number, check_string, err,
                  get_required, list_page, new_entity, require_roles, success,
                  touch)
from services import (D, must_get, run_proration, serialize_component,
                      serialize_lot, release_allocation)
from store import db, parse_dt

bp = Blueprint("components", __name__)

KINDS = {"RAW_MATERIAL", "BULK_FRAGRANCE", "COLORANT", "PRIMARY_PACK", "SECONDARY_PACK"}
SUPPLY_MODES = {"MANUFACTURER_SUPPLIED", "CUSTOMER_SUPPLIED"}
SENSORIAL = {"WITHIN_SPEC", "MINOR_VARIANT"}


def check_lot_confidentiality(comp):
    """CustomerRep may only access components/lots their own brand owns."""
    if g.user_role == "CustomerRep" and comp.get("customer_id") != g.user_id:
        err("ERR_CONFIDENTIALITY_VIOLATION", 403,
            "CustomerRep may only access their own brand's components and lots")


@bp.post("/cosmfg/components")
@require_roles("ProductionPlanner")
def create_component():
    b = body()
    name = check_string(get_required(b, "name"), "name")
    kind = check_enum(get_required(b, "kind"), KINDS, "kind")
    supply_mode = check_enum(get_required(b, "supply_mode"), SUPPLY_MODES, "supply_mode")
    cost = check_number(get_required(b, "standard_cost_per_kg_cents"),
                        "standard_cost_per_kg_cents", minimum=0)
    customer_id = b.get("customer_id")
    if customer_id is not None:
        must_get(db.customers, customer_id, "Customer")
    if supply_mode == "CUSTOMER_SUPPLIED" and customer_id is None:
        err("ERR_VALIDATION", 400,
            "customer_id is required when supply_mode is CUSTOMER_SUPPLIED")
    if supply_mode == "MANUFACTURER_SUPPLIED" and customer_id is not None:
        err("ERR_VALIDATION", 400,
            "customer_id must be null when supply_mode is MANUFACTURER_SUPPLIED")
    c = new_entity()
    c.update({
        "name": name,
        "kind": kind,
        "supply_mode": supply_mode,
        "customer_id": customer_id,
        "standard_cost_per_kg_cents": cost,
    })
    db.components[c["id"]] = c
    return success(serialize_component(c), status=201)


@bp.get("/cosmfg/components/<cid>")
@require_roles("ProductionPlanner", "QAManager", "PlantDirector",
               "FormulationChemist", "CustomerRep")
def get_component(cid):
    c = must_get(db.components, cid, "Component")
    check_lot_confidentiality(c)
    return success(serialize_component(c))


@bp.get("/cosmfg/components")
@require_roles("ProductionPlanner", "QAManager", "PlantDirector", "CustomerRep")
def list_components():
    items = list(db.components.values())
    if g.user_role == "CustomerRep":
        items = [c for c in items if c.get("customer_id") == g.user_id]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [c for c in items if c.get("customer_id") == customer_id]
    kind = request.args.get("kind")
    if kind is not None:
        items = [c for c in items if c["kind"] == kind]
    return list_page(items, serialize_component)


@bp.post("/cosmfg/components/<cid>/lots")
@require_roles("ProductionPlanner")
def create_lot(cid):
    comp = must_get(db.components, cid, "Component")
    b = body()
    lot_code = check_string(get_required(b, "lot_code"), "lot_code")
    for existing in db.lots.values():
        if existing["component_id"] == cid and existing["lot_code"] == lot_code:
            err("ERR_VALIDATION", 400, "lot_code must be unique per component")
    qty = check_number(get_required(b, "quantity_received"), "quantity_received",
                       minimum=0, exclusive_min=True)
    expires_at = get_required(b, "expires_at")
    if parse_dt(expires_at) is None:
        err("ERR_VALIDATION", 400, "expires_at must be an ISO-8601 datetime")
    unit_cost = b.get("unit_cost_per_kg_cents")
    if unit_cost is not None:
        check_number(unit_cost, "unit_cost_per_kg_cents", minimum=0)
    profile = check_enum(b.get("sensorial_profile", "WITHIN_SPEC"), SENSORIAL,
                         "sensorial_profile")
    lot = new_entity()
    lot.update({
        "component_id": cid,
        "lot_code": lot_code,
        "quantity_received": qty,
        "quantity_available": qty,
        "quantity_reserved": 0,
        "quantity_consumed": 0,
        "unit_cost_per_kg_cents": unit_cost,
        "expires_at": expires_at,
        "sensorial_profile": profile,
        "variant_waiver": "PENDING" if profile == "MINOR_VARIANT" else "NOT_REQUIRED",
        "status": "AVAILABLE",
    })
    db.lots[lot["id"]] = lot
    # Customer-supplied receipt: run the shortfall waterfall (PRD section 3.5)
    run_proration(lot)
    return success(serialize_lot(lot), status=201)


@bp.get("/cosmfg/lots/<lid>")
@require_roles("ProductionPlanner", "QAManager", "PlantDirector", "CustomerRep")
def get_lot(lid):
    lot = must_get(db.lots, lid, "ComponentLot")
    check_lot_confidentiality(must_get(db.components, lot["component_id"], "Component"))
    return success(serialize_lot(lot))


@bp.get("/cosmfg/components/<cid>/lots")
@require_roles("ProductionPlanner", "QAManager", "PlantDirector", "CustomerRep")
def list_lots(cid):
    comp = must_get(db.components, cid, "Component")
    check_lot_confidentiality(comp)
    items = [l for l in db.lots.values() if l["component_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_page(items, serialize_lot)


@bp.post("/cosmfg/lots/<lid>/waive-variant")
@require_roles("CustomerRep")
def waive_variant(lid):
    lot = must_get(db.lots, lid, "ComponentLot")
    comp = must_get(db.components, lot["component_id"], "Component")
    check_lot_confidentiality(comp)
    if lot["variant_waiver"] != "PENDING":
        err("ERR_INVALID_STATE", 409,
            "A waiver decision is only meaningful while variant_waiver is PENDING")
    b = body()
    decision = check_enum(get_required(b, "decision"), {"WAIVED", "REJECTED"}, "decision")
    if decision == "WAIVED":
        lot["variant_waiver"] = "WAIVED"
        touch(lot)
    else:
        lot["variant_waiver"] = "REJECTED"
        lot["status"] = "QUARANTINED"
        touch(lot)
        # Release every RESERVED allocation referencing this lot
        for a in db.allocations.values():
            if a["lot_id"] == lot["id"] and a["status"] == "RESERVED":
                release_allocation(a)
    return success(serialize_lot(lot))
