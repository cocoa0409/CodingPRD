"""AllocationCycle endpoints: create, fetch, open, close, nested orders/report."""
from flask import Blueprint, request

from db import db
from errors import err, ERR_INVALID_STATE
from middleware import get_identity, require_role
from response import object_response, array_response
from services import models
from services.calc import round2
from services.poundage import compute_poundage_report
from services.validate import (
    get_json_body,
    parse_pagination,
    paginate,
    require_string,
    require_number,
)
from routes.lookups import get_cycle

bp = Blueprint("cycles", __name__)

READ_ROLES_ALL = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor", "AgencyCoordinator"}
READ_ROLES_NO_COORD = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor"}


@bp.post("/allocation-cycles")
def create_cycle():
    user_id, role = get_identity()
    require_role(role, {"AllocationManager"})
    body = get_json_body()
    label = require_string(body, "label")
    total_pool = require_number(body, "total_pool_lbs", positive=True)

    cycle = models._common_create()
    cycle.update(
        {
            "label": label,
            "total_pool_lbs": round2(total_pool),
            "total_fair_share_weight": 0,
            "status": "DRAFT",
        }
    )
    db.allocation_cycles[cycle["id"]] = cycle
    return object_response(models.serialize_cycle(cycle), status=201)


@bp.get("/allocation-cycles/<cycle_id>")
def fetch_cycle(cycle_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_ALL)
    cycle = get_cycle(cycle_id)
    return object_response(models.serialize_cycle(cycle))


@bp.post("/allocation-cycles/<cycle_id>/open")
def open_cycle(cycle_id):
    user_id, role = get_identity()
    require_role(role, {"AllocationManager"})
    cycle = get_cycle(cycle_id)
    # state legality
    if cycle["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Cycle is not in DRAFT state.")
    active = [a for a in db.agencies.values() if a["status"] == "ACTIVE"]
    if not active:
        raise err(ERR_INVALID_STATE, "No ACTIVE agency to open cycle against.")
    cycle["total_fair_share_weight"] = sum(a["fair_share_weight"] for a in active)
    cycle["status"] = "OPEN"
    models.touch(cycle)
    return object_response(models.serialize_cycle(cycle))


@bp.post("/allocation-cycles/<cycle_id>/close")
def close_cycle(cycle_id):
    user_id, role = get_identity()
    require_role(role, {"AllocationManager"})
    cycle = get_cycle(cycle_id)
    if cycle["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Cycle is not in OPEN state.")
    for o in db.agency_orders.values():
        if o["allocation_cycle_id"] == cycle["id"] and o["status"] in (
            "SUBMITTED",
            "APPROVED",
        ):
            raise err(
                ERR_INVALID_STATE,
                "Cannot close cycle while orders remain SUBMITTED/APPROVED.",
            )
    cycle["status"] = "CLOSED"
    models.touch(cycle)
    return object_response(models.serialize_cycle(cycle))


@bp.get("/allocation-cycles/<cycle_id>/agency-orders")
def cycle_orders(cycle_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_NO_COORD)
    cycle = get_cycle(cycle_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    orders = [o for o in db.agency_orders.values() if o["allocation_cycle_id"] == cycle["id"]]
    if status is not None:
        orders = [o for o in orders if o["status"] == status]
    orders.sort(key=lambda o: o["_seq"])
    page, total = paginate(orders, limit, offset)
    return array_response([models.serialize_order(o) for o in page], limit, offset, total)


@bp.get("/allocation-cycles/<cycle_id>/poundage-report")
def cycle_poundage_report(cycle_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_NO_COORD)
    cycle = get_cycle(cycle_id)
    limit, offset = parse_pagination()
    report = compute_poundage_report(cycle["id"])
    items = [models.serialize_poundage_report(report)]
    page, total = paginate(items, limit, offset)
    return array_response(page, limit, offset, total)
