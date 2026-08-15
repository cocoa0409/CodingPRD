"""Asset register (PRD §3.1) and operational-state actions."""
from flask import Blueprint, request

import errors as E
from errors import ApiError
from db import store, new_common_fields, touch, parse_dt
from middleware import auth, require_role, body, v_str, v_int, v_enum, paginate
from response import ok_object, ok_list
from services.core import (get_unit, get_asset, property_of_unit,
                           property_of_asset, require_active_property,
                           OPEN_WO_STATES)
from services.compliance import compute_compliance_status
from services.serializers import asset_view

bp = Blueprint("assets", __name__)

PM = ("PropertyManager",)
ALL = ("PropertyManager", "Technician", "ComplianceAuditor")
COMPONENT_TYPES = ("HVAC", "WATER_HEATER", "APPLIANCE")


def _asset_property_id(a):
    prop = property_of_asset(a)
    return prop["id"] if prop else None


@bp.route("/pm/assets", methods=["POST"])
def create_asset():
    _, role = auth()
    require_role(role, PM)
    data = body()
    # Stage 3/4: unit reference.
    unit = None
    if data.get("unit_id") is not None:
        unit = get_unit(data["unit_id"])
        require_active_property(property_of_unit(unit))
    # Stage 15: field shape, declared input order.
    uid = v_str(data, "unit_id")
    ctype = v_enum(data, "component_type", COMPONENT_TYPES)
    installed_raw = v_str(data, "installed_on")
    warranty = v_int(data, "warranty_months", minv=0)
    life = v_int(data, "expected_life_months", minv=1)
    cost = v_int(data, "replacement_cost_cents", minv=1)
    if life < warranty:
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "expected_life_months must be >= warranty_months")
    try:
        installed_dt, _ = parse_dt(installed_raw)
    except ValueError:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "installed_on is not a valid ISO 8601 date")
    if unit is None:
        unit = get_unit(uid)
        require_active_property(property_of_unit(unit))
    rec = new_common_fields()
    rec.update({
        "unit_id": unit["id"],
        "component_type": ctype,
        "installed_on": installed_raw,
        "_installed_dt": installed_dt.date(),
        "warranty_months": warranty,
        "expected_life_months": life,
        "replacement_cost_cents": cost,
        "condition_score": None,
        "operational_status": "IN_SERVICE",
        "compliance_status": "COMPLIANT",
        "superseded_by_asset_id": None,
    })
    store.assets[rec["id"]] = rec
    # Initialize compliance via next_due_date mapping (no version bump on init).
    rec["compliance_status"] = compute_compliance_status(rec)
    return ok_object(asset_view(rec), 201)


@bp.route("/pm/assets/<asset_id>", methods=["GET"])
def get_asset_route(asset_id):
    _, role = auth()
    require_role(role, ALL)
    a = get_asset(asset_id)
    return ok_object(asset_view(a), 200)


@bp.route("/pm/assets", methods=["GET"])
def list_assets():
    _, role = auth()
    require_role(role, ALL)
    rows = list(store.assets.values())
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        rows = [a for a in rows if a["unit_id"] == unit_id]
    property_id = request.args.get("property_id")
    if property_id is not None:
        rows = [a for a in rows if _asset_property_id(a) == property_id]
    superseded = request.args.get("superseded_by_asset_id")
    if superseded is not None:
        rows = [a for a in rows if a["superseded_by_asset_id"] == superseded]
    ctype = request.args.get("component_type")
    if ctype is not None:
        rows = [a for a in rows if a["component_type"] == ctype]
    cstat = request.args.get("compliance_status")
    if cstat is not None:
        rows = [a for a in rows if a["compliance_status"] == cstat]
    ostat = request.args.get("operational_status")
    if ostat is not None:
        rows = [a for a in rows if a["operational_status"] == ostat]
    page, limit, offset, total = paginate(rows)
    return ok_list([asset_view(a) for a in page], limit, offset, total)


@bp.route("/pm/assets/<asset_id>/operational-status", methods=["POST"])
def set_operational_status(asset_id):
    _, role = auth()
    require_role(role, PM)
    a = get_asset(asset_id)
    require_active_property(property_of_asset(a))
    data = body()
    # Stage 5: transition legality (DECOMMISSIONED is never a source here).
    target_raw = data.get("target_status")
    if target_raw == "DECOMMISSIONED" or (
            isinstance(target_raw, str)
            and target_raw not in ("IN_SERVICE", "OUT_OF_SERVICE")):
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "target_status must be IN_SERVICE or OUT_OF_SERVICE")
    target = v_enum(data, "target_status", ("IN_SERVICE", "OUT_OF_SERVICE"))
    if a["operational_status"] == "DECOMMISSIONED" or a["operational_status"] == target:
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Asset cannot transition from %s to %s"
                       % (a["operational_status"], target))
    a["operational_status"] = target
    touch(a)
    return ok_object(asset_view(a), 200)


@bp.route("/pm/assets/<asset_id>/decommission", methods=["POST"])
def decommission_asset(asset_id):
    _, role = auth()
    require_role(role, PM)
    a = get_asset(asset_id)
    require_active_property(property_of_asset(a))
    if a["operational_status"] == "DECOMMISSIONED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Asset is already DECOMMISSIONED")
    for wo in store.work_orders.values():
        if wo["asset_id"] == a["id"] and wo["status"] in OPEN_WO_STATES:
            raise ApiError(E.ERR_ASSET_HAS_OPEN_WORK, 409,
                           "Asset has an open corrective work order")
    a["operational_status"] = "DECOMMISSIONED"
    touch(a)
    return ok_object(asset_view(a), 200)
