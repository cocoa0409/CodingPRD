"""District endpoints: create (with pay-rule defaults), get, OCC update."""

from flask import Blueprint

import db
from db import STORE, new_entity, touch, public
from errors import raise_err, ERR_DISTRICT_NOT_FOUND, ERR_STALE_VERSION
from middleware import auth_context, require_role
from response import ok
from validate import body, req_str, opt_str, opt_int, opt_num, req_int

bp = Blueprint("districts", __name__)

INT_CONFIG = {
    "offer_response_window_minutes": 120,
    "long_term_approval_days": 5,
    "long_term_threshold_days": 10,
    "short_notice_hours": 24,
    "moderate_notice_hours": 72,
    "preference_rank_boost": 10,
    "reliability_window_days": 90,
    "suspension_score_threshold": 60,
    "suspension_min_completions": 5,
    "period_comp_rate_cents": 2500,
    "daily_period_cap": 8,
    "weekly_period_cap": 10,
}

NUM_CONFIG = {
    "long_term_rate_multiplier": 1.15,
    "htf_high_premium_pct": 0.20,
    "htf_moderate_premium_pct": 0.10,
    "short_notice_premium_pct": 0.25,
    "moderate_notice_premium_pct": 0.10,
    "premium_cap_multiplier": 1.50,
}


@bp.route("/districts", methods=["POST"])
def create_district():
    auth_context()
    data = body()
    name = req_str(data, "name")
    require_role(auth_context()[1], ["DistrictAdmin"])
    fields = {"name": name}
    for f, default in INT_CONFIG.items():
        fields[f] = opt_int(data, f, default)
    for f, default in NUM_CONFIG.items():
        fields[f] = opt_num(data, f, default)
    d = new_entity(STORE.districts, fields)
    return ok(public(d), status=201)


@bp.route("/districts/<did>", methods=["GET"])
def get_district(did):
    _, role = auth_context()
    require_role(role, ["DistrictAdmin", "SchoolCoordinator", "Teacher", "Substitute", "PayrollClerk"])
    d = STORE.districts.get(did)
    if d is None:
        raise_err(ERR_DISTRICT_NOT_FOUND, "district id does not exist")
    return ok(public(d))


@bp.route("/districts/<did>", methods=["PUT"])
def update_district(did):
    auth_context()
    data = body()
    expected = req_int(data, "expected_district_version")
    name = opt_str(data, "name")
    updates = {}
    for f in INT_CONFIG:
        v = opt_int(data, f)
        if v is not None:
            updates[f] = v
    for f in NUM_CONFIG:
        v = opt_num(data, f)
        if v is not None:
            updates[f] = v
    require_role(auth_context()[1], ["DistrictAdmin"])
    d = STORE.districts.get(did)
    if d is None:
        raise_err(ERR_DISTRICT_NOT_FOUND, "district id does not exist")
    if expected != d["version"]:
        raise_err(ERR_STALE_VERSION, "expected_district_version does not match the current version")
    if name is not None:
        d["name"] = name
    for f, v in updates.items():
        d[f] = v
    touch(d)
    return ok(public(d))
