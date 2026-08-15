"""Dealership routes: tenant root with warehouse capacity and labor defaults."""
from flask import Blueprint

from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import new_entity
from validate import body_dict, req_str, req_int, opt_int

bp = Blueprint("dealerships", __name__)


@bp.route("/api/dealerships", methods=["POST"])
def create_dealership():
    authorize(["DealerAdmin"])
    body = body_dict()
    name = req_str(body, "name")
    staging_capacity_units = req_int(body, "staging_capacity_units", minv=0)
    standard_labor_rate = req_int(body, "standard_labor_rate_cents_per_hour", minv=0)
    after_hours_start_minute = opt_int(body, "after_hours_start_minute", minv=0, maxv=1439)
    after_hours_multiplier_bp = opt_int(body, "after_hours_multiplier_bp", minv=0)
    turnover_buffer_minutes = opt_int(body, "turnover_buffer_minutes", minv=0)
    credit_cap_pct = opt_int(body, "credit_cap_pct", minv=0, maxv=100)
    dealership = new_entity("dealerships", {
        "name": name,
        "staging_capacity_units": staging_capacity_units,
        "standard_labor_rate_cents_per_hour": standard_labor_rate,
        "after_hours_start_minute": 1080 if after_hours_start_minute is None else after_hours_start_minute,
        "after_hours_multiplier_bp": 15000 if after_hours_multiplier_bp is None else after_hours_multiplier_bp,
        "turnover_buffer_minutes": 30 if turnover_buffer_minutes is None else turnover_buffer_minutes,
        "credit_cap_pct": 25 if credit_cap_pct is None else credit_cap_pct,
    })
    return success_object(public(dealership), status=201)


@bp.route("/api/dealerships", methods=["GET"])
def list_dealerships():
    authorize(ALL_ROLES)
    return list_response("dealerships", [])


@bp.route("/api/dealerships/<dealership_id>", methods=["GET"])
def get_dealership(dealership_id):
    authorize(ALL_ROLES)
    return get_response("dealerships", dealership_id)
