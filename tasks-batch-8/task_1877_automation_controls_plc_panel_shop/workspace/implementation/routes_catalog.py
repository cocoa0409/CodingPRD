"""Routes: catalog components."""

from flask import Blueprint, request

from core import (
    bump,
    envelope_object,
    err_duplicate,
    err_invalid_request,
    get_body,
    opt_bool,
    opt_int,
    opt_num,
    paginate,
    req_enum,
    req_int,
    req_num,
    req_str,
    require_roles,
    sorted_by_created,
    stamp_new,
)
from lookups import get_component
from serializers import ser_component
from store import db

bp = Blueprint("catalog", __name__)

COMPONENT_CLASSES = (
    "DISCONNECT",
    "BRANCH_PROTECTIVE",
    "CONTACTOR",
    "OVERLOAD",
    "CONTROL_POWER",
    "PLC_IO",
    "TERMINAL",
    "WIRE_DUCT",
    "PILOT_DEVICE",
    "POWER_SUPPLY",
)


@bp.route("/panel-shop/components", methods=["POST"])
def create_component():
    require_roles("QAManager")
    body = get_body()
    part_number = req_str(body, "part_number")
    component_class = req_enum(body, "component_class", COMPONENT_CLASSES)
    unit_cost_cents = req_int(body, "unit_cost_cents")
    if unit_cost_cents < 0:
        raise err_invalid_request("unit_cost_cents must be >= 0.")
    lead_time_days = req_int(body, "lead_time_days")
    if lead_time_days < 0:
        raise err_invalid_request("lead_time_days must be >= 0.")
    sccr_ka = body.get("sccr_ka")
    if sccr_ka is not None:
        if not isinstance(sccr_ka, int) or isinstance(sccr_ka, bool) or sccr_ka < 1:
            raise err_invalid_request("sccr_ka must be an integer >= 1 when present.")
    heat_dissipation_w = req_num(body, "heat_dissipation_w")
    if heat_dissipation_w < 0:
        raise err_invalid_request("heat_dissipation_w must be >= 0.")
    active = opt_bool(body, "active", True)
    if any(c["part_number"] == part_number for c in db.components.values()):
        raise err_duplicate("part_number already exists.")
    c = stamp_new(
        {
            "part_number": part_number,
            "component_class": component_class,
            "unit_cost_cents": unit_cost_cents,
            "lead_time_days": lead_time_days,
            "sccr_ka": sccr_ka,
            "heat_dissipation_w": heat_dissipation_w,
            "active": active,
        }
    )
    db.components[c["id"]] = c
    return envelope_object(ser_component(c), 201)


@bp.route("/panel-shop/components/<component_id>", methods=["GET"])
def fetch_component(component_id):
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "ShopLead")
    return envelope_object(ser_component(get_component(component_id)))


@bp.route("/panel-shop/components", methods=["GET"])
def list_components():
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "ShopLead")
    comps = list(db.components.values())
    args = request.args
    if "component_class" in args:
        comps = [c for c in comps if c["component_class"] == args.get("component_class")]
    if "active" in args:
        raw = args.get("active").lower()
        if raw not in ("true", "false"):
            raise err_invalid_request("active filter must be true or false.")
        want = raw == "true"
        comps = [c for c in comps if c["active"] == want]
    return paginate(sorted_by_created(comps), ser_component)


@bp.route("/panel-shop/components/<component_id>", methods=["PATCH"])
def update_component(component_id):
    require_roles("QAManager")
    c = get_component(component_id)
    body = get_body()
    if "lead_time_days" in body:
        v = opt_int(body, "lead_time_days")
        if v is None or v < 0:
            raise err_invalid_request("lead_time_days must be an integer >= 0.")
        c["lead_time_days"] = v
    if "unit_cost_cents" in body:
        v = opt_int(body, "unit_cost_cents")
        if v is None or v < 0:
            raise err_invalid_request("unit_cost_cents must be an integer >= 0.")
        c["unit_cost_cents"] = v
    if "active" in body:
        c["active"] = opt_bool(body, "active")
    bump(c)
    return envelope_object(ser_component(c))
