"""ProductLot endpoints (PRD §3.2).

Created nested under a compartment of a TENDERED shipment; read flat.
"""

from flask import Blueprint, request

from db import store
from errors import err
from helpers import (
    get_compartment_or_404,
    get_product_lot_or_404,
    pagination_params,
    paginate,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create
from response import array_response, object_response
from validators import as_int, as_string, get_body, require

bp = Blueprint("product_lots", __name__)


@bp.route("/compartments/<cid>/lots", methods=["POST"])
def create_lot(cid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "PlatformAdmin"})
    comp = get_compartment_or_404(cid)

    # only while the owning shipment is TENDERED
    shipment = store.shipments.get(comp["shipment_id"])
    if shipment is None or shipment["status"] != "TENDERED":
        raise err("ERR_INVALID_STATE", "Lots may only be added while the shipment is TENDERED")

    body = get_body(request)
    sku = as_string(require(body, "sku"), "sku")
    pallet_count = as_int(require(body, "pallet_count"), "pallet_count", minimum=0)
    declared_value_cents = as_int(
        require(body, "declared_value_cents"), "declared_value_cents", minimum=0
    )

    rec = {
        "compartment_id": cid,
        "sku": sku,
        "pallet_count": pallet_count,
        "declared_value_cents": declared_value_cents,
        "spoilage_status": "SOUND",
    }
    stamp_create(rec)
    store.product_lots[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/product-lots/<lid>", methods=["GET"])
def get_lot(lid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "ComplianceOfficer", "PlatformAdmin"})
    rec = get_product_lot_or_404(lid)
    return object_response(serialize(rec), 200)


@bp.route("/product-lots", methods=["GET"])
def list_lots():
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "ComplianceOfficer", "PlatformAdmin"})
    limit, offset = pagination_params()

    compartment_id = request.args.get("compartment_id")
    records = list(store.product_lots.values())
    if compartment_id is not None:
        records = [r for r in records if r["compartment_id"] == compartment_id]

    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)
