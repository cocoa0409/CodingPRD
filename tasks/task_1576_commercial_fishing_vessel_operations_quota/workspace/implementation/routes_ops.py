"""Routes: gear assets/events, VMS pings, compliance violations."""

from flask import Blueprint, request

from errors import ApiError
import store
from common import (
    auth,
    body,
    f_dt,
    f_enum,
    f_int,
    f_number,
    f_str,
    get_gear_asset,
    get_trip,
    get_vessel,
    get_violation,
    list_response,
    make_entity,
    make_event,
    not_owner,
    ok_object,
    pub,
    require_roles,
    touch,
)
import domain
from store import iso

bp = Blueprint("ops", __name__)

OWNER = ["VesselOwner"]
CAPTAIN = ["Captain"]
GEAR_WRITERS = ["VesselOwner", "Captain"]
REGULATOR = ["FisheriesRegulator"]
GEAR_EVENT_TYPES = ["LOSS", "REPAIR", "MAINTENANCE_START", "MAINTENANCE_END"]


# ---------------------------------------------------------------------------
# Gear assets and events
# ---------------------------------------------------------------------------

@bp.route("/vessels/<rid>/gear-assets", methods=["POST"])
def create_gear_asset(rid):
    uid, role = auth()
    require_roles(role, OWNER)
    if uid != rid:
        not_owner("X-User-ID must equal the vessel id")
    vessel = get_vessel(rid)
    payload = body()
    gear_type = f_enum(payload, "gear_type", domain.GEAR_TYPES)
    units_total = f_int(payload, "units_total")
    if units_total <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "units_total must be > 0")
    asset = make_entity(
        {
            "vessel_id": vessel["id"],
            "gear_type": gear_type,
            "units_total": units_total,
            "units_lost": 0,
            "units_in_maintenance": 0,
            "units_operational": units_total,
            "status": "OPERATIONAL",
        }
    )
    store.db.gear_assets[asset["id"]] = asset
    return ok_object(pub(asset), 201)


@bp.route("/vessels/<rid>/gear-assets", methods=["GET"])
def list_gear_assets(rid):
    auth()
    get_vessel(rid)
    items = [a for a in store.db.gear_assets.values() if a["vessel_id"] == rid]
    return list_response(items, [("gear_type", request.args.get("gear_type"))])


@bp.route("/gear-assets/<rid>", methods=["GET"])
def get_one_gear_asset(rid):
    auth()
    return ok_object(pub(get_gear_asset(rid)))


@bp.route("/gear-assets/<rid>/events", methods=["POST"])
def create_gear_event(rid):
    uid, role = auth()
    require_roles(role, GEAR_WRITERS)
    asset = get_gear_asset(rid)
    if uid != asset["vessel_id"]:
        not_owner("X-User-ID must equal the gear asset's vessel id")
    payload = body()
    event_type = f_enum(payload, "event_type", GEAR_EVENT_TYPES)
    units = f_int(payload, "units")
    if units <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "units must be > 0")
    occurred_at = f_dt(payload, "occurred_at")
    trip_id = payload.get("trip_id")
    if trip_id is not None:
        if not isinstance(trip_id, str):
            raise ApiError(400, "ERR_INVALID_REQUEST", "trip_id must be a string")
        get_trip(trip_id)  # 404 when referenced trip does not exist
    event = make_event(
        {
            "gear_asset_id": asset["id"],
            "trip_id": trip_id,
            "event_type": event_type,
            "units": units,
            "occurred_at": iso(occurred_at),
        }
    )
    # Legality is evaluated over the full replay including the new event.
    domain.check_gear_event_legal(asset, event)
    store.db.gear_events[event["id"]] = event
    domain.apply_gear_projection(asset)
    return ok_object(pub(event), 201)


@bp.route("/gear-assets/<rid>/events", methods=["GET"])
def list_gear_events(rid):
    auth()
    get_gear_asset(rid)
    items = [e for e in store.db.gear_events.values() if e["gear_asset_id"] == rid]
    return list_response(items)


@bp.route("/fishing-trips/<rid>/gear-events", methods=["GET"])
def list_trip_gear_events(rid):
    auth()
    get_trip(rid)
    items = [e for e in store.db.gear_events.values() if e.get("trip_id") == rid]
    return list_response(items)


# ---------------------------------------------------------------------------
# VMS pings (append-only)
# ---------------------------------------------------------------------------

@bp.route("/vessels/<rid>/vms-pings", methods=["POST"])
def create_vms_ping(rid):
    uid, role = auth()
    require_roles(role, CAPTAIN)
    if uid != rid:
        not_owner("X-User-ID must equal the vessel id")
    vessel = get_vessel(rid)
    payload = body()
    recorded_at = f_dt(payload, "recorded_at")
    latitude = f_number(payload, "latitude")
    longitude = f_number(payload, "longitude")
    ping = make_event(
        {
            "vessel_id": vessel["id"],
            "recorded_at": iso(recorded_at),
            "latitude": latitude,
            "longitude": longitude,
        }
    )
    store.db.vms_pings[ping["id"]] = ping
    return ok_object(pub(ping), 201)


@bp.route("/vessels/<rid>/vms-pings", methods=["GET"])
def list_vms_pings(rid):
    auth()
    get_vessel(rid)
    items = [p for p in store.db.vms_pings.values() if p["vessel_id"] == rid]
    return list_response(items)


# ---------------------------------------------------------------------------
# Compliance violations
# ---------------------------------------------------------------------------

@bp.route("/violations", methods=["POST"])
def create_violation():
    _, role = auth()
    require_roles(role, REGULATOR)
    payload = body()
    vessel = get_vessel(f_str(payload, "vessel_id"))
    violation_type = f_enum(payload, "violation_type", domain.VIOLATION_TYPES)
    details = payload.get("details")
    if not isinstance(details, str):
        raise ApiError(400, "ERR_INVALID_REQUEST", "details must be a string")
    trip_id = payload.get("trip_id")
    if trip_id is not None:
        if not isinstance(trip_id, str):
            raise ApiError(400, "ERR_INVALID_REQUEST", "trip_id must be a string")
        get_trip(trip_id)
    violation = domain.create_violation(vessel["id"], violation_type, details, trip_id)
    return ok_object(pub(violation), 201)


@bp.route("/violations", methods=["GET"])
def list_violations():
    auth()
    return list_response(
        store.db.violations.values(),
        [
            ("vessel_id", request.args.get("vessel_id")),
            ("trip_id", request.args.get("trip_id")),
            ("status", request.args.get("status")),
        ],
    )


@bp.route("/violations/<rid>", methods=["GET"])
def get_one_violation(rid):
    auth()
    return ok_object(pub(get_violation(rid)))


@bp.route("/violations/<rid>/adjudicate", methods=["POST"])
def adjudicate_violation(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    violation = get_violation(rid)
    if violation["status"] != "OPEN":
        raise ApiError(409, "ERR_VIOLATION_NOT_OPEN", "adjudicate requires OPEN")
    vessel = get_vessel(violation["vessel_id"])
    severity = domain.penalty_points(violation, vessel)
    violation["severity_points"] = severity
    violation["status"] = "ADJUDICATED"
    touch(violation)
    vessel["compliance_points"] -= severity
    touch(vessel)
    if vessel["compliance_points"] < domain.SUSPENSION_THRESHOLD:
        domain.suspend_vessel_cascade(vessel)
    return ok_object(pub(violation))


@bp.route("/violations/<rid>/dismiss", methods=["POST"])
def dismiss_violation(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    violation = get_violation(rid)
    if violation["status"] != "OPEN":
        raise ApiError(409, "ERR_VIOLATION_NOT_OPEN", "dismiss requires OPEN")
    violation["status"] = "DISMISSED"
    touch(violation)
    return ok_object(pub(violation))


@bp.route("/violations/<rid>/appeal", methods=["POST"])
def appeal_violation(rid):
    uid, role = auth()
    require_roles(role, OWNER)
    violation = get_violation(rid)
    if uid != violation["vessel_id"]:
        not_owner("X-User-ID must equal the violation's vessel id")
    if violation["status"] != "ADJUDICATED":
        raise ApiError(
            409, "ERR_VIOLATION_NOT_ADJUDICATED", "appeal requires ADJUDICATED"
        )
    violation["status"] = "APPEALED"
    touch(violation)
    return ok_object(pub(violation))


@bp.route("/violations/<rid>/reverse", methods=["POST"])
def reverse_violation(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    violation = get_violation(rid)
    if violation["status"] != "APPEALED":
        raise ApiError(409, "ERR_VIOLATION_NOT_APPEALED", "reverse requires APPEALED")
    violation["status"] = "REVERSED"
    touch(violation)
    vessel = get_vessel(violation["vessel_id"])
    vessel["compliance_points"] += violation["severity_points"]
    touch(vessel)
    # Suspension is deliberately NOT auto-lifted; reinstate is manual.
    return ok_object(pub(violation))


@bp.route("/violations/<rid>/uphold", methods=["POST"])
def uphold_violation(rid):
    _, role = auth()
    require_roles(role, REGULATOR)
    violation = get_violation(rid)
    if violation["status"] != "APPEALED":
        raise ApiError(409, "ERR_VIOLATION_NOT_APPEALED", "uphold requires APPEALED")
    violation["status"] = "UPHELD"
    touch(violation)
    return ok_object(pub(violation))
