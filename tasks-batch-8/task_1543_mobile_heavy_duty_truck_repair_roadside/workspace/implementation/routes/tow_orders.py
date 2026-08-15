"""TowOrder endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state, err_validation)
from middleware import auth
from response import success
from serializers import serialize
from services.cascades import append_event, wall_now
from routes.service_calls import get_call_or_404, ensure_not_cancelled
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("tow_orders", __name__)

CREATE_ROLES = ["Dispatcher", "Technician", "OpsAdmin"]
READ_ROLES = ["OpsAdmin", "Dispatcher", "Technician", "BillingClerk"]
LIST_ROLES = ["OpsAdmin", "Dispatcher", "BillingClerk"]
ACT_ROLES = ["Dispatcher", "OpsAdmin"]

TOW_BUFFER = timedelta(minutes=30)


def _get_tow(tow_id):
    t = store.tow_orders.get(tow_id)
    if t is None:
        raise err_not_found("TowOrder not found")
    return t


@bp.route("/roadside/service-calls/<serviceCallId>/tow-orders", methods=["POST"])
def create_tow(serviceCallId):
    uid, role = auth(CREATE_ROLES)
    call = get_call_or_404(serviceCallId)
    vals = validate_body(request.get_json(silent=True), [
        Field("tow_provider_name", "string", required=True),
        Field("tow_unit_id", "string", required=True),
        Field("pickup_location_text", "string", required=True),
        Field("dropoff_location_text", "string", required=True),
        Field("pickup_window_start_at", "datetime", required=True),
        Field("pickup_window_end_at", "datetime", required=True),
        Field("tow_fee_cents", "int", required=True, min_val=0),
    ])
    if vals["pickup_window_end_at"] <= vals["pickup_window_start_at"]:
        raise err_validation("pickup_window_end_at must be > pickup_window_start_at")
    ensure_not_cancelled(call)
    if call["status"] != "DIAGNOSED":
        raise err_invalid_state("Tow order requires status DIAGNOSED")
    # buffered pickup-window overlap on the shared tow unit (touching counts)
    ws = vals["pickup_window_start_at"] - TOW_BUFFER
    we = vals["pickup_window_end_at"] + TOW_BUFFER
    for t in store.tow_orders.values():
        if t["tow_unit_id"] == vals["tow_unit_id"] and t["status"] in (
                "REQUESTED", "HOOKED"):
            es = t["pickup_window_start_at"] - TOW_BUFFER
            ee = t["pickup_window_end_at"] + TOW_BUFFER
            if ws <= ee and es <= we:
                raise ApiError("ERR_TOW_WINDOW_OVERLAP",
                               "Tow unit already committed within the buffered "
                               "pickup window", 409)
    if call["resolution_path"] != "TOW_REQUIRED":
        raise ApiError("ERR_RESOLUTION_PATH_CONFLICT",
                       "Tow order requires resolution_path TOW_REQUIRED", 409)
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "service_call_id": call["id"],
        "tow_provider_name": vals["tow_provider_name"],
        "tow_unit_id": vals["tow_unit_id"],
        "pickup_location_text": vals["pickup_location_text"],
        "dropoff_location_text": vals["dropoff_location_text"],
        "pickup_window_start_at": vals["pickup_window_start_at"],
        "pickup_window_end_at": vals["pickup_window_end_at"],
        "tow_fee_cents": vals["tow_fee_cents"],
        "status": "REQUESTED",
        "hooked_at": None,
        "delivered_at": None,
    })
    store.tow_orders[rec["id"]] = rec
    call["status"] = "TOW_IN_PROGRESS"
    touch(call, now)
    append_event(call["id"], "TOW_REQUESTED", role, uid)
    return success(serialize("tow_order", rec), status=201)


@bp.route("/roadside/tow-orders/<towOrderId>", methods=["GET"])
def get_tow(towOrderId):
    auth(READ_ROLES)
    return success(serialize("tow_order", _get_tow(towOrderId)))


@bp.route("/roadside/tow-orders", methods=["GET"])
def list_tows():
    auth(LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    call_f = request.args.get("service_call_id")
    unit_f = request.args.get("tow_unit_id")
    status_f = request.args.get("status")
    items = sorted(store.tow_orders.values(), key=lambda r: r["_seq"])
    if call_f is not None:
        items = [t for t in items if t["service_call_id"] == call_f]
    if unit_f is not None:
        items = [t for t in items if t["tow_unit_id"] == unit_f]
    if status_f is not None:
        items = [t for t in items if t["status"] == status_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("tow_order", t) for t in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/tow-orders/<towOrderId>/hook", methods=["POST"])
def hook(towOrderId):
    uid, role = auth(ACT_ROLES)
    tow = _get_tow(towOrderId)
    validate_body(request.get_json(silent=True), [])
    if tow["status"] != "REQUESTED":
        raise err_invalid_state("Hook requires status REQUESTED")
    tow["status"] = "HOOKED"
    tow["hooked_at"] = store.clock
    touch(tow, wall_now())
    call = store.service_calls.get(tow["service_call_id"])
    if call is not None:
        append_event(call["id"], "TOW_HOOKED", role, uid)
    return success(serialize("tow_order", tow))


@bp.route("/roadside/tow-orders/<towOrderId>/deliver", methods=["POST"])
def deliver(towOrderId):
    uid, role = auth(ACT_ROLES)
    tow = _get_tow(towOrderId)
    validate_body(request.get_json(silent=True), [])
    if tow["status"] != "HOOKED":
        raise err_invalid_state("Deliver requires status HOOKED")
    tow["status"] = "DELIVERED"
    tow["delivered_at"] = store.clock
    touch(tow, wall_now())
    call = store.service_calls.get(tow["service_call_id"])
    if call is not None and call["status"] == "TOW_IN_PROGRESS":
        call["status"] = "TOWED"
        touch(call, wall_now())
        append_event(call["id"], "TOW_DELIVERED", role, uid)
    return success(serialize("tow_order", tow))


@bp.route("/roadside/tow-orders/<towOrderId>/cancel", methods=["POST"])
def cancel(towOrderId):
    uid, role = auth(ACT_ROLES)
    tow = _get_tow(towOrderId)
    validate_body(request.get_json(silent=True), [])
    if tow["status"] != "REQUESTED":
        raise err_invalid_state("Cancel requires status REQUESTED")
    tow["status"] = "CANCELLED"
    touch(tow, wall_now())
    call = store.service_calls.get(tow["service_call_id"])
    if call is not None and call["status"] == "TOW_IN_PROGRESS":
        call["status"] = "DIAGNOSED"
        touch(call, wall_now())
    return success(serialize("tow_order", tow))
