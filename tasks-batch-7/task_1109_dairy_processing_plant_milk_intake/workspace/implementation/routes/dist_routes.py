"""Distribution routes (PRD 3.8)."""
from flask import Blueprint

from db import STORE, base_record
from errors import not_found
from helpers import body, req_int, req_str
from middleware import require_roles
from response import success_object
from services import ser_route

bp = Blueprint("distribution_routes", __name__)


@bp.route("/dairy/distribution-routes", methods=["POST"])
def create_route():
    require_roles("PlantController")
    data = body()
    route_code = req_str(data, "route_code")
    destination_zip = req_str(data, "destination_zip")
    transit_days = req_int(data, "transit_days")
    min_days = req_int(data, "min_days_of_code_required")
    rec = base_record()
    rec.update({
        "route_code": route_code,
        "destination_zip": destination_zip,
        "transit_days": transit_days,
        "min_days_of_code_required": min_days,
        "status": "ACTIVE",
    })
    STORE["routes"][rec["id"]] = rec
    return success_object(ser_route(rec), 201)


@bp.route("/dairy/distribution-routes/<rid>", methods=["GET"])
def get_route(rid):
    require_roles("PlantController", "PasteurizerOperator")
    route = STORE["routes"].get(rid)
    if route is None:
        raise not_found("DistributionRoute not found")
    return success_object(ser_route(route))
