"""ChargeBay and ChargeSession endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at, now_iso
from middleware import require_role, get_auth
from response import success_object, success_list
from services.show import serialize_charge_bay, serialize_charge_session, touch

bp = Blueprint("charging", __name__)


# --------------------------------------------------------------------------
# ChargeBay

def _get_bay(bay_id):
    b = DB.charge_bays.get(bay_id)
    if b is None:
        raise errors.not_found("ERR_CHARGE_BAY_NOT_FOUND", "charge bay not found")
    return b


@bp.route("/api/charge-bays", methods=["POST"])
def create_charge_bay():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["site_id", "bay_code", "port_count"])
    site_id = body["site_id"]
    if not isinstance(site_id, str):
        raise errors.validation("site_id must be a string")
    bay_code = V.req_string(body, "bay_code")
    port_count = V.req_int(body, "port_count")
    if port_count < 1:
        raise errors.validation("port_count must be >= 1")
    require_role("FleetManager")

    site = DB.sites.get(site_id)
    if site is None:
        raise errors.not_found("ERR_SITE_NOT_FOUND", "site not found")

    # uniqueness within site (no dedicated error id in catalog; treat as validation)
    for bid in DB.insertion_order["charge_bays"]:
        b = DB.charge_bays[bid]
        if b["site_id"] == site_id and b["bay_code"] == bay_code:
            raise errors.validation("bay_code must be unique within the site")

    bid = new_id()
    ts = wall_created_at()
    bay = {
        "id": bid, "site_id": site_id, "bay_code": bay_code,
        "port_count": port_count,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.charge_bays[bid] = bay
    DB.insertion_order["charge_bays"].append(bid)
    return success_object(serialize_charge_bay(bay), 201)


@bp.route("/api/charge-bays/<chargeBayId>", methods=["GET"])
def get_charge_bay(chargeBayId):
    get_auth()
    return success_object(serialize_charge_bay(_get_bay(chargeBayId)))


@bp.route("/api/charge-bays", methods=["GET"])
def list_charge_bays():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    site_id = V.opt_string(request.args, "site_id")
    items = [DB.charge_bays[i] for i in DB.insertion_order["charge_bays"]]
    if site_id is not None:
        items = [b for b in items if b["site_id"] == site_id]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_charge_bay(b) for b in page], limit, offset, total)


# --------------------------------------------------------------------------
# ChargeSession

def _get_session(session_id):
    s = DB.charge_sessions.get(session_id)
    if s is None:
        raise errors.not_found("ERR_CHARGE_SESSION_NOT_FOUND", "charge session not found")
    return s


@bp.route("/api/charge-sessions", methods=["POST"])
def create_charge_session():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["drone_id", "charge_bay_id"])
    drone_id = body["drone_id"]
    bay_id = body["charge_bay_id"]
    if not isinstance(drone_id, str):
        raise errors.validation("drone_id must be a string")
    if not isinstance(bay_id, str):
        raise errors.validation("charge_bay_id must be a string")
    require_role("FleetManager")

    drone = DB.drones.get(drone_id)
    if drone is None:
        raise errors.not_found("ERR_DRONE_NOT_FOUND", "drone not found")
    bay = DB.charge_bays.get(bay_id)
    if bay is None:
        raise errors.not_found("ERR_CHARGE_BAY_NOT_FOUND", "charge bay not found")

    # state: drone must be AVAILABLE (one active session per drone)
    if drone["status"] != "AVAILABLE":
        raise errors.conflict("ERR_INVALID_STATE", "drone must be AVAILABLE to start charging")

    # capacity: bay ACTIVE sessions < port_count
    active = sum(1 for sid in DB.insertion_order["charge_sessions"]
                 if DB.charge_sessions[sid]["charge_bay_id"] == bay["id"]
                 and DB.charge_sessions[sid]["status"] == "ACTIVE")
    if active >= bay["port_count"]:
        raise errors.conflict("ERR_BAY_CAPACITY_EXCEEDED", "charge bay is at capacity")

    if drone["charge_pct"] >= 100:
        raise errors.conflict("ERR_CHARGE_NOT_NEEDED", "drone charge_pct is already 100")

    sid = new_id()
    ts = wall_created_at()
    session = {
        "id": sid, "drone_id": drone_id, "charge_bay_id": bay_id,
        "charge_from_pct": drone["charge_pct"],
        "charge_to_pct": None,
        "started_at": now_iso(),
        "ended_at": None,
        "status": "ACTIVE",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.charge_sessions[sid] = session
    DB.insertion_order["charge_sessions"].append(sid)
    drone["status"] = "CHARGING"
    touch(drone)
    return success_object(serialize_charge_session(session), 201)


@bp.route("/api/charge-sessions/<chargeSessionId>", methods=["GET"])
def get_charge_session(chargeSessionId):
    get_auth()
    return success_object(serialize_charge_session(_get_session(chargeSessionId)))


@bp.route("/api/charge-sessions", methods=["GET"])
def list_charge_sessions():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    drone_id = V.opt_string(request.args, "drone_id")
    bay_id = V.opt_string(request.args, "charge_bay_id")
    status = V.opt_string(request.args, "status")
    items = [DB.charge_sessions[i] for i in DB.insertion_order["charge_sessions"]]
    if drone_id is not None:
        items = [s for s in items if s["drone_id"] == drone_id]
    if bay_id is not None:
        items = [s for s in items if s["charge_bay_id"] == bay_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_charge_session(s) for s in page], limit, offset, total)


def _end_session(session, target, lower_inclusive):
    if session["status"] != "ACTIVE":
        raise errors.conflict("ERR_INVALID_STATE", "charge session must be ACTIVE")
    frm = session["charge_from_pct"]
    if lower_inclusive:
        ok = frm <= target <= 100
    else:
        ok = frm < target <= 100
    if not ok:
        raise errors.conflict("ERR_INVALID_CHARGE_TARGET", "charge_to_pct out of range")
    session["charge_to_pct"] = target
    session["ended_at"] = now_iso()
    session["status"] = "COMPLETED" if not lower_inclusive else "INTERRUPTED"
    touch(session)
    drone = DB.drones.get(session["drone_id"])
    if drone is not None:
        drone["charge_pct"] = target
        if drone["status"] == "CHARGING":
            drone["status"] = "AVAILABLE"
        touch(drone)
    return session


def _end_session_endpoint(chargeSessionId, lower_inclusive):
    # priority order: schema (0) -> auth (1) -> role (2) -> existence (3) -> state (5)
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["charge_to_pct"])
    target = V.req_int(body, "charge_to_pct")
    require_role("FleetManager")
    session = _get_session(chargeSessionId)
    session = _end_session(session, target, lower_inclusive)
    return success_object(serialize_charge_session(session))


@bp.route("/api/charge-sessions/<chargeSessionId>/complete", methods=["POST"])
def complete_session(chargeSessionId):
    return _end_session_endpoint(chargeSessionId, lower_inclusive=False)


@bp.route("/api/charge-sessions/<chargeSessionId>/interrupt", methods=["POST"])
def interrupt_session(chargeSessionId):
    return _end_session_endpoint(chargeSessionId, lower_inclusive=True)
