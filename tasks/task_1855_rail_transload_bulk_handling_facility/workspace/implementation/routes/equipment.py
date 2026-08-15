"""Equipment endpoints: create, get, list (contamination-audit filters),
cleaning cycle."""

from flask import Blueprint, request

from db import STORE, new_entity, touch, public
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, paginated
from validate import body, req_str, req_enum

bp = Blueprint("equipment", __name__)

EQUIPMENT_TYPES = ("CONVEYOR", "PUMP", "HOSE")


@bp.route("/transload/equipment", methods=["POST"])
def create_equipment():
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    data = body()
    name = req_str(data, "name")
    equipment_type = req_enum(data, "equipment_type", EQUIPMENT_TYPES)
    eq = new_entity(STORE.equipment, {
        "name": name,
        "equipment_type": equipment_type,
        "status": "AVAILABLE",
        "last_product_id": None,
    })
    return ok(public(eq), status=201)


@bp.route("/transload/equipment/<eid>", methods=["GET"])
def get_equipment(eid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    eq = STORE.equipment.get(eid)
    if eq is None:
        raise_err(ERR_NOT_FOUND, "equipment id does not exist")
    return ok(public(eq))


@bp.route("/transload/equipment", methods=["GET"])
def list_equipment():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    last_product_id = request.args.get("last_product_id")
    status = request.args.get("status")
    items = sorted(STORE.equipment.values(), key=lambda e: (e["created_at"], e["_seq"]))
    if last_product_id is not None:
        items = [e for e in items if e["last_product_id"] == last_product_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, meta = paginated(items)
    return ok([public(e) for e in page], pagination=meta)


@bp.route("/transload/equipment/<eid>/start-cleaning", methods=["POST"])
def start_cleaning(eid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    eq = STORE.equipment.get(eid)
    if eq is None:
        raise_err(ERR_NOT_FOUND, "equipment id does not exist")
    if eq["status"] != "AVAILABLE":
        raise_err(ERR_INVALID_STATE, "equipment is not AVAILABLE")
    eq["status"] = "CLEANING"
    touch(eq)
    return ok(public(eq))


@bp.route("/transload/equipment/<eid>/finish-cleaning", methods=["POST"])
def finish_cleaning(eid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    eq = STORE.equipment.get(eid)
    if eq is None:
        raise_err(ERR_NOT_FOUND, "equipment id does not exist")
    if eq["status"] != "CLEANING":
        raise_err(ERR_INVALID_STATE, "equipment is not CLEANING")
    eq["status"] = "AVAILABLE"
    eq["last_product_id"] = None
    touch(eq)
    return ok(public(eq))
