"""Rule config endpoints."""

from flask import Blueprint, request

from db import stores
from errors import raise_err, ERR_DUPLICATE_OUR_PLAN, ERR_STALE_VERSION, ERR_INVALID_REQUEST
from helpers import base_record, touch, get_or_404, body, req_str, req_int, req_enum, paginate
from middleware import require_roles
from response import success

bp = Blueprint("rule_configs", __name__)

PRIMACY_RULES = ("BIRTHDAY_RULE", "GENDER_RULE", "CUSTODIAL_DECREE")


@bp.route("/cob/rule-configs", methods=["POST"])
def create_config():
    require_roles("PlatformAdmin")
    data = body()
    config_name = req_str(data, "config_name")
    dep_rule = req_enum(data, "dependent_primacy_rule", PRIMACY_RULES)
    threshold = req_int(data, "msp_employer_size_threshold")
    esrd_months = req_int(data, "esrd_coordination_months")
    lookback = req_int(data, "retroactive_lookback_months")
    recovery_window = req_int(data, "recovery_window_days")
    period_length = req_int(data, "savings_period_length_days")

    current_active = None
    for c in stores["rule_configs"].values():
        if c.get("status") == "ACTIVE":
            current_active = c
            break

    # OCC: expected_active_config_version
    if "expected_active_config_version" in data and data["expected_active_config_version"] is not None:
        expected = data["expected_active_config_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise_err(ERR_INVALID_REQUEST, "expected_active_config_version must be an integer")
        if current_active is None or current_active["version"] != expected:
            raise_err(ERR_STALE_VERSION, "expected_active_config_version does not match current ACTIVE config version")

    # config_name unique among ACTIVE configs
    if current_active is not None and current_active["config_name"] == config_name:
        raise_err(ERR_DUPLICATE_OUR_PLAN, "config_name unique among ACTIVE configs")

    # Supersede prior ACTIVE
    if current_active is not None:
        current_active["status"] = "SUPERSEDED"
        touch(current_active)

    rec = base_record()
    rec.update({
        "config_name": config_name,
        "dependent_primacy_rule": dep_rule,
        "msp_employer_size_threshold": threshold,
        "esrd_coordination_months": esrd_months,
        "retroactive_lookback_months": lookback,
        "recovery_window_days": recovery_window,
        "savings_period_length_days": period_length,
        "status": "ACTIVE",
    })
    stores["rule_configs"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/rule-configs", methods=["GET"])
def list_configs():
    require_roles("PlatformAdmin", "COBAnalyst", "COBAuditor")
    status_filter = request.args.get("status")
    items = list(stores["rule_configs"].values())
    if status_filter:
        items = [c for c in items if c.get("status") == status_filter]
    return paginate(items)


@bp.route("/cob/rule-configs/<cid>", methods=["GET"])
def get_config(cid):
    require_roles("PlatformAdmin", "COBAnalyst", "COBAuditor")
    rec = get_or_404(stores["rule_configs"], cid, "rule config")
    return success(rec)
