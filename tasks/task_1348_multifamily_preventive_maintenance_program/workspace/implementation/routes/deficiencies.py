"""Deficiency lifecycle: create (nested under visit), list, triage, waive."""
from flask import Blueprint, request

import errors as E
from errors import ApiError
from db import store, new_common_fields, touch
from middleware import auth, require_role, body, v_str, v_enum, paginate
from response import ok_object, ok_list
from services.core import (get_visit, get_asset, get_deficiency,
                           property_of_visit, property_of_deficiency,
                           require_active_property, OPEN_WO_STATES)
from services.serializers import deficiency_view

bp = Blueprint("deficiencies", __name__)

PM = ("PropertyManager",)
TECH = ("Technician",)
ALL = ("PropertyManager", "Technician", "ComplianceAuditor")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "EMERGENCY")


@bp.route("/pm/visits/<visit_id>/deficiencies", methods=["POST"])
def create_deficiency(visit_id):
    _, role = auth()
    require_role(role, TECH)
    v = get_visit(visit_id)
    data = body()
    asset = None
    if data.get("asset_id") is not None:
        asset = get_asset(data["asset_id"])
    require_active_property(property_of_visit(v))
    if v["visit_status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Deficiencies may be recorded only on IN_PROGRESS or COMPLETED visits")
    if asset is not None and asset["id"] != v["asset_id"]:
        raise ApiError(E.ERR_DEFICIENCY_ASSET_MISMATCH, 422,
                       "Deficiency asset_id must equal the visit's asset_id")
    aid = v_str(data, "asset_id")
    severity = v_enum(data, "severity", SEVERITIES)
    desc = v_str(data, "description")
    if asset is None:
        asset = get_asset(aid)
        if asset["id"] != v["asset_id"]:
            raise ApiError(E.ERR_DEFICIENCY_ASSET_MISMATCH, 422,
                           "Deficiency asset_id must equal the visit's asset_id")
    rec = new_common_fields()
    rec.update({
        "visit_id": v["id"],
        "asset_id": asset["id"],
        "severity": severity,
        "description": desc,
        "status": "RECORDED",
        "work_order_id": None,
    })
    store.deficiencies[rec["id"]] = rec
    return ok_object(deficiency_view(rec), 201)


@bp.route("/pm/deficiencies", methods=["GET"])
def list_deficiencies():
    _, role = auth()
    require_role(role, ALL)
    rows = list(store.deficiencies.values())
    for param, field in (("visit_id", "visit_id"), ("asset_id", "asset_id"),
                         ("status", "status")):
        val = request.args.get(param)
        if val is not None:
            rows = [d for d in rows if d[field] == val]
    page, limit, offset, total = paginate(rows)
    return ok_list([deficiency_view(d) for d in page], limit, offset, total)


@bp.route("/pm/deficiencies/<deficiency_id>", methods=["GET"])
def get_deficiency_route(deficiency_id):
    _, role = auth()
    require_role(role, ALL)
    d = get_deficiency(deficiency_id)
    return ok_object(deficiency_view(d), 200)


@bp.route("/pm/deficiencies/<deficiency_id>/triage", methods=["POST"])
def triage_deficiency(deficiency_id):
    _, role = auth()
    require_role(role, PM)
    d = get_deficiency(deficiency_id)
    require_active_property(property_of_deficiency(d))
    if d["status"] != "RECORDED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Deficiency in %s cannot be triaged" % d["status"])
    d["status"] = "TRIAGED"
    touch(d)
    return ok_object(deficiency_view(d), 200)


@bp.route("/pm/deficiencies/<deficiency_id>/waive", methods=["POST"])
def waive_deficiency(deficiency_id):
    _, role = auth()
    require_role(role, PM)
    d = get_deficiency(deficiency_id)
    require_active_property(property_of_deficiency(d))
    if d["status"] not in ("RECORDED", "TRIAGED"):
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Deficiency in %s cannot be waived" % d["status"])
    for wo in store.work_orders.values():
        if wo["deficiency_id"] == d["id"] and wo["status"] in OPEN_WO_STATES:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Deficiency has an open corrective work order")
    if d["severity"] == "EMERGENCY":
        raise ApiError(E.ERR_EMERGENCY_NOT_WAIVABLE, 422,
                       "An EMERGENCY deficiency may not be waived")
    d["status"] = "WAIVED"
    touch(d)
    return ok_object(deficiency_view(d), 200)
