"""NetworkLoop endpoints and the loop emissions summary (PRD 3.1, 3.9)."""

from flask import Blueprint

import calc
import enums
import services as svc
from db import base_record, store
from middleware import ALL_STAFF, endpoint, paginate
from validators import get_enum, get_num, get_str, json_body, query_enum

bp = Blueprint("loops", __name__, url_prefix="/district-energy")

READERS = ALL_STAFF
SUMMARY_READERS = ("SystemController", "NetworkEngineer", "BillingAnalyst")


@endpoint(bp, "/network-loops", ["POST"], ["SystemController"], status=201)
def create_loop():
    body = json_body()
    code = get_str(body, "code", min_len=1, max_len=32)
    name = get_str(body, "name")
    service_mode = get_enum(body, "service_mode", enums.SERVICE_MODE)
    design_supply_temp_c = get_num(body, "design_supply_temp_c")
    max_pressure_kpa = get_num(body, "max_pressure_kpa", gt=0)
    rated_capacity_kw = get_num(body, "rated_capacity_kw", gt=0)

    svc.require_unique_code("loops", "code", code)

    loop = base_record()
    loop.update({
        "code": code,
        "name": name,
        "service_mode": service_mode,
        "design_supply_temp_c": design_supply_temp_c,
        "max_pressure_kpa": max_pressure_kpa,
        "rated_capacity_kw": rated_capacity_kw,
        "posture": "NORMAL",
        "committed_reserved_kw": 0.0,
        "open_isolation_count": 0,
        "suspect_segment_count": 0,
    })
    store.loops[loop["id"]] = loop
    return loop


@endpoint(bp, "/network-loops", ["GET"], READERS)
def list_loops():
    filters = {}
    service_mode = query_enum("service_mode", enums.SERVICE_MODE)
    posture = query_enum("posture", enums.POSTURE)
    if service_mode is not None:
        filters["service_mode"] = service_mode
    if posture is not None:
        filters["posture"] = posture
    return paginate(svc.where("loops", **filters))


@endpoint(bp, "/network-loops/<loop_id>", ["GET"], READERS)
def get_loop(loop_id):
    return svc.path_get("loops", loop_id)


@endpoint(bp, "/network-loops/<loop_id>/emissions-summary", ["GET"], SUMMARY_READERS)
def loop_emissions_summary(loop_id):
    loop = svc.path_get("loops", loop_id)
    plans = [p for p in svc.rows("plans")
             if p["loop_id"] == loop["id"]
             and p["plan_state"] in ("COMMITTED", "RECONCILED")]
    orders = []
    for plan in plans:
        orders.extend(svc.plan_orders(plan["id"]))
    return calc.loop_emissions_efficiency_summary(loop["id"], plans, orders)
