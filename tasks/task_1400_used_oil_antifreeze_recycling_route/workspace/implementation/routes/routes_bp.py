"""Route endpoints and stop creation (PRD §3.3)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_DRIVER_NO_HAZMAT,
    ERR_DRIVER_NOT_FOUND,
    ERR_DRIVER_SUSPENDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STOP_WINDOW,
    ERR_ROUTE_EMPTY,
    ERR_ROUTE_HAS_COMPLETED_STOPS,
    ERR_ROUTE_HAS_OPEN_STOPS,
    ERR_ROUTE_HAS_SUBMITTED_MANIFEST,
    ERR_ROUTE_NOT_CANCELLABLE,
    ERR_ROUTE_NOT_FOUND,
    ERR_ROUTE_NOT_PLANNED,
    ERR_STALE_VERSION,
    ERR_TANK_NOT_FOUND,
    ERR_TANK_SITE_NOT_FOUND,
)
from middleware import (
    get_body,
    req_date,
    req_enum,
    req_int,
    req_str,
    req_time_hhmm,
    require_roles,
)
from response import success_list, success_object
from services import cascades
from services.calc import route_posture

bp = Blueprint("routes", __name__)

DENSITY_ZONES = {"URBAN", "SUBURBAN", "RURAL"}
READ_ROLES = ("RoutePlanner", "SettlementClerk", "EHSOfficer", "Regulator", "Driver")
# Manifest states that are "SUBMITTED or beyond" for route-cancel purposes.
MANIFEST_BLOCKS_CANCEL = {
    "SUBMITTED", "IN_TRANSIT", "DELIVERED", "AMENDMENT_PENDING", "AMENDED", "CLOSED",
    "REJECTED_BY_FACILITY",
}
MANIFEST_ALLOWS_COMPLETE = {"SUBMITTED", "IN_TRANSIT", "DELIVERED", "AMENDED", "CLOSED"}


def get_route_or_404(route_id):
    route = db.get("routes", route_id)
    if route is None:
        raise ApiError(ERR_ROUTE_NOT_FOUND, "Route id not found", 404)
    return route


def serialize_route(route):
    out = db.serialize(route)
    out["posture"] = route_posture(route)
    return out


@bp.post("/routes")
@require_roles("RoutePlanner")
def create_route():
    body = get_body()
    route_code = req_str(body, "route_code")
    scheduled_date = req_date(body, "scheduled_date")
    driver_id = req_str(body, "driver_id")
    vehicle_capacity_gallons = req_int(body, "vehicle_capacity_gallons", minimum=1)
    density_zone = req_enum(body, "density_zone", DENSITY_ZONES)
    driver = db.get("drivers", driver_id)
    if driver is None:
        raise ApiError(ERR_DRIVER_NOT_FOUND, "Driver id not found", 404)
    for r in db.all_entities("routes"):
        if r["route_code"] == route_code and r["scheduled_date"] == scheduled_date:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "route_code must be unique per scheduled_date",
                400,
            )
    route = db.create_entity("routes", {
        "route_code": route_code,
        "scheduled_date": scheduled_date,
        "driver_id": driver_id,
        "vehicle_capacity_gallons": vehicle_capacity_gallons,
        "loaded_gallons": 0,
        "density_zone": density_zone,
        "status": "PLANNED",
        "_posture_override": False,
    })
    return success_object(serialize_route(route), 201)


@bp.get("/routes")
@require_roles(*READ_ROLES)
def list_routes():
    items = db.all_entities("routes")
    status = request.args.get("status")
    scheduled_date = request.args.get("scheduled_date")
    driver_id = request.args.get("driver_id")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if scheduled_date is not None:
        items = [r for r in items if r["scheduled_date"] == scheduled_date]
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    return success_list([serialize_route(r) for r in db.sorted_created(items)])


@bp.get("/routes/<routeId>")
@require_roles(*READ_ROLES)
def get_route(routeId):
    return success_object(serialize_route(get_route_or_404(routeId)))


@bp.post("/routes/<routeId>/dispatch")
@require_roles("RoutePlanner")
def dispatch_route(routeId):
    route = get_route_or_404(routeId)
    if route["status"] != "PLANNED":
        raise ApiError(ERR_ROUTE_NOT_PLANNED, "Dispatch requires PLANNED", 409)
    stops = cascades.stops_for_route(route["id"])
    if not any(s["status"] == "SCHEDULED" for s in stops):
        raise ApiError(ERR_ROUTE_EMPTY, "Dispatch requires at least one SCHEDULED stop", 409)
    driver = db.get("drivers", route["driver_id"])
    if driver is None:
        raise ApiError(ERR_DRIVER_NOT_FOUND, "Driver id not found", 404)
    if driver["status"] != "ACTIVE":
        raise ApiError(ERR_DRIVER_SUSPENDED, "Driver suspended", 409)
    active_stops = [
        s for s in stops
        if s["status"] not in ("CANCELLED_ROUTE", "CANCELLED_CUSTOMER", "CANCELLED_HALOGEN")
    ]
    needs_hazmat = False
    for s in active_stops:
        tank = db.get("tanks", s["tank_id"])
        if tank and tank["tank_kind"] == "MIXED":
            needs_hazmat = True
            break
    if needs_hazmat and not driver["hazmat_endorsement"]:
        raise ApiError(
            ERR_DRIVER_NO_HAZMAT,
            "Driver lacks hazmat endorsement required by MIXED tank on route",
            403,
        )
    route["status"] = "DISPATCHED"
    db.touch(route)
    return success_object(serialize_route(route))


@bp.post("/routes/<routeId>/complete")
@require_roles("RoutePlanner")
def complete_route(routeId):
    route = get_route_or_404(routeId)
    for stop in cascades.stops_for_route(route["id"]):
        if stop["status"] not in cascades.TERMINAL_STOP_STATES:
            raise ApiError(
                ERR_ROUTE_HAS_OPEN_STOPS,
                "Complete requires all stops terminal",
                409,
            )
    manifest = cascades.manifest_for_route(route["id"])
    if manifest is not None and manifest["status"] not in MANIFEST_ALLOWS_COMPLETE:
        raise ApiError(
            "ERR_MANIFEST_NOT_SUBMITTED",
            "Route complete requires manifest submitted (when manifest exists)",
            409,
        )
    route["status"] = "COMPLETE"
    db.touch(route)
    return success_object(serialize_route(route))


@bp.post("/routes/<routeId>/cancel")
@require_roles("RoutePlanner")
def cancel_route(routeId):
    route = get_route_or_404(routeId)
    if route["status"] not in ("PLANNED", "DISPATCHED"):
        raise ApiError(ERR_ROUTE_NOT_CANCELLABLE, "Cancel requires PLANNED or DISPATCHED", 409)
    manifest = cascades.manifest_for_route(route["id"])
    if route["status"] == "DISPATCHED":
        if any(s["status"] == "COMPLETED" for s in cascades.stops_for_route(route["id"])):
            raise ApiError(
                ERR_ROUTE_HAS_COMPLETED_STOPS,
                "Cancel requires zero COMPLETED stops when DISPATCHED",
                409,
            )
    if manifest is not None and manifest["status"] in MANIFEST_BLOCKS_CANCEL:
        raise ApiError(
            ERR_ROUTE_HAS_SUBMITTED_MANIFEST,
            "Cancel blocked by SUBMITTED-or-later manifest",
            409,
        )
    route["status"] = "CANCELLED"
    db.touch(route)
    for stop in cascades.stops_for_route(route["id"]):
        # PLANNED branch cancels SCHEDULED stops; DISPATCHED branch cancels
        # every non-terminal stop. SCHEDULED is non-terminal in both.
        if stop["status"] in cascades.NON_TERMINAL_STOP_STATES:
            stop["status"] = "CANCELLED_ROUTE"
            db.touch(stop)
    return success_object(serialize_route(route))


@bp.get("/routes/<routeId>/route-stops")
@require_roles(*READ_ROLES)
def list_route_stops(routeId):
    get_route_or_404(routeId)
    items = cascades.stops_for_route(routeId)
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return success_list([db.serialize(s) for s in db.sorted_created(items)])


@bp.get("/routes/<routeId>/manifest")
@require_roles(*READ_ROLES)
def get_route_manifest(routeId):
    get_route_or_404(routeId)
    manifest = cascades.manifest_for_route(routeId)
    items = [manifest] if manifest is not None else []
    return success_list([db.serialize(m) for m in items])


@bp.post("/routes/<routeId>/route-stops")
@require_roles("RoutePlanner")
def create_route_stop(routeId):
    route = get_route_or_404(routeId)
    body = get_body()
    tank_site_id = req_str(body, "tank_site_id")
    tank_id = req_str(body, "tank_id")
    window_start = req_time_hhmm(body, "scheduled_window_start")
    window_end = req_time_hhmm(body, "scheduled_window_end")
    sequence = req_int(body, "sequence", minimum=1)
    estimated_volume_gallons = req_int(body, "estimated_volume_gallons", minimum=0)
    expected_route_version = req_int(body, "expected_route_version")
    # Body FK existence (priority 4).
    if db.get("tank_sites", tank_site_id) is None:
        raise ApiError(ERR_TANK_SITE_NOT_FOUND, "TankSite id not found", 404)
    if db.get("tanks", tank_id) is None:
        raise ApiError(ERR_TANK_NOT_FOUND, "Tank id not found", 404)
    # OCC on Route.version (priority 6).
    if expected_route_version != route["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_route_version does not match the route's current version",
            412,
        )
    # Window / sequence structural constraints (priority 10).
    if window_end <= window_start:
        raise ApiError(
            ERR_INVALID_STOP_WINDOW,
            "scheduled_window_end must be after scheduled_window_start",
            400,
        )
    for s in cascades.stops_for_route(route["id"]):
        if s["sequence"] == sequence:
            raise ApiError(
                ERR_INVALID_STOP_WINDOW,
                "sequence must be unique within the route",
                400,
            )
    stop = db.create_entity("route_stops", {
        "route_id": route["id"],
        "tank_site_id": tank_site_id,
        "tank_id": tank_id,
        "scheduled_window_start": window_start,
        "scheduled_window_end": window_end,
        "sequence": sequence,
        "estimated_volume_gallons": estimated_volume_gallons,
        "status": "SCHEDULED",
        "_halogen_count_at_screen": None,
    })
    db.touch(route)
    return success_object(db.serialize(stop), 201)
