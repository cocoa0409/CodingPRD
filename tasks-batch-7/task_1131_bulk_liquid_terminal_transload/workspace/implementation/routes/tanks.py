"""Tank endpoints including maintenance state transitions."""
from flask import Blueprint, request

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import tank_view
from services import calc
from services.common import touch, get_tank_or_404
from validation import (get_body, req_string, req_enum, req_number, opt_number,
                        sort_and_page, PRODUCT_GRADES)

bp = Blueprint("tanks", __name__)

VAPOR_CLASSES = ("NONE", "VRU_REQUIRED")


@bp.post("/tanks")
def create_tank():
    require_roles("TerminalOperator")
    body = get_body()
    tank_code = req_string(body, "tank_code")
    product_grade = req_enum(body, "product_grade", PRODUCT_GRADES)
    capacity_bbl = req_number(body, "capacity_bbl", gt=0)
    safe_fill_pct = opt_number(body, "safe_fill_pct", 0.95, gt=0, le=1)
    heel_bbl = opt_number(body, "heel_bbl", 0, ge=0)
    vapor_control_class = body.get("vapor_control_class", "NONE")
    if not isinstance(vapor_control_class, str) or vapor_control_class not in VAPOR_CLASSES:
        raise err("ERR_VALIDATION",
                  "Field 'vapor_control_class' must be one of NONE, VRU_REQUIRED")

    now = CLOCK.now()
    tank = {
        "id": new_id(),
        "tank_code": tank_code,
        "product_grade": product_grade,
        "capacity_bbl": capacity_bbl,
        "safe_fill_pct": safe_fill_pct,
        "heel_bbl": heel_bbl,
        "vapor_control_class": vapor_control_class,
        "working_capacity_bbl": calc.compute_working_capacity(
            capacity_bbl, safe_fill_pct, heel_bbl),
        "current_inventory_bbl": 0,
        "provisional_inventory_bbl": 0,
        "status": "AVAILABLE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.tanks[tank["id"]] = tank
    return success_object(tank_view(tank), status=201)


@bp.get("/tanks")
def list_tanks():
    current_user()
    rows = list(STORE.tanks.values())
    status_filter = request.args.get("status")
    if status_filter is not None:
        rows = [t for t in rows if t["status"] == status_filter]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([tank_view(t) for t in page], total, limit, offset)


@bp.get("/tanks/<tankId>")
def get_tank(tankId):
    current_user()
    tank = get_tank_or_404(tankId)
    return success_object(tank_view(tank))


@bp.post("/tanks/<tankId>/enter-maintenance")
def enter_maintenance(tankId):
    require_roles("TerminalOperator")
    tank = get_tank_or_404(tankId)
    if tank["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE",
                  "Tank %s is %s; enter-maintenance requires AVAILABLE"
                  % (tankId, tank["status"]))
    for m in STORE.movements.values():
        if m["tank_id"] == tank["id"] and m["status"] in ("ARRIVED", "IN_PROGRESS", "SUSPENDED"):
            raise err("ERR_INVALID_STATE",
                      "Tank has a movement in status %s" % m["status"])
    tank["status"] = "MAINTENANCE"
    touch(tank)
    return success_object(tank_view(tank))


@bp.post("/tanks/<tankId>/return-to-service")
def return_to_service(tankId):
    require_roles("TerminalOperator")
    tank = get_tank_or_404(tankId)
    if tank["status"] != "MAINTENANCE":
        raise err("ERR_INVALID_STATE",
                  "Tank %s is %s; return-to-service requires MAINTENANCE"
                  % (tankId, tank["status"]))
    # No inventory re-evaluation here: bounds re-checked only on custody
    # certify / resolve / void (PRD 2.6).
    tank["status"] = "AVAILABLE"
    touch(tank)
    return success_object(tank_view(tank))
