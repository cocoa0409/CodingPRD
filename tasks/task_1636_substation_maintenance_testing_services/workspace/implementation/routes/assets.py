"""Asset endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    err_validation, err_not_found, err_policy_not_found, err_state_transition,
)
from services.common import (
    body, require_string, require_number, require_enum, optional_string,
    optional_number, optional_enum, parse_datetime_field, parse_pagination,
    paginate, get_substation, get_asset, get_policy_for_class,
)
from services.calculations import (
    compute_next_due_condition_adjusted, compute_next_due_baseline,
    compute_condition_score, refresh_asset_condition_and_due,
)

bp = Blueprint("assets", __name__)

ASSET_CLASSES = {"POWER_TRANSFORMER", "CIRCUIT_BREAKER", "RELAY"}
CRITICALITY_ENUM = {"HIGH", "MEDIUM", "LOW"}


def asset_view(a):
    return {
        "id": a["id"],
        "substation_id": a["substation_id"],
        "asset_class": a["asset_class"],
        "criticality": a["criticality"],
        "nameplate_mva": a.get("nameplate_mva"),
        "voltage_kv": a["voltage_kv"],
        "install_date": a["install_date"],
        "upstream_asset_id": a.get("upstream_asset_id"),
        "status": a["status"],
        "condition_score": a["condition_score"],
        "approved_outage_hours": a.get("approved_outage_hours", 0),
        "last_maintenance_completed_at": a.get("last_maintenance_completed_at"),
        "next_due_date": a.get("next_due_date"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/assets")
def create_asset():
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    payload = body()
    substation_id = require_string(payload, "substation_id")
    asset_class = require_enum(payload, "asset_class", ASSET_CLASSES)
    voltage_kv = require_number(payload, "voltage_kv")
    install_date_raw = parse_datetime_field(payload, "install_date", required=True)
    install_date = db._format_iso(install_date_raw)
    criticality = optional_enum(payload, "criticality", CRITICALITY_ENUM, "MEDIUM")
    nameplate_mva = optional_number(payload, "nameplate_mva")
    upstream_asset_id = optional_string(payload, "upstream_asset_id")
    last_maint_raw = parse_datetime_field(payload, "last_maintenance_completed_at", required=False)
    last_maintenance_completed_at = db._format_iso(last_maint_raw) if last_maint_raw else None

    # FK: substation_id must exist
    get_substation(substation_id)

    # upstream_asset_id must reference an existing RELAY asset
    if upstream_asset_id is not None:
        upstream = db.assets.get(upstream_asset_id)
        if upstream is None:
            raise err_not_found("upstream_asset_id does not resolve")
        if upstream["asset_class"] != "RELAY":
            raise err_validation("upstream_asset_id must reference a RELAY asset")

    # Policy must exist for this asset_class
    policy = get_policy_for_class(asset_class)
    if policy is None:
        raise err_policy_not_found()

    ent = {
        "id": db.new_id(),
        "substation_id": substation_id,
        "asset_class": asset_class,
        "criticality": criticality,
        "nameplate_mva": nameplate_mva,
        "voltage_kv": voltage_kv,
        "install_date": install_date,
        "upstream_asset_id": upstream_asset_id,
        "status": "IN_SERVICE",
        "condition_score": 100.00,
        "approved_outage_hours": 0,
        "last_maintenance_completed_at": last_maintenance_completed_at,
        "next_due_date": None,
    }
    db.stamp_new(ent)
    db.assets[ent["id"]] = ent
    # Compute next_due_date
    ent["next_due_date"] = compute_next_due_condition_adjusted(ent["id"])
    return success_object(asset_view(ent), status=201)


@bp.get("/assets")
def list_assets():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.assets.values())
    # Filters
    substation_id = request.args.get("substation_id")
    if substation_id:
        items = [a for a in items if a["substation_id"] == substation_id]
    asset_class = request.args.get("asset_class")
    if asset_class:
        items = [a for a in items if a["asset_class"] == asset_class]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    upstream_asset_id = request.args.get("upstream_asset_id")
    if upstream_asset_id:
        items = [a for a in items if a.get("upstream_asset_id") == upstream_asset_id]
    page, total = paginate(items, limit, offset)
    return success_list([asset_view(a) for a in page], limit, offset, total)


@bp.get("/assets/<id>")
def get_asset_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    a = get_asset(id)
    return success_object(asset_view(a))


@bp.get("/assets/<id>/forecast")
def get_asset_forecast(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    a = get_asset(id)
    policy = get_policy_for_class(a["asset_class"])
    condition_score = a.get("condition_score", 100.0)
    next_due_baseline = compute_next_due_baseline(id)
    next_due_adjusted = compute_next_due_condition_adjusted(id)
    escalation_active = False
    if policy:
        escalation_active = condition_score < policy["condition_escalation_threshold"]
    return success_object({
        "condition_score": condition_score,
        "next_due_interval_baseline": next_due_baseline,
        "next_due_condition_adjusted": next_due_adjusted,
        "escalation_active": escalation_active,
    })


@bp.post("/assets/<id>/decommission")
def decommission_asset(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    a = get_asset(id)
    if a["status"] != "IN_SERVICE":
        raise err_state_transition("Asset is not IN_SERVICE")
    # Check no non-terminal outage windows
    for w in db.outage_windows.values():
        if w["asset_id"] == id and w["status"] in ("REQUESTED", "APPROVED", "SWITCHING", "CLEARED"):
            raise err_state_transition("Asset has non-terminal outage windows")
    a["status"] = "DECOMMISSIONED"
    db.touch(a)
    return success_object(asset_view(a))
