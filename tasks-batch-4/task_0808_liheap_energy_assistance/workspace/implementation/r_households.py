"""Household intake endpoints (§3.2)."""
from store import db, stamp_new, public
from common import (
    endpoint, object_response, get_body, req_int, req_str, req_enum, opt_bool,
)
from helpers import get_path, forbid

HEATING_SOURCES = {"ELECTRICITY", "NATURAL_GAS", "FUEL_OIL", "PROPANE"}


def register(app):
    @app.route("/liheap/households", methods=["POST"])
    @endpoint(["Caseworker", "ProgramAdmin"])
    def create_household(role, user_id):
        body = get_body()
        household = {
            "primary_applicant_name": req_str(body, "primary_applicant_name"),
            "household_size": req_int(body, "household_size", minimum=1),
            "annual_income_cents": req_int(body, "annual_income_cents", minimum=0),
            "state_code": req_str(body, "state_code"),
            "county": req_str(body, "county"),
            "has_elderly_or_disabled": opt_bool(body, "has_elderly_or_disabled", False),
            "has_child_under_6": opt_bool(body, "has_child_under_6", False),
            "heating_source": req_enum(body, "heating_source", HEATING_SOURCES),
        }
        stamp_new(household)
        db.households[household["id"]] = household
        return object_response(public(household), 201)

    @app.route("/liheap/households/<id_>", methods=["GET"])
    @endpoint(["Applicant", "Caseworker", "ProgramAdmin"])
    def get_household(role, user_id, id_):
        # Applicant may only read its own household (identity resource).
        if role == "Applicant" and id_ != user_id:
            forbid()
        household = get_path(db.households, id_)
        return object_response(public(household), 200)
