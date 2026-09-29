"""POST /properties, GET /properties/{id}."""

from flask import Blueprint

import calculations as calc
from db import create
from errors import ApiError
from middleware import ALL_ROLES, authenticate, body, req_enum, req_str, opt_int, resolve
from response import entity_response

bp = Blueprint("properties", __name__)


@bp.post("/properties")
def create_property():
    authenticate(("ProjectCoordinator",))
    payload = body()
    street_address = req_str(payload, "street_address")
    state_code = req_enum(payload, "state_code", calc.STATE_CODES)
    county_code = req_str(payload, "county_code")
    homeowner_name = req_str(payload, "homeowner_name")
    homeowner_email = req_str(payload, "homeowner_email")
    insurance_carrier_code = req_str(payload, "insurance_carrier_code")
    first_party = opt_int(payload, "first_party_coverage_limit_cents", 2000000, minimum=0)
    third_party = opt_int(payload, "third_party_sublimit_cents", 5000000, minimum=0)

    prop = create("properties", {
        "street_address": street_address,
        "state_code": state_code,
        "county_code": county_code,
        "homeowner_name": homeowner_name,
        "homeowner_email": homeowner_email,
        "insurance_carrier_code": insurance_carrier_code,
        "first_party_coverage_limit_cents": first_party,
        "third_party_sublimit_cents": third_party,
        "trust_fund_deductible_cents": calc.STATE_DEDUCTIBLE_CENTS[state_code],
        "open_project_count": 0,
    })
    return entity_response(prop, 201)


@bp.get("/properties/<property_id>")
def read_property(property_id):
    user_id, role = authenticate(ALL_ROLES)
    # A Homeowner's X-User-ID *is* the Property id, so ownership is decidable
    # before resolution and therefore evaluated first (ladder rule 3 < rule 4).
    if role == "Homeowner" and user_id != property_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return entity_response(resolve("properties", property_id))
