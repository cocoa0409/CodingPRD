"""ProgramChangeOrder endpoints (PRD §3.9)."""
from flask import Blueprint

import calc
import db
import lookup
import serialize
from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT, ROLE_PROGRAM_ADMIN,
                  authorize)
from errors import ApiError
from response import created, ok, paginate
from util import add_days, clamp, clock
from validate import (bad, field_datetime, field_enum, field_int, field_ref,
                      field_tier_multiplier, json_body, tier_keys_valid)

bp = Blueprint("change_orders", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)
CHANGE_TYPES = ("EXPIRY_DAYS_CHANGE", "SSP_CHANGE", "TIER_MULTIPLIER_CHANGE")
REQUIRED_FIELD = {
    "EXPIRY_DAYS_CHANGE": "new_point_expiry_days",
    "SSP_CHANGE": "new_ssp_millicents_per_point",
    "TIER_MULTIPLIER_CHANGE": "new_tier_multiplier_bp",
}


@bp.route("/program-change-orders", methods=["POST"])
def create_change_order():
    authorize(ROLE_PROGRAM_ADMIN)
    body = json_body()
    program_id = field_ref(body, "program_id")
    change_type = field_enum(body, "change_type", CHANGE_TYPES)
    new_expiry_days = field_int(body, "new_point_expiry_days", required=False,
                                minimum=1, maximum=3650)
    new_ssp = field_int(body, "new_ssp_millicents_per_point", required=False,
                        minimum=1, maximum=100000)
    new_tier = field_tier_multiplier(body, "new_tier_multiplier_bp",
                                     required=False)
    elasticity = field_int(body, "behavior_elasticity_bp", minimum=-5000,
                           maximum=5000)
    effective_at = field_datetime(body, "effective_at")
    supplied = {
        "new_point_expiry_days": new_expiry_days,
        "new_ssp_millicents_per_point": new_ssp,
        "new_tier_multiplier_bp": new_tier,
    }
    wanted = REQUIRED_FIELD[change_type]
    if supplied[wanted] is None:
        raise bad("%s is required for change_type %s." % (wanted, change_type))
    for name, value in supplied.items():
        if name != wanted and value is not None:
            raise bad("%s must be omitted for change_type %s." % (name, change_type))
    if effective_at < clock.now():
        raise bad("effective_at must not precede the current clock reading.")
    program = lookup.program(program_id)
    if new_tier is not None and not tier_keys_valid(new_tier):
        raise ApiError("ERR_TIER_MULTIPLIER_KEYS_INVALID", 409)
    projection = calc.change_order_projection(program, change_type, new_ssp,
                                              elasticity)
    fields = {
        "program_id": program["id"],
        "change_type": change_type,
        "new_point_expiry_days": new_expiry_days,
        "new_ssp_millicents_per_point": new_ssp,
        "new_tier_multiplier_bp": new_tier,
        "behavior_elasticity_bp": elasticity,
        "effective_at": effective_at,
        "state": "MODELED",
        "applied_at": None,
        "cancelled_by_order_id": None,
    }
    fields.update(projection)
    rec = db.new_record(db.store.change_orders, fields)
    return created(serialize.change_order(rec))


@bp.route("/program-change-orders", methods=["GET"])
def list_change_orders():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.change_orders), "program_id",
                           "change_type", "state", "cancelled_by_order_id")
    return paginate(rows, serialize.change_order)


@bp.route("/program-change-orders/<order_id>", methods=["GET"])
def read_change_order(order_id):
    authorize(*READ_ROLES)
    return ok(serialize.change_order(lookup.change_order(order_id)))


@bp.route("/program-change-orders/<order_id>/approve", methods=["POST"])
def approve_change_order(order_id):
    authorize(ROLE_CONTROLLER)
    order = lookup.change_order(order_id)
    program = lookup.program(order["program_id"])
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409)
    if order["state"] != "MODELED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    order["state"] = "APPROVED"
    db.touch(order)
    for competitor in db.rows(db.store.change_orders):
        if competitor["id"] == order["id"]:
            continue
        if competitor["program_id"] != program["id"]:
            continue
        if competitor["change_type"] != order["change_type"]:
            continue
        if competitor["state"] != "MODELED":
            continue
        competitor["state"] = "CANCELLED"
        competitor["cancelled_by_order_id"] = order["id"]
        db.touch(competitor)
    return ok(serialize.change_order(order))


@bp.route("/program-change-orders/<order_id>/apply", methods=["POST"])
def apply_change_order(order_id):
    authorize(ROLE_CONTROLLER)
    order = lookup.change_order(order_id)
    program = lookup.program(order["program_id"])
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409)
    if order["state"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    now = clock.now()
    if now < order["effective_at"]:
        raise ApiError("ERR_CHANGE_NOT_YET_EFFECTIVE", 409)
    change_type = order["change_type"]
    if change_type == "EXPIRY_DAYS_CHANGE":
        program["point_expiry_days"] = order["new_point_expiry_days"]
    elif change_type == "SSP_CHANGE":
        program["ssp_millicents_per_point"] = order["new_ssp_millicents_per_point"]
    else:
        program["tier_multiplier_bp"] = dict(order["new_tier_multiplier_bp"])
    db.touch(program)
    if change_type == "EXPIRY_DAYS_CHANGE":
        for lot in db.program_lots(program["id"]):
            if not calc.is_outstanding(lot):
                continue
            lot["expires_at"] = add_days(lot["issued_at"],
                                         program["point_expiry_days"])
            db.touch(lot)
    for cohort in db.cohort_order(db.program_cohorts(program["id"])):
        cohort["program_change_adjustment_bp"] = clamp(
            cohort["program_change_adjustment_bp"] + order["behavior_elasticity_bp"],
            -5000, 5000,
        )
        db.touch(cohort)
    order["state"] = "EFFECTIVE"
    order["applied_at"] = now
    db.touch(order)
    return ok(serialize.change_order(order))
