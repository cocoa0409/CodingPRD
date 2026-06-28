"""Practice config root endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import errors
import response
import serialize
import validate
from middleware import authenticate, require_roles
from routes.helpers import get_or_404

bp = Blueprint("practices", __name__)


@bp.route("/practices", methods=["POST"])
def create_practice():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin"})
    data = validate.body()

    name = validate.require(data, "name", str)
    panel_target = validate.require(data, "panel_target", int)
    panel_hard_cap = validate.require(data, "panel_hard_cap", int)
    monthly_fee_cents = validate.require(data, "monthly_fee_cents", int)
    dpc_codes = validate.require(data, "dpc_covered_service_codes", list)

    annual_disc = validate.optional(data, "annual_fee_discount_pct", (int, float), 0.15)
    coins = validate.optional(data, "insurance_coinsurance_pct", (int, float), 0.20)
    late_fee = validate.optional(data, "late_fee_cents", int, 2500)
    grace = validate.optional(data, "grace_period_days", int, 14)

    # Numeric/business constraints -> ERR_VALIDATION (PRD §3.1).
    if panel_target <= 0:
        raise errors.validation("panel_target must be > 0.")
    if panel_hard_cap < panel_target:
        raise errors.validation("panel_hard_cap must be >= panel_target.")
    if monthly_fee_cents <= 0:
        raise errors.validation("monthly_fee_cents must be > 0.")
    if not (0 <= annual_disc < 1):
        raise errors.validation("annual_fee_discount_pct must be in [0, 1).")
    if not (0 <= coins < 1):
        raise errors.validation("insurance_coinsurance_pct must be in [0, 1).")
    if late_fee < 0:
        raise errors.validation("late_fee_cents must be >= 0.")
    if grace < 0:
        raise errors.validation("grace_period_days must be >= 0.")

    for code in dpc_codes:
        if not isinstance(code, str):
            raise errors.invalid_request("dpc_covered_service_codes must be strings.")

    e = dict(db.common_fields())
    e["id"] = db.new_id()
    e["_seq"] = db.next_seq()
    e["name"] = name
    e["panel_target"] = panel_target
    e["panel_hard_cap"] = panel_hard_cap
    e["monthly_fee_cents"] = monthly_fee_cents
    e["annual_fee_discount_pct"] = annual_disc
    e["dpc_covered_service_codes"] = list(dpc_codes)
    e["insurance_coinsurance_pct"] = coins
    e["late_fee_cents"] = late_fee
    e["grace_period_days"] = grace
    db.practices[e["id"]] = e
    return response.object_response(serialize.practice(e), 201)


@bp.route("/practices/<pid>", methods=["GET"])
def get_practice(pid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member", "Employer"})
    e = get_or_404("practice", pid)
    return response.object_response(serialize.practice(e), 200)
