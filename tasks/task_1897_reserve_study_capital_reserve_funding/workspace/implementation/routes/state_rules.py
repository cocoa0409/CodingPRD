"""StateReserveRule endpoints."""

from flask import request, Blueprint
from db import store
from middleware import require_roles
from response import success_object, success_list
from errors import make_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_STATE_RULE_EXISTS

bp = Blueprint("state_rules", __name__)

VALID_PLAN_TYPES = {"BASELINE", "THRESHOLD", "FULL"}


def serialize_rule(rule):
    return {
        "id": rule["id"],
        "created_at": rule["created_at"],
        "updated_at": rule["updated_at"],
        "version": rule["version"],
        "state_code": rule["state_code"],
        "min_percent_funded_pct": rule["min_percent_funded_pct"],
        "allowed_plan_types": rule["allowed_plan_types"],
        "site_visit_interval_years": rule["site_visit_interval_years"],
        "disclosure_deadline_days": rule["disclosure_deadline_days"],
        "annual_update_required": rule["annual_update_required"],
    }


@bp.route("/state-reserve-rules", methods=["POST"])
def create_state_rule():
    require_roles("PlatformAdmin")
    body = request.get_json(force=True, silent=True) or {}

    required = ["state_code", "min_percent_funded_pct", "allowed_plan_types",
                "site_visit_interval_years", "disclosure_deadline_days", "annual_update_required"]
    allowed = set(required)
    for field in required:
        if field not in body:
            raise make_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    for key in body:
        if key not in allowed:
            raise make_error(ERR_INVALID_REQUEST, f"Unknown field: {key}")

    state_code = body["state_code"]
    min_pct = body["min_percent_funded_pct"]
    allowed_types = body["allowed_plan_types"]
    site_visit_years = body["site_visit_interval_years"]
    disclosure_days = body["disclosure_deadline_days"]
    annual_update = body["annual_update_required"]

    # Validation
    if not isinstance(state_code, str) or len(state_code) != 2:
        raise make_error(ERR_INVALID_REQUEST, "state_code must be a two-letter string")
    if not isinstance(min_pct, (int, float)) or min_pct < 0 or min_pct > 100:
        raise make_error(ERR_INVALID_REQUEST, "min_percent_funded_pct must be between 0 and 100")
    if not isinstance(allowed_types, list) or len(allowed_types) == 0:
        raise make_error(ERR_INVALID_REQUEST, "allowed_plan_types must be a non-empty list")
    for t in allowed_types:
        if t not in VALID_PLAN_TYPES:
            raise make_error(ERR_INVALID_REQUEST, f"Invalid plan type: {t}")
    if not isinstance(site_visit_years, int) or site_visit_years < 1:
        raise make_error(ERR_INVALID_REQUEST, "site_visit_interval_years must be a positive integer")
    if not isinstance(disclosure_days, int) or disclosure_days < 0:
        raise make_error(ERR_INVALID_REQUEST, "disclosure_deadline_days must be a non-negative integer")
    if not isinstance(annual_update, bool):
        raise make_error(ERR_INVALID_REQUEST, "annual_update_required must be a boolean")

    # Uniqueness check
    for r in store.state_reserve_rules.values():
        if r["state_code"] == state_code:
            raise make_error(ERR_STATE_RULE_EXISTS, f"State rule for {state_code} already exists")

    rule = store.make_common_fields()
    rule.update({
        "state_code": state_code,
        "min_percent_funded_pct": min_pct,
        "allowed_plan_types": allowed_types,
        "site_visit_interval_years": site_visit_years,
        "disclosure_deadline_days": disclosure_days,
        "annual_update_required": annual_update,
    })
    store.state_reserve_rules[rule["id"]] = rule
    return success_object(serialize_rule(rule), 201)
