"""Parcel routes: register, list, read, shelf reassign, pickup, dispose, pickup-codes, authorizations, reminders."""
from flask import Blueprint, request
from response import ok_object, ok_array
from middleware import require_roles, get_auth
from services.common import parse_pagination, sort_by_created
from services.station import get_station
from services.parcel import (
    register_parcel, get_parcel, reassign_shelf, pickup_parcel, dispose_parcel,
    reissue_pickup_code, _mint_code,
)
from services.authorization import create_authorization, update_authorization
from services.reminder import list_reminders_for_parcel
from services.serialize import (
    parcel as ser_parcel, pickup_code as ser_code,
    pickup_auth as ser_auth, reminder as ser_reminder,
)
from db import store


bp = Blueprint("parcels", __name__)


@bp.post("/stations/<station_id>/parcels")
@require_roles("Clerk")
def post_parcel(station_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    p = register_parcel(station_id, body, role, user_id)
    return ok_object(ser_parcel(p), status=201)


@bp.get("/stations/<station_id>/parcels")
@require_roles("Manager", "Clerk")
def list_parcels(station_id):
    get_station(station_id)
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    recipient_phone_f = request.args.get("recipient_phone")
    items = [p for p in store.parcels.values() if p["station_id"] == station_id]
    if status_f:
        items = [p for p in items if p["status"] == status_f]
    if recipient_phone_f:
        items = [p for p in items if p["recipient_phone"] == recipient_phone_f]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array([ser_parcel(i) for i in page], limit, offset, total)


@bp.get("/parcels/<parcel_id>")
@require_roles("Manager", "Clerk", "Recipient", "CourierCompany")
def read_parcel(parcel_id):
    p = get_parcel(parcel_id)
    return ok_object(ser_parcel(p))


@bp.patch("/parcels/<parcel_id>/shelf")
@require_roles("Clerk", "Manager")
def patch_shelf(parcel_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    p = reassign_shelf(parcel_id, body, role, user_id)
    return ok_object(ser_parcel(p))


@bp.post("/parcels/<parcel_id>/pickup")
@require_roles("Clerk")
def post_pickup(parcel_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    p = pickup_parcel(parcel_id, body, role, user_id)
    return ok_object(ser_parcel(p))


@bp.post("/parcels/<parcel_id>/dispose")
@require_roles("Manager")
def post_dispose(parcel_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    p = dispose_parcel(parcel_id, body, role, user_id)
    return ok_object(ser_parcel(p))


@bp.post("/parcels/<parcel_id>/pickup-codes")
@require_roles("Clerk", "Recipient")
def post_pickup_code(parcel_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    c = reissue_pickup_code(parcel_id, body, role, user_id)
    return ok_object(ser_code(c), status=201)


@bp.get("/parcels/<parcel_id>/pickup-codes")
@require_roles("Clerk", "Manager", "Recipient")
def list_pickup_codes(parcel_id):
    get_parcel(parcel_id)
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    items = [c for c in store.pickup_codes.values() if c["parcel_id"] == parcel_id]
    if status_f:
        items = [c for c in items if c["status"] == status_f]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array([ser_code(i) for i in page], limit, offset, total)


@bp.post("/parcels/<parcel_id>/authorizations")
@require_roles("Recipient")
def post_authorization(parcel_id):
    body = request.get_json(silent=True, force=True) or {}
    a = create_authorization(parcel_id, body)
    return ok_object(ser_auth(a), status=201)


@bp.patch("/authorizations/<authorization_id>")
@require_roles("Recipient")
def patch_authorization(authorization_id):
    body = request.get_json(silent=True, force=True) or {}
    a = update_authorization(authorization_id, body)
    return ok_object(ser_auth(a))


@bp.get("/parcels/<parcel_id>/reminders")
@require_roles("Manager", "Clerk", "Recipient")
def list_reminders(parcel_id):
    get_parcel(parcel_id)
    limit, offset = parse_pagination(request.args)
    items = sort_by_created(list_reminders_for_parcel(parcel_id))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array([ser_reminder(i) for i in page], limit, offset, total)
