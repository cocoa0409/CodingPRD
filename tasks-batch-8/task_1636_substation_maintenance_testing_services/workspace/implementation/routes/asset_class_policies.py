"""AssetClassPolicy endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import err_duplicate_key
from services.common import (
    body, require_string, require_number, require_int, require_enum,
    parse_pagination, paginate,
)

bp = Blueprint("asset_class_policies", __name__)

ASSET_CLASSES = {"POWER_TRANSFORMER", "CIRCUIT_BREAKER", "RELAY"}


def policy_view(p):
    return {
        "id": p["id"],
        "asset_class": p["asset_class"],
        "interval_months": p["interval_months"],
        "condition_escalation_threshold": p["condition_escalation_threshold"],
        "condition_critical_threshold": p["condition_critical_threshold"],
        "oil_warn_ppm": p["oil_warn_ppm"],
        "oil_critical_ppm": p["oil_critical_ppm"],
        "ir_min_mohm": p["ir_min_mohm"],
        "relay_timing_warn_pct": p["relay_timing_warn_pct"],
        "relay_timing_fail_pct": p["relay_timing_fail_pct"],
        "w_insulation": p["w_insulation"],
        "w_oil": p["w_oil"],
        "w_relay": p["w_relay"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/asset-class-policies")
def create_policy():
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    payload = body()
    asset_class = require_enum(payload, "asset_class", ASSET_CLASSES)
    interval_months = require_int(payload, "interval_months")
    if interval_months <= 0:
        from errors import err_validation
        raise err_validation("interval_months must be > 0")
    condition_escalation_threshold = require_number(payload, "condition_escalation_threshold")
    condition_critical_threshold = require_number(payload, "condition_critical_threshold")
    oil_warn_ppm = require_number(payload, "oil_warn_ppm")
    oil_critical_ppm = require_number(payload, "oil_critical_ppm")
    ir_min_mohm = require_number(payload, "ir_min_mohm")
    relay_timing_warn_pct = require_number(payload, "relay_timing_warn_pct")
    relay_timing_fail_pct = require_number(payload, "relay_timing_fail_pct")
    w_insulation = require_number(payload, "w_insulation")
    w_oil = require_number(payload, "w_oil")
    w_relay = require_number(payload, "w_relay")
    # Uniqueness: asset_class
    for p in db.asset_class_policies.values():
        if p["asset_class"] == asset_class:
            raise err_duplicate_key("asset_class policy already exists")
    ent = {
        "id": db.new_id(),
        "asset_class": asset_class,
        "interval_months": interval_months,
        "condition_escalation_threshold": condition_escalation_threshold,
        "condition_critical_threshold": condition_critical_threshold,
        "oil_warn_ppm": oil_warn_ppm,
        "oil_critical_ppm": oil_critical_ppm,
        "ir_min_mohm": ir_min_mohm,
        "relay_timing_warn_pct": relay_timing_warn_pct,
        "relay_timing_fail_pct": relay_timing_fail_pct,
        "w_insulation": w_insulation,
        "w_oil": w_oil,
        "w_relay": w_relay,
    }
    db.stamp_new(ent)
    db.asset_class_policies[ent["id"]] = ent
    return success_object(policy_view(ent), status=201)


@bp.get("/asset-class-policies")
def list_policies():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.asset_class_policies.values())
    asset_class = request.args.get("asset_class")
    if asset_class:
        items = [p for p in items if p["asset_class"] == asset_class]
    page, total = paginate(items, limit, offset)
    return success_list([policy_view(p) for p in page], limit, offset, total)
