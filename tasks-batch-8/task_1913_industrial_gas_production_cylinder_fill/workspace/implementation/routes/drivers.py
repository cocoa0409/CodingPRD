"""Driver and DeliveryRoute endpoints (PRD §3.7)."""
from flask import Blueprint

from constants import CDL_CLASSES, DRIVER_STATUSES, ENDORSEMENT_CLASSES, ROUTE_STATUSES
from db import store
from errors import (
    ERR_DRIVER_CERT_EXPIRED,
    ERR_DRIVER_NOT_QUALIFIED,
    ERR_DRIVER_ROUTE_OVERLAP,
    ERR_HAZMAT_ENDORSEMENT_MISSING,
    ERR_ROLE,
    ERR_ROUTE_INVALID_STATE,
    ApiError,
    bad_request,
    not_found,
)
from middleware import ANY_ROLE, get_body, locked, req_enum, req_int, req_list, req_str, require_roles
from response import success
from routes.listing import list_response
from services.ops import base_record, driver_out, route_out, unassign_driver_routes
from util import clock_date, parse_date, touch

bp = Blueprint("drivers", __name__)


def _parse_endorsements(body):
    raw = body.get("hazmat_endorsements")
    if raw is None or not isinstance(raw, list):
        bad_request("hazmat_endorsements must be an array")
    out = []
    for e in raw:
        if not isinstance(e, dict):
            bad_request("hazmat_endorsements entries must be objects")
        cls = e.get("endorsement_class")
        if not isinstance(cls, str) or cls not in ENDORSEMENT_CLASSES:
            from errors import bad_enum

            bad_enum("invalid endorsement_class")
        exp = parse_date(e.get("expiry_date"))
        if exp is None:
            bad_request("endorsement expiry_date must be an ISO date")
        out.append({"endorsement_class": cls, "expiry_date_d": exp})
    return out


def _certs_valid(driver, on_date):
    if driver["medical_card_expiry_d"] < on_date:
        return False
    for e in driver["hazmat_endorsements"]:
        if e["expiry_date_d"] < on_date:
            return False
    return True


@bp.post("/api/drivers")
@locked
def create_driver():
    require_roles("LogisticsCoordinator")
    body = get_body()
    name = req_str(body, "driver_name")
    cdl = req_enum(body, "cdl_class", CDL_CLASSES)
    endorsements = _parse_endorsements(body)
    medical = parse_date(body.get("medical_card_expiry"))
    if medical is None:
        bad_request("medical_card_expiry must be an ISO date")
    d = base_record()
    d.update(
        {
            "driver_name": name,
            "cdl_class": cdl,
            "hazmat_endorsements": endorsements,
            "medical_card_expiry_d": medical,
            "status": "QUALIFIED" if _certs_valid({"medical_card_expiry_d": medical, "hazmat_endorsements": endorsements}, clock_date()) else "CERT_EXPIRED",
        }
    )
    store.drivers[d["id"]] = d
    return success(driver_out(d), status=201)


@bp.get("/api/drivers")
@locked
def list_drivers():
    require_roles(*ANY_ROLE)
    return list_response(store.drivers.values(), driver_out, [("status", "status")])


@bp.get("/api/drivers/<driverId>")
@locked
def get_driver(driverId):
    require_roles(*ANY_ROLE)
    d = store.drivers.get(driverId)
    if d is None:
        not_found("driver not found")
    return success(driver_out(d))


@bp.patch("/api/drivers/<driverId>")
@locked
def patch_driver(driverId):
    require_roles("LogisticsCoordinator")
    body = get_body()
    medical = None
    if "medical_card_expiry" in body and body["medical_card_expiry"] is not None:
        medical = parse_date(body["medical_card_expiry"])
        if medical is None:
            bad_request("medical_card_expiry must be an ISO date")
    endorsements = None
    if "hazmat_endorsements" in body and body["hazmat_endorsements"] is not None:
        endorsements = _parse_endorsements(body)
    d = store.drivers.get(driverId)
    if d is None:
        not_found("driver not found")
    if medical is not None:
        d["medical_card_expiry_d"] = medical
    if endorsements is not None:
        d["hazmat_endorsements"] = endorsements
    touched = {d["id"]}
    if d["status"] == "QUALIFIED" and not _certs_valid(d, clock_date()):
        d["status"] = "CERT_EXPIRED"
        unassign_driver_routes(d["id"], touched)
    touch(d)
    return success(driver_out(d))


@bp.post("/api/drivers/<driverId>/set-status")
@locked
def driver_set_status(driverId):
    require_roles("LogisticsCoordinator")
    body = get_body()
    target = req_enum(body, "target_status", DRIVER_STATUSES)
    d = store.drivers.get(driverId)
    if d is None:
        not_found("driver not found")
    allowed = {
        "QUALIFIED": {"SUSPENDED"},
        "SUSPENDED": {"QUALIFIED"},
        "CERT_EXPIRED": {"QUALIFIED"},
    }
    if target not in allowed.get(d["status"], set()):
        bad_request("target_status unreachable from current driver status")
    touched = {d["id"]}
    if target == "SUSPENDED":
        d["status"] = "SUSPENDED"
        unassign_driver_routes(d["id"], touched)
    else:  # QUALIFIED reinstatement revalidates certs
        if not _certs_valid(d, clock_date()):
            raise ApiError(ERR_DRIVER_CERT_EXPIRED, 422, "driver certifications are expired")
        d["status"] = "QUALIFIED"
    touch(d)
    return success(driver_out(d))


# ---------------- delivery routes ----------------

@bp.post("/api/routes")
@locked
def create_route():
    require_roles("LogisticsCoordinator")
    body = get_body()
    route_date = parse_date(body.get("route_date"))
    if route_date is None:
        bad_request("route_date must be an ISO date")
    start = req_int(body, "window_start_hour")
    end = req_int(body, "window_end_hour")
    if start < 0 or start > 23:
        bad_request("window_start_hour must be in 0..23")
    if end < 1 or end > 24:
        bad_request("window_end_hour must be in 1..24")
    if end <= start:
        bad_request("window_end_hour must be > window_start_hour")
    stops = req_list(body, "stops")
    if not stops:
        bad_request("at least one stop is required")
    for s in stops:
        if not isinstance(s, dict) or not isinstance(s.get("stop_name"), str):
            bad_request("each stop needs a stop_name")
        classes = s.get("hazmat_classes")
        if not isinstance(classes, list):
            bad_request("each stop needs a hazmat_classes array")
        for cls in classes:
            if not isinstance(cls, str) or cls not in ENDORSEMENT_CLASSES:
                from errors import bad_enum

                bad_enum("invalid hazmat class in stops")
    r = base_record()
    r.update(
        {
            "route_date_d": route_date,
            "window_start_hour": start,
            "window_end_hour": end,
            "stops": [
                {"stop_name": s["stop_name"], "hazmat_classes": list(s["hazmat_classes"])} for s in stops
            ],
            "driver_id": None,
            "status": "PLANNED",
        }
    )
    store.routes[r["id"]] = r
    return success(route_out(r), status=201)


@bp.get("/api/routes")
@locked
def list_routes():
    require_roles(*ANY_ROLE)
    return list_response(
        store.routes.values(),
        route_out,
        [("driver_id", "driver_id"), ("status", "status"), ("route_date", "route_date")],
    )


def _route_date_key(route):
    from util import fmt_date

    return fmt_date(route["route_date_d"])


@bp.get("/api/routes/<routeId>")
@locked
def get_route(routeId):
    require_roles(*ANY_ROLE)
    r = store.routes.get(routeId)
    if r is None:
        not_found("route not found")
    return success(route_out(r))


@bp.post("/api/routes/<routeId>/assign-driver")
@locked
def assign_driver(routeId):
    require_roles("LogisticsCoordinator")
    body = get_body()
    driver_id = req_str(body, "driver_id")
    r = store.routes.get(routeId)
    if r is None:
        not_found("route not found")
    d = store.drivers.get(driver_id)
    if d is None:
        not_found("driver not found")
    if r["status"] != "PLANNED":
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409, "route must be PLANNED to assign a driver")
    if d["status"] != "QUALIFIED":
        raise ApiError(ERR_DRIVER_NOT_QUALIFIED, 409, "driver is not QUALIFIED")
    # hazmat coverage (route_hazmat_coverage)
    required = []
    for s in r["stops"]:
        for cls in s["hazmat_classes"]:
            if cls not in required:
                required.append(cls)
    for cls in required:
        holders = [e for e in d["hazmat_endorsements"] if e["endorsement_class"] == cls]
        if not holders:
            raise ApiError(ERR_HAZMAT_ENDORSEMENT_MISSING, 422, f"driver holds no {cls} endorsement")
        if all(e["expiry_date_d"] < r["route_date_d"] for e in holders):
            raise ApiError(ERR_DRIVER_CERT_EXPIRED, 422, f"{cls} endorsement expired before route_date")
    if d["medical_card_expiry_d"] < r["route_date_d"]:
        raise ApiError(ERR_DRIVER_CERT_EXPIRED, 422, "medical card expired before route_date")
    # window overlap: half-open [start, end); touching endpoints do not overlap
    for other in store.routes.values():
        if (
            other["id"] != r["id"]
            and other["driver_id"] == driver_id
            and other["status"] in ("DRIVER_ASSIGNED", "DISPATCHED")
            and other["route_date_d"] == r["route_date_d"]
            and r["window_start_hour"] < other["window_end_hour"]
            and other["window_start_hour"] < r["window_end_hour"]
        ):
            raise ApiError(ERR_DRIVER_ROUTE_OVERLAP, 409, "driver has an overlapping route window")
    r["driver_id"] = driver_id
    r["status"] = "DRIVER_ASSIGNED"
    touch(r)
    return success(route_out(r))


@bp.post("/api/routes/<routeId>/dispatch")
@locked
def dispatch_route(routeId):
    require_roles("LogisticsCoordinator")
    get_body()
    r = store.routes.get(routeId)
    if r is None:
        not_found("route not found")
    if r["status"] != "DRIVER_ASSIGNED":
        raise ApiError(ERR_ROUTE_INVALID_STATE, 409, "route must be DRIVER_ASSIGNED to dispatch")
    d = store.drivers.get(r["driver_id"])
    if d is None or d["status"] != "QUALIFIED" or d["medical_card_expiry_d"] < clock_date():
        raise ApiError(ERR_DRIVER_CERT_EXPIRED, 422, "driver certification no longer valid")
    r["status"] = "DISPATCHED"
    touch(r)
    return success(route_out(r))


@bp.post("/api/routes/<routeId>/set-status")
@locked
def route_set_status(routeId):
    uid, role = require_roles("LogisticsCoordinator", "Driver")
    body = get_body()
    target = req_enum(body, "target_status", ROUTE_STATUSES)
    r = store.routes.get(routeId)
    if r is None:
        not_found("route not found")
    if role == "Driver":
        # A Driver may only COMPLETE a route assigned to them; may never cancel.
        if target != "COMPLETED" or r["driver_id"] != uid:
            raise ApiError(ERR_ROLE, 403, "driver may only complete their own assigned route")
    if target == "COMPLETED":
        if r["status"] != "DISPATCHED":
            raise ApiError(ERR_ROUTE_INVALID_STATE, 409, "route must be DISPATCHED to complete")
        r["status"] = "COMPLETED"
    elif target == "CANCELLED":
        if r["status"] not in ("PLANNED", "DRIVER_ASSIGNED", "DISPATCHED"):
            raise ApiError(ERR_ROUTE_INVALID_STATE, 409, "route cannot be cancelled from its current state")
        r["status"] = "CANCELLED"
    else:
        bad_request("target_status not supported by set-status")
    touch(r)
    return success(route_out(r))
