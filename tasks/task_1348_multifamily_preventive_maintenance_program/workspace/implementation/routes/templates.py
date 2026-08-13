"""PM task template library (PRD §3.2)."""
from flask import Blueprint, request

import errors as E
from errors import ApiError
from db import store, new_common_fields, touch, parse_dt, fmt_ts, now
from middleware import auth, require_role, body, v_str, v_int, v_enum, v_bool, paginate
from response import ok_object, ok_list
from services.core import get_property, get_template, require_active_property
from services.serializers import template_view

bp = Blueprint("templates", __name__)

PM = ("PropertyManager",)
ALL = ("PropertyManager", "Technician", "ComplianceAuditor")
COMPONENT_TYPES = ("HVAC", "WATER_HEATER", "APPLIANCE")


@bp.route("/pm/pm-task-templates", methods=["POST"])
def create_template():
    _, role = auth()
    require_role(role, PM)
    data = body()
    prop = None
    if data.get("property_id") is not None:
        prop = get_property(data["property_id"])
        require_active_property(prop)
    pid = v_str(data, "property_id")
    ctype = v_enum(data, "component_type", COMPONENT_TYPES)
    name = v_str(data, "task_name")
    freq = v_int(data, "frequency_days", minv=1)
    minutes = v_int(data, "estimated_labor_minutes", minv=1)
    evidence = v_bool(data, "requires_evidence")
    eff_raw = v_str(data, "effective_from")
    try:
        parse_dt(eff_raw)
    except ValueError:
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "effective_from is not a valid ISO 8601 date")
    if prop is None:
        prop = get_property(pid)
        require_active_property(prop)
    rec = new_common_fields()
    rec.update({
        "property_id": prop["id"],
        "component_type": ctype,
        "task_name": name,
        "frequency_days": freq,
        "estimated_labor_minutes": minutes,
        "requires_evidence": evidence,
        "effective_from": eff_raw,
        "retired_at": None,
    })
    store.templates[rec["id"]] = rec
    return ok_object(template_view(rec), 201)


@bp.route("/pm/properties/<property_id>/pm-task-templates", methods=["GET"])
def list_templates(property_id):
    _, role = auth()
    require_role(role, ALL)
    prop = get_property(property_id)
    rows = [t for t in store.templates.values() if t["property_id"] == prop["id"]]
    include_retired = request.args.get("include_retired", "false").lower() == "true"
    if not include_retired:
        rows = [t for t in rows if t["retired_at"] is None]
    ctype = request.args.get("component_type")
    if ctype is not None:
        rows = [t for t in rows if t["component_type"] == ctype]
    page, limit, offset, total = paginate(rows)
    return ok_list([template_view(t) for t in page], limit, offset, total)


@bp.route("/pm/pm-task-templates/<template_id>/retire", methods=["POST"])
def retire_template(template_id):
    _, role = auth()
    require_role(role, PM)
    t = get_template(template_id)
    prop = store.properties.get(t["property_id"])
    require_active_property(prop)
    if t["retired_at"] is not None:
        raise ApiError(E.ERR_INVALID_STATE, 409, "Template is already retired")
    t["retired_at"] = fmt_ts(now())
    touch(t)
    return ok_object(template_view(t), 200)
