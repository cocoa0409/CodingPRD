from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE
from helpers import (auth, require_role, require_body, ok, v_str, v_int,
                     v_enum, ALL_ROLES)
from serializers import program_to_dict

bp = Blueprint("programs", __name__)

POSTING_POLICIES = ["HIGH_TO_LOW", "CHRONOLOGICAL"]


def get_program_or_404(pid):
    p = db.store["programs"].get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Program %s not found" % pid)
    return p


@bp.post("/v1/programs")
def create_program():
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    body = require_body()
    p = db.new_entity({
        "name": v_str(body, "name"),
        "fee_amount_cents": v_int(body, "fee_amount_cents", min_value=1),
        "daily_fee_cap_cents": v_int(body, "daily_fee_cap_cents", min_value=0),
        "max_daily_fees_count": v_int(body, "max_daily_fees_count", min_value=0),
        "de_minimis_threshold_cents": v_int(body, "de_minimis_threshold_cents", min_value=0),
        "sustained_overdraft_days_threshold": v_int(body, "sustained_overdraft_days_threshold", min_value=0),
        "sustained_overdraft_fee_cents": v_int(body, "sustained_overdraft_fee_cents", min_value=0),
        "charge_off_grace_business_days": v_int(body, "charge_off_grace_business_days", min_value=0),
        "notice_window_days": v_int(body, "notice_window_days", min_value=0),
        "steering_fee_count_threshold": v_int(body, "steering_fee_count_threshold", min_value=0),
        "steering_window_days": v_int(body, "steering_window_days", min_value=0),
        "offer_expiry_days": v_int(body, "offer_expiry_days", min_value=0),
        "posting_order_policy": v_enum(body, "posting_order_policy", POSTING_POLICIES),
        "current_disclosure_version": v_str(body, "current_disclosure_version"),
        "status": "ACTIVE",
    })
    db.store["programs"][p["id"]] = p
    return ok(program_to_dict(p), status=201)


@bp.get("/v1/programs/<pid>")
def get_program(pid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    p = get_program_or_404(pid)
    return ok(program_to_dict(p))


@bp.post("/v1/programs/<pid>/suspend")
def suspend_program(pid):
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    p = get_program_or_404(pid)
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE program can be suspended")
    p["status"] = "SUSPENDED"
    db.touch(p)
    return ok(program_to_dict(p))


@bp.post("/v1/programs/<pid>/resume")
def resume_program(pid):
    _, role = auth()
    require_role(role, ["ProgramAdmin"])
    p = get_program_or_404(pid)
    if p["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SUSPENDED program can be resumed")
    p["status"] = "ACTIVE"
    db.touch(p)
    return ok(program_to_dict(p))
