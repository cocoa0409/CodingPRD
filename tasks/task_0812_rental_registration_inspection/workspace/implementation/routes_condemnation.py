"""Condemnation order routes."""
from flask import Blueprint, request
from store import store, new_entity, touch
from auth import require_role, body, require_fields
from errors import err
from lookups import get_property, get_violation, get_condemnation, sorted_by_creation
from pagination import paginate
from envelope import success, list_response
from serializers import condemnation_dict
from domain import condemn_property

bp = Blueprint("condemnation", __name__)


@bp.post("/condemnation-orders")
def create_condemnation_order():
    require_role({"Registrar"})
    data = body()
    if data.get("property_id") is not None:
        get_property(data["property_id"])
    if data.get("triggering_violation_id") is not None:
        get_violation(data["triggering_violation_id"])
    require_fields(data, ["property_id", "basis"])
    e = new_entity(store.condemnation_orders, {
        "property_id": data["property_id"],
        "triggering_violation_id": data.get("triggering_violation_id"),
        "basis": data["basis"],
        "status": "DRAFT",
        "issued_at": None,
    })
    return success(condemnation_dict(e), status=201)


@bp.get("/condemnation-orders/<cid>")
def get_condemnation_route(cid):
    require_role({"Registrar", "Landlord"})
    e = get_condemnation(cid)
    return success(condemnation_dict(e), status=200)


@bp.get("/condemnation-orders")
def list_condemnation_orders():
    require_role({"Registrar", "Landlord"})
    items = list(store.condemnation_orders.values())
    for key in ("property_id", "triggering_violation_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return list_response([condemnation_dict(c) for c in page], limit, offset, total)


@bp.post("/condemnation-orders/<cid>/issue")
def issue_condemnation(cid):
    require_role({"Registrar"})
    order = get_condemnation(cid)
    if order["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Order is not DRAFT")
    prop = store.properties[order["property_id"]]
    has_escalated = any(
        v["property_id"] == prop["id"] and v["status"] == "ESCALATED"
        for v in store.violations.values()
    )
    if not has_escalated:
        raise err("ERR_NO_CONDEMNATION_BASIS", "Property has no escalated violation")
    order["status"] = "ISSUED"
    order["issued_at"] = store.now()
    touch(order)
    condemn_property(prop)
    return success(condemnation_dict(order), status=200)
