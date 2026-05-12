"""ReturnShipment routes."""
from flask import Blueprint, request
from response import ok_object
from middleware import require_roles, get_auth
from services.return_shipment import (
    create_return_shipment, courier_response, ship_return,
)
from services.serialize import return_shipment as ser_rs


bp = Blueprint("returns", __name__)


@bp.post("/parcels/<parcel_id>/return-shipments")
@require_roles("Manager")
def post_return_shipment(parcel_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    rs = create_return_shipment(parcel_id, body, role, user_id)
    return ok_object(ser_rs(rs), status=201)


@bp.post("/return-shipments/<return_shipment_id>/courier-response")
@require_roles("PlatformAdmin", "CourierCompany")
def post_courier_response(return_shipment_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    rs = courier_response(return_shipment_id, body, role, user_id)
    return ok_object(ser_rs(rs))


@bp.post("/return-shipments/<return_shipment_id>/ship")
@require_roles("PlatformAdmin", "CourierCompany")
def post_ship_return(return_shipment_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    rs = ship_return(return_shipment_id, body, role, user_id)
    return ok_object(ser_rs(rs))
