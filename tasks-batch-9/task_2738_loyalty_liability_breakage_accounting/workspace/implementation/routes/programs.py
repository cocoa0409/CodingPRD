"""LoyaltyProgram endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import lookup
import serialize
from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT, ROLE_PROGRAM_ADMIN,
                  authorize)
from errors import ApiError
from response import created, ok, paginate
from validate import (field_code, field_enum, field_int, field_string,
                      field_tier_multiplier, json_body, tier_keys_valid)

bp = Blueprint("programs", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)
BREAKAGE_METHODS = ("COHORT_WEIGHTED", "PROGRAM_HISTORICAL")


@bp.route("/programs", methods=["POST"])
def create_program():
    authorize(ROLE_PROGRAM_ADMIN)
    body = json_body()
    name = field_string(body, "name", max_length=120)
    currency_code = field_code(body, "currency_code", 3, required=False, default="USD")
    ssp = field_int(body, "ssp_millicents_per_point", minimum=1, maximum=100000)
    expiry_days = field_int(body, "point_expiry_days", minimum=1, maximum=3650)
    cap = field_int(body, "per_issuance_point_cap", minimum=1)
    tiers = field_tier_multiplier(body, "tier_multiplier_bp")
    promo_cap = field_int(body, "promo_multiplier_cap_bp", required=False,
                          default=30000, minimum=10000, maximum=100000)
    method = field_enum(body, "breakage_method", BREAKAGE_METHODS,
                        required=False, default="COHORT_WEIGHTED")
    historical = field_int(body, "historical_redemption_rate_bp",
                           minimum=200, maximum=9800)
    threshold = field_int(body, "escheat_disclosure_threshold_cents",
                          required=False, default=100000, minimum=0)
    if not tier_keys_valid(tiers):
        raise ApiError("ERR_TIER_MULTIPLIER_KEYS_INVALID", 409)
    rec = db.new_record(db.store.programs, {
        "name": name,
        "currency_code": currency_code,
        "status": "DRAFT",
        "ssp_millicents_per_point": ssp,
        "point_expiry_days": expiry_days,
        "per_issuance_point_cap": cap,
        "tier_multiplier_bp": dict(tiers),
        "promo_multiplier_cap_bp": promo_cap,
        "breakage_method": method,
        "historical_redemption_rate_bp": historical,
        "escheat_disclosure_threshold_cents": threshold,
        "current_breakage_rate_bp": 0,
        "total_escheat_accrual_cents": 0,
        "escheat_disclosure_required": False,
    })
    return created(serialize.program(rec))


@bp.route("/programs", methods=["GET"])
def list_programs():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.programs), "status", "breakage_method")
    return paginate(rows, serialize.program)


@bp.route("/programs/<program_id>", methods=["GET"])
def read_program(program_id):
    authorize(*READ_ROLES)
    return ok(serialize.program(lookup.program(program_id)))


@bp.route("/programs/<program_id>/activate", methods=["POST"])
def activate_program(program_id):
    authorize(ROLE_PROGRAM_ADMIN)
    program = lookup.program(program_id)
    if program["status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if program["status"] == "DRAFT":
        has_rule = any(
            r["program_id"] == program_id
            for r in db.store.state_expiry_rules.values()
        )
        has_cohort = any(
            c["program_id"] == program_id for c in db.store.cohorts.values()
        )
        if not has_rule or not has_cohort:
            raise ApiError("ERR_PROGRAM_CONFIG_INCOMPLETE", 409)
        program["current_breakage_rate_bp"] = (
            10000 - program["historical_redemption_rate_bp"]
        )
    program["status"] = "ACTIVE"
    db.touch(program)
    return ok(serialize.program(program))


@bp.route("/programs/<program_id>/suspend", methods=["POST"])
def suspend_program(program_id):
    authorize(ROLE_PROGRAM_ADMIN)
    program = lookup.program(program_id)
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    program["status"] = "SUSPENDED"
    db.touch(program)
    return ok(serialize.program(program))


@bp.route("/programs/<program_id>/close", methods=["POST"])
def close_program(program_id):
    authorize(ROLE_PROGRAM_ADMIN)
    program = lookup.program(program_id)
    if program["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    for period in db.program_periods(program_id):
        if period["state"] != "HARD_CLOSED":
            raise ApiError("ERR_PERIODS_NOT_CLOSED", 409)
    program["status"] = "CLOSED"
    db.touch(program)
    return ok(serialize.program(program))
