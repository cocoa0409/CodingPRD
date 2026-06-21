"""RouteStop read endpoints (top-level reverse-reachability) (PRD 2.6)."""
from flask import Blueprint, request

from common import get_or_404, list_response
from db import db
from middleware import require_roles
from response import object_response
from services import serialize

bp = Blueprint("stops", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")


@bp.route("/operations/stops", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_stops():
    rows = list(db.stops.values())
    machine_id = request.args.get("machine_id")
    route_id = request.args.get("route_id")
    if machine_id is not None:
        rows = [s for s in rows if s["machine_id"] == machine_id]
    if route_id is not None:
        rows = [s for s in rows if s["route_id"] == route_id]
    return list_response(rows, serialize.stop)


@bp.route("/operations/stops/<stop_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_stop(stop_id):
    obj = get_or_404("stops", stop_id)
    return object_response(serialize.stop(obj))
