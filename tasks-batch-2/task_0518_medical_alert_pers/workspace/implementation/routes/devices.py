"""Device endpoints: register, enroll, tests (PRD 3.5)."""
from flask import Blueprint, request

from clock import clock
from db import store
from errors import err
from middleware import get_auth, require_role
from models import new_record, touch, serialize_device, serialize_device_test
from response import object_response, array_response
from services.lookup import (get_device, get_contract, devices_for_contract,
                             require_owner_subscriber)
from services.calculations import device_test_result, battery_health_class
from services.device_service import recompute_next_test_due, maybe_flag_needs_test
from util import (get_json_body, require_fields, require_enum, require_bool,
                  require_int_in_range, parse_pagination, paginate, sort_by_created)

bp = Blueprint("devices", __name__)

DEVICE_TYPES = {"PENDANT", "WRISTBAND", "MOBILE_GPS", "HOME_BASE"}
FALL_CAPABLE = {"PENDANT", "WRISTBAND", "MOBILE_GPS"}


@bp.route("/pers/devices", methods=["POST"])
def register_device():
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    body = get_json_body()
    require_fields(body, ["contract_id", "serial_number", "device_type"])
    contract = get_contract(body["contract_id"])
    # ownership: subscriber may only register under their own contract (priority 4)
    require_owner_subscriber(role, uid, contract["subscriber_id"])

    require_enum(body["device_type"], DEVICE_TYPES, "device_type")
    serial = body["serial_number"]
    if not isinstance(serial, str) or serial == "":
        raise err("ERR_INVALID_REQUEST", "serial_number must be a non-empty string")
    fall = body.get("fall_detection_enabled", False)
    if fall is None:
        fall = False
    require_bool(fall, "fall_detection_enabled")

    # serial unique across all devices (priority 16)
    for d in store.devices.values():
        if d["serial_number"] == serial:
            raise err("ERR_DUPLICATE", "serial_number already exists")

    r = new_record()
    r.update({
        "contract_id": body["contract_id"],
        "serial_number": serial,
        "device_type": body["device_type"],
        "fall_detection_enabled": fall,
        "status": "REGISTERED",
        "battery_pct": 100,
        "battery_health": battery_health_class(100),
        "last_test_at_dt": None,
        "next_test_due_at_dt": None,
        "open_alarm_count": 0,
    })
    store.devices[r["id"]] = r
    return object_response(serialize_device(r), 201)


@bp.route("/pers/devices/<did>", methods=["GET"])
def get_device_route(did):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "CallCenterAgent"})
    r = get_device(did)
    return object_response(serialize_device(r), 200)


@bp.route("/pers/devices", methods=["GET"])
def list_devices():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "CallCenterAgent"})
    limit, offset = parse_pagination()
    items = list(store.devices.values())
    if "contract_id" in request.args:
        items = [d for d in items if d["contract_id"] == request.args.get("contract_id")]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_device(d) for d in page], limit, offset, total)


@bp.route("/pers/devices/<did>/enroll", methods=["POST"])
def enroll_device(did):
    uid, role = get_auth()
    require_role(role, {"Subscriber"})
    d = get_device(did)
    contract = get_contract(d["contract_id"])
    require_owner_subscriber(role, uid, contract["subscriber_id"])
    # state (priority 5)
    if d["status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", "Device is not REGISTERED")
    # enroll preconditions (priority 14)
    has_pass = any(t["device_id"] == did and t["result"] == "PASS" for t in store.device_tests.values())
    if not has_pass:
        raise err("ERR_ENROLL_PRECONDITION", "No passing DeviceTest exists for this device")
    if d["fall_detection_enabled"] and d["device_type"] not in FALL_CAPABLE:
        raise err("ERR_ENROLL_PRECONDITION", "device_type cannot perform fall detection")

    d["status"] = "ENROLLED"
    touch(d)
    return object_response(serialize_device(d), 200)


@bp.route("/pers/devices/<did>/tests", methods=["POST"])
def submit_test(did):
    uid, role = get_auth()
    require_role(role, {"Subscriber"})
    d = get_device(did)
    contract = get_contract(d["contract_id"])
    require_owner_subscriber(role, uid, contract["subscriber_id"])
    body = get_json_body()
    require_fields(body, ["reported_battery_pct", "signal_ok"])
    pct = require_int_in_range(body["reported_battery_pct"], 0, 100, "reported_battery_pct")
    signal_ok = require_bool(body["signal_ok"], "signal_ok")

    # auto-flag NEEDS_TEST first if device ACTIVE and overdue (PRD 3.5)
    maybe_flag_needs_test(d)

    result = device_test_result(signal_ok, pct)

    # immutable DeviceTest record: only id + created_at (no version/updated_at)
    tr = new_record(with_common=False)
    tr.update({
        "device_id": did,
        "reported_battery_pct": pct,
        "signal_ok": signal_ok,
        "result": result,
        "tested_at_dt": clock.now(),
    })
    store.device_tests[tr["id"]] = tr

    # ALWAYS update battery_pct + battery_health (PRD 3.5), every test PASS or FAIL
    d["battery_pct"] = pct
    d["battery_health"] = battery_health_class(pct)

    # status/timing changes gated on PASS
    plan = store.monitoring_plans.get(contract["plan_id"])
    if result == "PASS":
        if d["status"] == "NEEDS_TEST":
            d["status"] = "ACTIVE"
        d["last_test_at_dt"] = clock.now()
        recompute_next_test_due(d, plan)

    touch(d)
    return object_response(serialize_device_test(tr), 201)


@bp.route("/pers/devices/<did>/tests", methods=["GET"])
def list_tests(did):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    get_device(did)
    items = sort_by_created([t for t in store.device_tests.values() if t["device_id"] == did])
    limit, offset = parse_pagination()
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_device_test(t) for t in page], limit, offset, total)
