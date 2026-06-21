"""SecuritySystem endpoints: register, read, list, patch telemetry, arm/disarm,
test-mode enter/exit."""
from flask import Blueprint, request

import clock
from db import db, new_id, new_common, touch
from errors import (
    err,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOT_ACCOUNT_OWNER,
    ERR_COMMUNICATOR_OFFLINE,
    ERR_CELLULAR_NOT_ENTITLED,
    ERR_TEST_MODE_ALREADY_OPEN,
)
from middleware import authenticate, require_role
from response import success, list_response
from services import validate, common, calc
from services.derive import serialize_system, system_health

bp = Blueprint("systems", __name__)

PATHS = {"BROADBAND", "CELLULAR"}
ARM_MODES = {"ARMED_STAY", "ARMED_AWAY"}


def _plan_for_system(system):
    account = db.accounts.get(system["account_id"])
    if account is None:
        return None
    return db.monitoring_plans.get(account["plan_id"])


def _ownership_check(caller, system):
    if caller.role == "Subscriber" and caller.user_id != system["account_id"]:
        raise err(ERR_NOT_ACCOUNT_OWNER, "Subscriber is not the owner of this system's account")


@bp.route("/systems", methods=["POST"])
def create_system():
    caller = authenticate()
    require_role(caller, {"Administrator"})
    body = validate.get_body()

    # FK presence + resolution
    account_id = validate.require_str(body, "account_id")
    if account_id not in db.accounts:
        raise err(ERR_REFERENCE_NOT_FOUND, "account_id does not resolve: %s" % account_id)

    primary_path = validate.require_enum(body, "primary_path", PATHS)
    cellular_signal_dbm = validate.require_int(body, "cellular_signal_dbm")
    backup_battery_pct = validate.require_int(body, "backup_battery_pct", minimum=0, maximum=100)
    last_checkin_minutes_ago = validate.require_int(body, "last_checkin_minutes_ago", minimum=0)

    # cellular entitlement (priority 9)
    if primary_path == "CELLULAR":
        account = db.accounts[account_id]
        plan = db.monitoring_plans.get(account["plan_id"])
        if plan is None or not plan["cellular_backup_included"]:
            raise err(ERR_CELLULAR_NOT_ENTITLED, "Plan does not include cellular backup")

    sid = new_id()
    system = {"id": sid}
    system.update(new_common())
    system.update({
        "account_id": account_id,
        "arming_state": "DISARMED",
        "test_mode": False,
        "test_mode_expires_utc": None,
        "primary_path": primary_path,
        "cellular_signal_dbm": cellular_signal_dbm,
        "backup_battery_pct": backup_battery_pct,
        "last_checkin_minutes_ago": last_checkin_minutes_ago,
    })
    db.systems[sid] = system
    return success(serialize_system(system), http_status=201)


@bp.route("/systems/<sid>", methods=["GET"])
def get_system(sid):
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    system = common.lookup(db.systems, sid)
    return success(serialize_system(system))


@bp.route("/systems", methods=["GET"])
def list_systems():
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    limit, offset = common.parse_pagination()
    account_id = request.args.get("account_id")
    items = list(db.systems.values())
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    items = common.sort_by_created(items)
    window, total = common.paginate(items, limit, offset)
    return list_response([serialize_system(s) for s in window], limit, offset, total)


@bp.route("/systems/<sid>", methods=["PATCH"])
def patch_system(sid):
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator"})
    system = common.lookup(db.systems, sid)
    body = validate.get_body()

    primary_path = validate.optional_enum(body, "primary_path", PATHS)
    cellular_signal_dbm = validate.optional_int(body, "cellular_signal_dbm")
    backup_battery_pct = validate.optional_int(body, "backup_battery_pct", minimum=0, maximum=100)
    last_checkin_minutes_ago = validate.optional_int(body, "last_checkin_minutes_ago", minimum=0)

    # Effective primary path after this patch
    effective_path = primary_path if primary_path is not None else system["primary_path"]
    if effective_path == "CELLULAR":
        plan = _plan_for_system(system)
        if plan is None or not plan["cellular_backup_included"]:
            raise err(ERR_CELLULAR_NOT_ENTITLED, "Plan does not include cellular backup")

    changed = False
    if primary_path is not None:
        system["primary_path"] = primary_path
        changed = True
    if cellular_signal_dbm is not None:
        system["cellular_signal_dbm"] = cellular_signal_dbm
        changed = True
    if backup_battery_pct is not None:
        system["backup_battery_pct"] = backup_battery_pct
        changed = True
    if last_checkin_minutes_ago is not None:
        system["last_checkin_minutes_ago"] = last_checkin_minutes_ago
        changed = True
    if changed:
        touch(system)
    return success(serialize_system(system))


@bp.route("/systems/<sid>/arm", methods=["POST"])
def arm_system(sid):
    caller = authenticate()
    require_role(caller, {"Subscriber"})
    system = common.lookup(db.systems, sid)
    _ownership_check(caller, system)
    body = validate.get_body()
    mode = validate.require_enum(body, "mode", ARM_MODES)

    # State: arm defined only from DISARMED (and re-arming to a different mode).
    # The arming_state cycles freely among DISARMED/ARMED_STAY/ARMED_AWAY while
    # the account is ACTIVE, so an arm from any state is accepted provided the
    # account is ACTIVE; the only state gate is contract status.
    account = db.accounts.get(system["account_id"])
    if account is None or account["contract_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Owning account is not ACTIVE")

    # business_safety (priority 8): communicator must not be OFFLINE
    if system_health(system) == "OFFLINE":
        raise err(ERR_COMMUNICATOR_OFFLINE, "Cannot arm a system whose communicator is OFFLINE")

    if system["test_mode"]:
        raise err(ERR_INVALID_STATE, "Cannot arm a system in test mode")

    system["arming_state"] = mode
    touch(system)
    return success(serialize_system(system))


@bp.route("/systems/<sid>/disarm", methods=["POST"])
def disarm_system(sid):
    caller = authenticate()
    require_role(caller, {"Subscriber"})
    system = common.lookup(db.systems, sid)
    _ownership_check(caller, system)

    if system["arming_state"] not in ("ARMED_STAY", "ARMED_AWAY"):
        raise err(ERR_INVALID_STATE, "System is not armed")

    system["arming_state"] = "DISARMED"
    touch(system)

    # Side effect: RECEIVED BURGLARY events on this system -> RESOLVED_FALSE
    for ev in db.alarm_events.values():
        if (
            ev["system_id"] == sid
            and ev["status"] == "RECEIVED"
            and ev["signal_type"] == "BURGLARY"
        ):
            ev["status"] = "RESOLVED_FALSE"
            ev["resolution"] = "FALSE_ALARM"
            touch(ev)
    return success(serialize_system(system))


@bp.route("/systems/<sid>/enter-test-mode", methods=["POST"])
def enter_test_mode(sid):
    caller = authenticate()
    require_role(caller, {"Subscriber", "MonitoringOperator"})
    system = common.lookup(db.systems, sid)

    account = db.accounts.get(system["account_id"])
    if account is None or account["contract_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Owning account is not ACTIVE")

    # business_temporal (priority 13): window overlap, half-open [enter, expires)
    now = clock.now()
    expires = system.get("test_mode_expires_utc")
    if system["test_mode"] and expires is not None and now < expires:
        raise err(ERR_TEST_MODE_ALREADY_OPEN, "A test-mode window is already open")

    system["test_mode"] = True
    system["test_mode_expires_utc"] = now + calc.test_mode_window()
    system["arming_state"] = "DISARMED"
    touch(system)
    return success(serialize_system(system))


@bp.route("/systems/<sid>/exit-test-mode", methods=["POST"])
def exit_test_mode(sid):
    caller = authenticate()
    require_role(caller, {"Subscriber", "MonitoringOperator"})
    system = common.lookup(db.systems, sid)

    system["test_mode"] = False
    system["test_mode_expires_utc"] = None
    touch(system)
    return success(serialize_system(system))
