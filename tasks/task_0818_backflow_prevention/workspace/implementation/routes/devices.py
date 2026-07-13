from flask import Blueprint, request

import store
from auth import authenticate, require_role
from util import ApiError, object_response, array_response, paginate, apply_list, serialize
import validate as v
import services as svc
import lookups as lk

bp = Blueprint("devices", __name__)

DEVICE_TYPES = {"RP", "DC", "PVB", "DCDA"}
HAZARD_RATINGS = {"HIGH", "LOW"}
DEVICE_STATUSES = {"ACTIVE", "NEEDS_REPAIR", "REPLACED", "REMOVED"}


@bp.post("/devices")
def create_device():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    body = v.json_object()

    raw_scid = body.get("service_connection_id")
    conn = None
    if isinstance(raw_scid, str) and raw_scid:
        conn = lk.get_connection(raw_scid)

    raw_serial = body.get("serial_number")
    if isinstance(raw_serial, str) and raw_serial:
        if any(d["serial_number"] == raw_serial for d in store.devices.values()):
            raise ApiError("ERR_DUPLICATE_VALUE", 409, "serial_number already exists")

    scid = v.req_nonempty_str(body, "service_connection_id")
    serial = v.req_nonempty_str(body, "serial_number")
    device_type = v.req_enum(body, "device_type", DEVICE_TYPES)
    hazard_rating = v.req_enum(body, "hazard_rating", HAZARD_RATINGS)
    interval = v.opt_int(body, "test_interval_months", lo=1, default=12)
    install = v.req_datetime(body, "install_date")

    if conn is None:
        conn = lk.get_connection(scid)

    before = svc.begin(conn)
    device = {
        "service_connection_id": conn["id"],
        "serial_number": serial,
        "device_type": device_type,
        "hazard_rating": hazard_rating,
        "test_interval_months": interval,
        "install_date": install,
        "last_pass_date": None,
        "next_test_due_date": svc.next_due_from(install, interval),
        "status": "ACTIVE",
    }
    svc.stamp_new(device)
    store.devices[device["id"]] = device
    svc.finish(conn, before)
    return object_response(serialize(device), 201)


@bp.get("/devices")
def list_devices():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    limit, offset = paginate(request.args)

    scid = request.args.get("service_connection_id")
    status = request.args.get("status")

    pool = list(store.devices.values())
    if scid is not None:
        pool = [d for d in pool if d["service_connection_id"] == scid]
    if status is not None:
        pool = [d for d in pool if d["status"] == status]
    if role == "PremisesOwner":
        pool = [d for d in pool if lk.owns_connection(lk.connection_of_device(d), user_id)]

    items, total = apply_list(pool, limit, offset)
    return array_response(items, limit, offset, total)


@bp.get("/devices/<did>")
def get_device(did):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    device = lk.get_device(did)
    lk.ensure_owner_device(device, role, user_id)
    return object_response(serialize(device))


@bp.post("/devices/<did>/remove")
def remove_device(did):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    device = lk.get_device(did)
    if device["status"] not in ("ACTIVE", "NEEDS_REPAIR"):
        raise ApiError("ERR_DEVICE_NOT_REMOVABLE", 409, "device is not removable")
    conn = lk.connection_of_device(device)
    svc.read_recompute(conn)
    if conn["compliance_posture"] == "SHUTOFF":
        raise ApiError("ERR_CONNECTION_SHUTOFF", 409, "connection is shut off")

    before = svc.begin(conn)
    device["status"] = "REMOVED"
    svc.touch(device)
    svc.finish(conn, before)
    return object_response(serialize(device))
