from flask import Blueprint, request

import store
from auth import authenticate, require_role
from util import ApiError, object_response, array_response, paginate, apply_list, serialize
import validate as v
import services as svc
import lookups as lk

bp = Blueprint("repairs", __name__)

ORDER_TYPES = {"REPAIR", "REPLACEMENT"}


@bp.post("/repair-orders")
def open_order():
    user_id, role = authenticate()
    require_role(role, {"PremisesOwner", "UtilityAdmin"})
    body = v.json_object()

    raw_did = body.get("device_id")
    device = lk.get_device(raw_did) if isinstance(raw_did, str) and raw_did else None
    if device is not None:
        lk.ensure_owner_device(device, role, user_id)

    did = v.req_nonempty_str(body, "device_id")
    if device is None:
        device = lk.get_device(did)
        lk.ensure_owner_device(device, role, user_id)

    order_type = v.req_enum(body, "order_type", ORDER_TYPES)
    description = v.req_str(body, "description")
    repl_serial = v.opt_str(body, "replacement_serial_number")

    order = {
        "device_id": device["id"],
        "order_type": order_type,
        "description": description,
        "replacement_serial_number": repl_serial,
        "status": "OPEN",
    }
    svc.stamp_new(order)
    store.repair_orders[order["id"]] = order
    return object_response(serialize(order), 201)


@bp.get("/repair-orders")
def list_orders():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    limit, offset = paginate(request.args)

    did = request.args.get("device_id")
    status = request.args.get("status")

    pool = list(store.repair_orders.values())
    if did is not None:
        pool = [o for o in pool if o["device_id"] == did]
    if status is not None:
        pool = [o for o in pool if o["status"] == status]
    if role == "PremisesOwner":
        pool = [o for o in pool
                if lk.owns_connection(lk.connection_of_device(store.devices.get(o["device_id"])), user_id)]

    items, total = apply_list(pool, limit, offset)
    return array_response(items, limit, offset, total)


@bp.get("/repair-orders/<oid>")
def get_order(oid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    order = lk.get_repair_order(oid)
    if role == "PremisesOwner":
        lk.ensure_owner_device(store.devices.get(order["device_id"]), role, user_id)
    return object_response(serialize(order))


@bp.post("/repair-orders/<oid>/complete")
def complete_order(oid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    order = lk.get_repair_order(oid)
    if order["status"] != "OPEN":
        raise ApiError("ERR_REPAIR_NOT_OPEN", 409, "order is not OPEN")

    device = store.devices[order["device_id"]]
    if device["status"] != "NEEDS_REPAIR":
        raise ApiError("ERR_DEVICE_NOT_REPAIRABLE", 409, "device is not NEEDS_REPAIR")

    conn = store.connections[device["service_connection_id"]]

    body = v.optional_json_object()

    if order["order_type"] == "REPLACEMENT":
        serial = v.opt_str(body, "replacement_serial_number")
        if serial is None or serial.strip() == "":
            serial = order["replacement_serial_number"]
        if not serial or (isinstance(serial, str) and serial.strip() == ""):
            raise ApiError("ERR_REPLACEMENT_SERIAL_REQUIRED", 422,
                           "replacement_serial_number required")
        if any(d["serial_number"] == serial for d in store.devices.values()):
            raise ApiError("ERR_DUPLICATE_VALUE", 409, "serial_number already exists")

        before = svc.begin(conn)
        device["status"] = "REPLACED"
        svc.touch(device)
        new_device = {
            "service_connection_id": conn["id"],
            "serial_number": serial,
            "device_type": device["device_type"],
            "hazard_rating": device["hazard_rating"],
            "test_interval_months": device["test_interval_months"],
            "install_date": store.current_utc(),
            "last_pass_date": None,
            "next_test_due_date": svc.next_due_from(
                store.current_utc(), device["test_interval_months"]),
            "status": "ACTIVE",
        }
        svc.stamp_new(new_device)
        store.devices[new_device["id"]] = new_device
        order["replacement_serial_number"] = serial
        order["status"] = "COMPLETED"
        svc.touch(order)
        svc.auto_rescind_repair_notices(conn)
        svc.finish(conn, before)
    else:  # REPAIR
        before = svc.begin(conn)
        device["status"] = "ACTIVE"
        svc.touch(device)
        order["status"] = "COMPLETED"
        svc.touch(order)
        svc.auto_rescind_repair_notices(conn)
        svc.finish(conn, before, extra_increments=1)

    return object_response(serialize(order))


@bp.post("/repair-orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    order = lk.get_repair_order(oid)
    if role == "PremisesOwner":
        lk.ensure_owner_device(store.devices.get(order["device_id"]), role, user_id)
    if order["status"] != "OPEN":
        raise ApiError("ERR_REPAIR_NOT_OPEN", 409, "order is not OPEN")
    order["status"] = "CANCELLED"
    svc.touch(order)
    return object_response(serialize(order))
