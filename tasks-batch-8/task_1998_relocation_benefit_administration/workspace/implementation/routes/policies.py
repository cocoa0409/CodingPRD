from flask import Blueprint, request

from db import DB
from errors import err_not_found, err_duplicate_resource
from middleware import get_actor, require_role
from response import success_object
from serializers import serialize_policy
from util import (
    require_fields, require_enum, require_int, require_number, require_bool,
)

bp = Blueprint("policies", __name__)

JOB_LEVELS = {"ASSOCIATE", "MANAGER", "DIRECTOR", "EXECUTIVE"}
MOVE_SCOPES = {"DOMESTIC", "INTERNATIONAL"}
HOME_OWNERSHIP = {"HOMEOWNER", "RENTER"}
GROSS_UP_METHODS = {"FLAT_SUPPLEMENTAL", "MARGINAL_AGGREGATE"}
LOSS_BASES = {"APPRAISED", "PURCHASE_PRICE"}

ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]

REQUIRED_FIELDS = [
    "job_level", "move_scope", "home_ownership",
    "hhg_cap_cents", "temp_housing_cap_cents", "temp_housing_max_nights",
    "travel_cap_cents", "loss_on_sale_cap_cents", "misc_cap_cents",
    "home_sale_eligible", "repayment_window_months",
    "gross_up_method", "flat_gross_up_rate",
    "marginal_bracket_threshold_cents", "marginal_rate_low", "marginal_rate_high",
    "loss_basis",
]


@bp.route("/policies", methods=["POST"])
def create_policy():
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, REQUIRED_FIELDS)
    job_level = require_enum(payload, "job_level", JOB_LEVELS)
    move_scope = require_enum(payload, "move_scope", MOVE_SCOPES)
    home_ownership = require_enum(payload, "home_ownership", HOME_OWNERSHIP)
    gross_up_method = require_enum(payload, "gross_up_method", GROSS_UP_METHODS)
    loss_basis = require_enum(payload, "loss_basis", LOSS_BASES)
    home_sale_eligible = require_bool(payload, "home_sale_eligible")

    hhg_cap = require_int(payload, "hhg_cap_cents")
    th_cap = require_int(payload, "temp_housing_cap_cents")
    th_max_nights = require_int(payload, "temp_housing_max_nights")
    travel_cap = require_int(payload, "travel_cap_cents")
    los_cap = require_int(payload, "loss_on_sale_cap_cents")
    misc_cap = require_int(payload, "misc_cap_cents")
    repay_window = require_int(payload, "repayment_window_months")
    flat_rate = require_number(payload, "flat_gross_up_rate")
    bracket_threshold = require_int(payload, "marginal_bracket_threshold_cents")
    rate_low = require_number(payload, "marginal_rate_low")
    rate_high = require_number(payload, "marginal_rate_high")

    with DB.lock:
        for p in DB.policies.values():
            if (
                p["job_level"] == job_level
                and p["move_scope"] == move_scope
                and p["home_ownership"] == home_ownership
            ):
                raise err_duplicate_resource(
                    "Policy tier already exists for this (job_level, move_scope, home_ownership)"
                )
        now = DB.now()
        p = {
            "id": DB.new_id(),
            "job_level": job_level,
            "move_scope": move_scope,
            "home_ownership": home_ownership,
            "hhg_cap_cents": hhg_cap,
            "temp_housing_cap_cents": th_cap,
            "temp_housing_max_nights": th_max_nights,
            "travel_cap_cents": travel_cap,
            "loss_on_sale_cap_cents": los_cap,
            "misc_cap_cents": misc_cap,
            "home_sale_eligible": home_sale_eligible,
            "repayment_window_months": repay_window,
            "gross_up_method": gross_up_method,
            "flat_gross_up_rate": flat_rate,
            "marginal_bracket_threshold_cents": bracket_threshold,
            "marginal_rate_low": rate_low,
            "marginal_rate_high": rate_high,
            "loss_basis": loss_basis,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": DB.next_seq(),
        }
        DB.policies[p["id"]] = p
        return success_object(serialize_policy(p), status=201)


@bp.route("/policies/<id>", methods=["GET"])
def get_policy(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        p = DB.policies.get(id)
        if p is None:
            raise err_not_found("Policy not found")
        return success_object(serialize_policy(p))
