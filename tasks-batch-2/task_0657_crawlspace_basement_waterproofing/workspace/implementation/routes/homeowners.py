"""Homeowner endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import helpers
from middleware import authenticate, authorize, get_json_body
from response import object_response
from serializers import serialize
from services import factory

bp = Blueprint("homeowners", __name__)

CREDIT_BANDS = ["PRIME", "NEAR_PRIME", "SUBPRIME"]


@bp.route("/homeowners", methods=["POST"])
def create_homeowner():
    _uid, role = authenticate()
    authorize(role, ["Homeowner", "Estimator", "Scheduler", "WarrantyAdmin"])
    body = get_json_body()
    full_name = helpers.require_string(body, "full_name")
    email = helpers.require_string(body, "email")
    credit_band = helpers.require_enum(body, "credit_band", CREDIT_BANDS)
    entity = factory.create_homeowner(full_name, email, credit_band)
    return object_response(serialize(entity), status=201)


@bp.route("/homeowners/<homeowner_id>", methods=["GET"])
def get_homeowner(homeowner_id):
    _uid, role = authenticate()
    authorize(role, ["Homeowner", "Estimator", "WarrantyAdmin"])
    entity = helpers.find_or_404(db.homeowners, homeowner_id)
    return object_response(serialize(entity), status=200)
