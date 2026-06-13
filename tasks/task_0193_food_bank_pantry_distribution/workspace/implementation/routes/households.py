"""ClientHousehold endpoints: register, fetch, patch, certify."""
from flask import Blueprint

from db import db, now_iso
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_AGENCY_SCOPE_VIOLATION
from middleware import get_identity, require_role
from response import object_response
from services import models
from services.validate import (
    get_json_body,
    require_int,
    optional_int,
)
from routes.lookups import get_agency, get_household

bp = Blueprint("households", __name__)

READ_ROLES_ALL = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor", "AgencyCoordinator"}


@bp.post("/client-households")
def register_household():
    user_id, role = get_identity()
    require_role(role, {"AgencyCoordinator"})
    body = get_json_body()
    if "agency_id" not in body or not isinstance(body.get("agency_id"), str):
        raise err(ERR_INVALID_REQUEST, "Missing or invalid agency_id.")
    agency = get_agency(body["agency_id"])
    # scope ownership (priority 3)
    if agency["id"] != user_id:
        raise err(ERR_AGENCY_SCOPE_VIOLATION, "Household agency is not the caller's agency.")
    household_size = require_int(body, "household_size", minimum=1)
    monthly_income = require_int(body, "monthly_income_cents", non_negative=True)

    h = models._common_create()
    h.update(
        {
            "agency_id": agency["id"],
            "household_size": household_size,
            "monthly_income_cents": monthly_income,
            "tefap_eligible": False,
            "certification_status": "PENDING",
        }
    )
    models.recompute_tefap_eligible(h)
    db.client_households[h["id"]] = h
    return object_response(models.serialize_household(h), status=201)


@bp.get("/client-households/<household_id>")
def fetch_household(household_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_ALL)
    h = get_household(household_id)
    return object_response(models.serialize_household(h))


@bp.patch("/client-households/<household_id>")
def patch_household(household_id):
    user_id, role = get_identity()
    require_role(role, {"AgencyCoordinator"})
    h = get_household(household_id)
    # scope ownership (priority 3)
    if h["agency_id"] != user_id:
        raise err(ERR_AGENCY_SCOPE_VIOLATION, "Household is not the caller's agency's.")
    body = get_json_body()
    household_size = optional_int(body, "household_size", minimum=1, default=None)
    monthly_income = optional_int(body, "monthly_income_cents", non_negative=True, default=None)
    if household_size is not None:
        h["household_size"] = household_size
    if monthly_income is not None:
        h["monthly_income_cents"] = monthly_income
    models.recompute_tefap_eligible(h)
    models.touch(h)
    return object_response(models.serialize_household(h))


@bp.post("/client-households/<household_id>/certify")
def certify_household(household_id):
    user_id, role = get_identity()
    require_role(role, {"ComplianceAuditor"})
    h = get_household(household_id)
    if h["certification_status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Household is not PENDING.")
    if h["tefap_eligible"]:
        h["certification_status"] = "CERTIFIED"
        h["certified_at"] = models.current_clock_iso()
    else:
        h["certification_status"] = "DENIED"
    models.touch(h)
    return object_response(models.serialize_household(h))
