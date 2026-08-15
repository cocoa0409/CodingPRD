"""RepairCrew endpoints (PRD §3.3)."""
from flask import request

from db import STORE, make_entity, serialize, touch
from errors import bad_request, err, invalid_state
from middleware import (body, parse_pagination, req_bool, req_int, req_str,
                        require_roles)
from response import list_response, success
from services import FIELDS, get_or_404, sorted_all
from . import bp


def ser(crew):
    return serialize(crew, FIELDS["repair_crews"])


@bp.post("/repair-crews")
@require_roles("DispatchCoordinator")
def create_crew():
    d = body()
    code = req_str(d, "crew_code")
    region = req_str(d, "home_region")
    qualified = req_bool(d, "is_qualified_excavation")
    max_orders = req_int(d, "max_concurrent_orders")
    if max_orders < 0:
        raise bad_request("max_concurrent_orders must be >= 0")
    if any(c["crew_code"] == code for c in STORE["repair_crews"].values()):
        raise bad_request("crew_code must be unique")
    crew = make_entity()
    crew.update({"crew_code": code, "home_region": region,
                 "is_qualified_excavation": qualified,
                 "max_concurrent_orders": max_orders, "open_order_count": 0,
                 "status": "AVAILABLE"})
    STORE["repair_crews"][crew["id"]] = crew
    return success(ser(crew), code=201)


@bp.get("/repair-crews")
@require_roles("DispatchCoordinator", "IntegrityAnalyst")
def list_crews():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = sorted_all("repair_crews")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, ser, limit, offset)


@bp.get("/repair-crews/<cid>")
@require_roles("DispatchCoordinator", "IntegrityAnalyst")
def get_crew(cid):
    return success(ser(get_or_404("repair_crews", cid)))


@bp.get("/repair-crews/<cid>/repair-orders")
@require_roles("DispatchCoordinator", "IntegrityAnalyst")
def crew_repair_orders(cid):
    get_or_404("repair_crews", cid)
    limit, offset = parse_pagination()
    ds = request.args.get("dispatch_status")
    items = [o for o in sorted_all("repair_orders") if o.get("crew_id") == cid]
    if ds is not None:
        items = [o for o in items if o["dispatch_status"] == ds]
    return list_response(items,
                         lambda o: serialize(o, FIELDS["repair_orders"]),
                         limit, offset)


@bp.post("/repair-crews/<cid>/set-off-duty")
@require_roles("DispatchCoordinator")
def crew_set_off_duty(cid):
    crew = get_or_404("repair_crews", cid)
    if crew["status"] == "OFF_DUTY":
        raise invalid_state("RepairCrew is already OFF_DUTY")
    if crew["status"] == "AT_CAPACITY":
        has_open = any(o.get("crew_id") == cid
                       and o["dispatch_status"] in ("DISPATCHED", "ON_SITE")
                       for o in STORE["repair_orders"].values())
        if has_open:
            raise err("ERR_CREW_HAS_OPEN_ORDERS",
                      "Crew has open repair orders", 422)
    crew["status"] = "OFF_DUTY"
    touch(crew)
    return success(ser(crew))


@bp.post("/repair-crews/<cid>/set-on-duty")
@require_roles("DispatchCoordinator")
def crew_set_on_duty(cid):
    crew = get_or_404("repair_crews", cid)
    if crew["status"] != "OFF_DUTY":
        raise invalid_state("RepairCrew is not OFF_DUTY")
    crew["status"] = "AVAILABLE"
    touch(crew)
    return success(ser(crew))
