"""CrewRoute endpoints (PRD 3.10).

add-visit sequences a REQUESTED visit onto an OPEN route under the half-open
overlap rule: two windows conflict only if they actually overlap; touching at a
boundary is fine. Route completion cascades ROUTED visits to COMPLETED.
"""

from flask import Blueprint

from common import (
    get_json_body,
    paginate,
    require_fields,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_crew_route, get_service_visit
from middleware import get_auth, require_role
from response import success
from services.serialize import ser_crew_route, ser_service_visit

bp = Blueprint("crew_routes", __name__)

READ_ROLES = {"InstallTech", "OperationsAdmin"}


def _route_visit_count(route_id):
    """Count of visits on the route whose status is ROUTED or COMPLETED."""
    return sum(
        1
        for v in db.service_visits.values()
        if v.get("route_id") == route_id and v["status"] in {"ROUTED", "COMPLETED"}
    )


@bp.post("/crew-routes")
def create_crew_route():
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    body = get_json_body()
    require_fields(body, ["technician_id", "route_date"])
    technician_id = require_string(body, "technician_id")
    route_date = require_string(body, "route_date")

    record = stamp_new(
        {
            "technician_id": technician_id,
            "route_date": route_date,
            "visit_count": 0,
            "status": "OPEN",
        }
    )
    db.crew_routes[record["id"]] = record
    return success(ser_crew_route(record), status=201)


@bp.get("/crew-routes/<rid>")
def read_crew_route(rid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    r = get_crew_route(rid)
    return success(ser_crew_route(r), status=200)


@bp.get("/crew-routes/<rid>/visits")
def list_route_visits(rid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_crew_route(rid)
    items = [v for v in db.service_visits.values() if v.get("route_id") == rid]
    data, pagination = paginate(items, ser_service_visit)
    return success(data, status=200, pagination=pagination)


@bp.post("/crew-routes/<rid>/add-visit")
def add_visit(rid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    r = get_crew_route(rid)
    body = get_json_body()
    require_fields(body, ["visit_id"])
    visit_id = require_string(body, "visit_id")
    # Existence of body FK (priority 3).
    v = get_service_visit(visit_id)

    # State (6): route OPEN and visit REQUESTED.
    if r["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Route is not OPEN.")
    if v["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Visit is not REQUESTED.")
    # Route-date match.
    if v["visit_date"] != r["route_date"]:
        raise err(
            "ERR_ROUTE_DATE_MISMATCH",
            "Visit date does not match the route date.",
        )
    # Half-open overlap against already-ROUTED visits on this route.
    start, end = v["window_start_min"], v["window_end_min"]
    for other in db.service_visits.values():
        if other.get("route_id") == rid and other["status"] == "ROUTED":
            o_start, o_end = other["window_start_min"], other["window_end_min"]
            # [a,b) and [c,d) overlap iff a < d and c < b. Touching (b == c or
            # d == a) does NOT overlap.
            if start < o_end and o_start < end:
                raise err(
                    "ERR_VISIT_WINDOW_OVERLAP",
                    "Visit window overlaps an already-routed visit.",
                )

    v["route_id"] = rid
    v["status"] = "ROUTED"
    touch(v)
    # Recompute the route's visit_count.
    new_count = _route_visit_count(rid)
    if r.get("visit_count") != new_count:
        r["visit_count"] = new_count
        touch(r)
    return success(ser_service_visit(v), status=200)


@bp.post("/crew-routes/<rid>/dispatch")
def dispatch_route(rid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    r = get_crew_route(rid)
    if r["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Route is not OPEN.")
    has_routed = any(
        v.get("route_id") == rid and v["status"] == "ROUTED"
        for v in db.service_visits.values()
    )
    if not has_routed:
        raise err("ERR_INVALID_STATE", "Route has no routed visit to dispatch.")
    r["status"] = "DISPATCHED"
    touch(r)
    return success(ser_crew_route(r), status=200)


@bp.post("/crew-routes/<rid>/complete")
def complete_route(rid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    r = get_crew_route(rid)
    if r["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Route is not DISPATCHED.")
    r["status"] = "COMPLETED"
    touch(r)
    # Cascade: every ROUTED visit on the route -> COMPLETED.
    for v in db.service_visits.values():
        if v.get("route_id") == rid and v["status"] == "ROUTED":
            v["status"] = "COMPLETED"
            touch(v)
    new_count = _route_visit_count(rid)
    if r.get("visit_count") != new_count:
        r["visit_count"] = new_count
        touch(r)
    return success(ser_crew_route(r), status=200)
