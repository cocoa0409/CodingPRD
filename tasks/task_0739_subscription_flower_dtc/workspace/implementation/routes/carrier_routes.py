"""Carrier routes: POST /carrier-routes, GET /carrier-routes/{id}, GET .../shipments."""
from flask import Blueprint, request

from common import new_common
from errors import ApiError, ERR_ROUTE_NOT_FOUND
from middleware import auth_required
import db
from response import created, ok, list_ok
from pagination import parse_pagination, apply_page
from services import validators as v
from services.views import route_view, shipment_view

bp = Blueprint("carrier_routes", __name__)


@bp.route("/carrier-routes", methods=["POST"])
@auth_required("PlatformAdmin")
def create_carrier_route():
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    zone = v.require_str(body, "zone")
    _dt, service_date_str = v.require_datetime(body, "service_date")
    r = {
        **new_common(),
        "zone": zone,
        "service_date": service_date_str,
    }
    db.carrier_routes[r["id"]] = r
    return created(route_view(r))


@bp.route("/carrier-routes/<rid>", methods=["GET"])
@auth_required("PlatformAdmin", "FulfillmentOps")
def get_carrier_route(rid):
    r = db.carrier_routes.get(rid)
    if r is None:
        raise ApiError(ERR_ROUTE_NOT_FOUND, "route not found", 404)
    return ok(route_view(r))


@bp.route("/carrier-routes/<rid>/shipments", methods=["GET"])
@auth_required("PlatformAdmin", "FulfillmentOps")
def list_route_shipments(rid):
    limit, offset = parse_pagination()
    r = db.carrier_routes.get(rid)
    if r is None:
        raise ApiError(ERR_ROUTE_NOT_FOUND, "route not found", 404)
    items = [sh for sh in db.shipments.values() if sh.get("route_id") == rid]
    items.sort(key=lambda sh: sh["created_at"])
    page, total = apply_page(items, limit, offset)
    return list_ok([shipment_view(sh) for sh in page], limit, offset, total)
