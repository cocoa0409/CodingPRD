"""Component and ComponentLot endpoints (PRD §3.1)."""
from flask import Blueprint, request

import clock
import db
import errors
import response
import serializers
import util
from middleware import require_role, ALL_ROLES
from services import inventory

bp = Blueprint("components", __name__)

VALID_KINDS = {"INGREDIENT", "PACKAGING", "LABEL"}


@bp.route("/copack/components", methods=["POST"])
@require_role("Receiver")
def create_component():
    body = util.get_json_body()
    util.require_fields(body, "customer_id", "sku", "name", "kind")
    customer_id = body["customer_id"]
    sku = body["sku"]
    name = body["name"]
    kind = body["kind"]
    allergens = body.get("allergens", [])

    if not all(isinstance(v, str) for v in (customer_id, sku, name, kind)):
        raise errors.invalid_request("customer_id, sku, name, kind must be strings")
    if allergens is None:
        allergens = []
    if not isinstance(allergens, list) or not all(isinstance(a, str) for a in allergens):
        raise errors.invalid_request("allergens must be an array of strings")

    # priority 7: body FK existence (customer_id).
    customer = db.customers.get(customer_id)
    if customer is None:
        raise errors.not_found("Customer not found")

    # priority 6: sku unique within customer_id.
    for c in db.components.values():
        if c["customer_id"] == customer_id and c["sku"] == sku:
            raise errors.duplicate_sku()

    # priority 9: kind enum validity.
    if kind not in VALID_KINDS:
        raise errors.invalid_enum("kind must be one of INGREDIENT, PACKAGING, LABEL")

    # customer_owned snapshotted from Customer.owns_components at create time.
    rec = db.new_full_record({
        "customer_id": customer_id,
        "sku": sku,
        "name": name,
        "kind": kind,
        "allergens": list(allergens),
        "customer_owned": bool(customer["owns_components"]),
        "on_hand_qty": 0,
        "reserved_qty": 0,
    })
    db.components[rec["id"]] = rec
    return response.success(serializers.component(rec), status=201)


@bp.route("/copack/components/<cid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_component(cid):
    rec = db.components.get(cid)
    if rec is None:
        raise errors.not_found("Component not found")
    return response.success(serializers.component(rec), status=200)


@bp.route("/copack/components", methods=["GET"])
@require_role(*ALL_ROLES)
def list_components():
    limit, offset = util.parse_pagination()
    customer_id = request.args.get("customer_id")
    items = list(db.components.values())
    if customer_id is not None:
        items = [c for c in items if c["customer_id"] == customer_id]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.component(r) for r in window], status=200, pagination=meta)


@bp.route("/copack/components/<cid>/lots", methods=["POST"])
@require_role("Receiver")
def receive_lot(cid):
    # priority 3: path existence (component).
    component = db.components.get(cid)
    if component is None:
        raise errors.not_found("Component not found")

    body = util.get_json_body()
    util.require_fields(body, "supplier_lot_code", "received_qty", "expiration_date")
    supplier_lot_code = body["supplier_lot_code"]
    received_qty = body["received_qty"]
    expiration_date = body["expiration_date"]

    if not isinstance(supplier_lot_code, str):
        raise errors.invalid_request("supplier_lot_code must be a string")
    if not util.is_number(received_qty):
        raise errors.invalid_request("received_qty must be a number")
    if not isinstance(expiration_date, str):
        raise errors.invalid_request("expiration_date must be a string")

    # priority 8: received_qty > 0.
    if received_qty <= 0:
        raise errors.invalid_quantity("received_qty must be > 0")

    # priority 9: expiration_date must be a valid ISO instant (past or future).
    parsed = clock.parse_iso8601(expiration_date)
    if parsed is None:
        raise errors.invalid_enum("expiration_date must be a valid ISO 8601 instant")

    rec = db.new_full_record({
        "component_id": cid,
        "supplier_lot_code": supplier_lot_code,
        "received_qty": received_qty,
        "remaining_qty": received_qty,
        # store the normalized ISO form for consistent comparison/output
        "expiration_date": expiration_date,
        "_expiration_dt": parsed,
        "status": "AVAILABLE",
    })
    db.component_lots[rec["id"]] = rec

    # recompute Component.on_hand_qty immediately. The component is mutated.
    inventory.recompute_component_on_hand(component)
    db.touch(component)

    return response.success(serializers.component_lot(rec), status=201)


@bp.route("/copack/components/<cid>/lots", methods=["GET"])
@require_role(*ALL_ROLES)
def list_component_lots(cid):
    # path existence first
    component = db.components.get(cid)
    if component is None:
        raise errors.not_found("Component not found")
    limit, offset = util.parse_pagination()
    items = [l for l in db.component_lots.values() if l["component_id"] == cid]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.component_lot(r) for r in window], status=200, pagination=meta)


@bp.route("/copack/component-lots/<lid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_component_lot(lid):
    rec = db.component_lots.get(lid)
    if rec is None:
        raise errors.not_found("Component lot not found")
    return response.success(serializers.component_lot(rec), status=200)
