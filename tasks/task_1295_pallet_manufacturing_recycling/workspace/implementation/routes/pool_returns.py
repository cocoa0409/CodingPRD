"""PoolReturn endpoints: log/grade/credit/dispute."""

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, opt_field, as_str, as_int, as_enum,
)
from response import success
from services.calc import POOL_CREDIT_TIER_CENTS
from services.helpers import (
    init_common, touch, serialize, serialize_list, sorted_by_creation,
    get_or_404, ref_or_404,
)

bp = Blueprint("pool_returns", __name__)

RETURN_GRADES = ("A", "B", "SCRAP")


@bp.post("/pallet-ops/pool-returns")
def create_pool_return():
    require_roles("SalesRep", "YardSupervisor")
    body = get_json_body()
    customer_id = as_str(req_field(body, "customer_id"), "customer_id")
    ref_or_404(db.customers, customer_id, "customer_id")
    returned_count = as_int(req_field(body, "returned_count"), "returned_count", minimum=1)
    grade = as_enum(req_field(body, "grade_on_return"), "grade_on_return", RETURN_GRADES)
    route_stop_id = opt_field(body, "route_stop_id", None)
    if route_stop_id is not None:
        if not isinstance(route_stop_id, str):
            raise_err("ERR_INVALID_REQUEST", "route_stop_id must be a string")
        ref_or_404(db.route_stops, route_stop_id, "route_stop_id")

    ret = {
        "customer_id": customer_id,
        "returned_count": returned_count,
        "grade_on_return": grade,
        "credit_per_unit_cents": None,
        "total_credit_cents": None,
        "route_stop_id": route_stop_id,
        "status": "LOGGED",
    }
    init_common(ret)
    db.pool_returns[ret["id"]] = ret
    return success(serialize(ret), status=201)


@bp.get("/pallet-ops/pool-returns")
def list_pool_returns():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.pool_returns.values())
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    route_stop_id = request.args.get("route_stop_id")
    if route_stop_id is not None:
        items = [r for r in items if r.get("route_stop_id") == route_stop_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/pool-returns/<rid>")
def get_pool_return(rid):
    require_roles()
    ret = get_or_404(db.pool_returns, rid, "PoolReturn")
    return success(serialize(ret))


@bp.post("/pallet-ops/pool-returns/<rid>/grade")
def grade_pool_return(rid):
    require_roles("YardSupervisor")
    ret = get_or_404(db.pool_returns, rid, "PoolReturn")
    body = get_json_body()
    grade = as_enum(req_field(body, "grade_on_return"), "grade_on_return", RETURN_GRADES)

    if ret["status"] != "LOGGED":
        raise_err("ERR_RETURN_NOT_LOGGED", "grade requires return LOGGED")

    ret["grade_on_return"] = grade
    ret["credit_per_unit_cents"] = POOL_CREDIT_TIER_CENTS[grade]
    ret["total_credit_cents"] = ret["returned_count"] * ret["credit_per_unit_cents"]
    ret["status"] = "GRADED"
    touch(ret)
    return success(serialize(ret))


@bp.post("/pallet-ops/pool-returns/<rid>/credit")
def credit_pool_return(rid):
    require_roles("SalesRep")
    ret = get_or_404(db.pool_returns, rid, "PoolReturn")
    if ret["status"] != "GRADED":
        raise_err("ERR_RETURN_NOT_GRADED", "credit requires return GRADED")
    customer = db.customers.get(ret["customer_id"])
    if customer is None:
        raise_err("ERR_REFERENCED_NOT_FOUND", "Referenced customer_id does not exist")
    if customer["pool_units_outstanding"] < ret["returned_count"]:
        raise_err(
            "ERR_RETURN_EXCEEDS_OUTSTANDING",
            "returned_count exceeds customer.pool_units_outstanding",
        )

    # Ledger sync in one motion.
    customer["pool_credit_balance_cents"] += ret["total_credit_cents"]
    customer["pool_units_outstanding"] -= ret["returned_count"]
    touch(customer)

    # Inject returned units into the core pipeline: SCRAP -> GRINDING_QUEUED,
    # A/B -> YARD with grade set. One CoreUnit row per returned unit.
    for _ in range(ret["returned_count"]):
        core = {
            "batch_id": None,
            "grade": ret["grade_on_return"],
            "species": "MIXED",
            "condition_notes": "",
            "repair_cycle_count": 0,
            "processing_status": (
                "GRINDING_QUEUED" if ret["grade_on_return"] == "SCRAP" else "YARD"
            ),
            "rework_of_id": None,
            "_pool_return_id": ret["id"],
        }
        init_common(core)
        db.core_units[core["id"]] = core

    ret["status"] = "CREDITED"
    touch(ret)
    return success(serialize(ret))


@bp.post("/pallet-ops/pool-returns/<rid>/dispute")
def dispute_pool_return(rid):
    require_roles("SalesRep")
    ret = get_or_404(db.pool_returns, rid, "PoolReturn")
    if ret["status"] != "LOGGED":
        raise_err("ERR_RETURN_NOT_LOGGED", "dispute requires return LOGGED")
    ret["status"] = "DISPUTED"
    touch(ret)
    return success(serialize(ret))
