"""Budget line and OS&E order endpoints (PRD §3.7)."""
from flask import Blueprint

import clock
import db
import guards
import repo
import response
import tx
import validate as v
from db import db as store
from errors import ApiError
from middleware import ALL_ROLES, require
from services import derive

bp = Blueprint("budget", __name__)


# ===========================================================================
# Budget lines
# ===========================================================================

@bp.post("/pre-opening/budget-lines")
@require("ProgramDirector")
def create_budget_line():
    body = v.body()
    program_id = v.req_id(body, "program_id")
    category = v.req_enum(body, "category", repo.BUDGET_CATEGORIES)
    authorized_cents = v.req_int(body, "authorized_cents", minimum=0)

    program = repo.get_program(program_id)
    guards.ensure_not_stabilized(program)
    for existing in repo.budget_lines_of(program_id):
        if existing["category"] == category:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A %s budget line already exists for this program." % category)

    ts = db.stamp()
    line = {
        "id": db.new_id(),
        "program_id": program_id,
        "category": category,
        "authorized_cents": authorized_cents,
        "committed_cents": 0,
        "spent_cents": 0,
        "available_cents": authorized_cents,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.budget_lines[line["id"]] = line
    tx.commit()
    return response.created(repo.serialize(line))


@bp.get("/pre-opening/programs/<program_id>/budget-lines")
@require(*ALL_ROLES)
def list_budget_lines(program_id):
    program = repo.get_program(program_id)
    category = v.q_enum("category", repo.BUDGET_CATEGORIES)
    items = repo.budget_lines_of(program["id"])
    if category:
        items = [b for b in items if b["category"] == category]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


# ===========================================================================
# OS&E orders
# ===========================================================================

def _occupied_pallets(program_id, start, end, exclude_id=None):
    total = 0
    for order in repo.orders_of(program_id):
        if order["id"] == exclude_id:
            continue
        if order["state"] not in ("COMMITTED", "STORED"):
            continue
        other_start = clock.parse_date_strict(order["delivery_window_start"])
        other_end = clock.parse_date_strict(order["delivery_window_end"])
        if start < other_end and other_start < end:
            total += order["pallet_count"]
    return total


@bp.post("/pre-opening/ose-orders")
@require("ProcurementManager")
def create_order():
    body = v.body()
    program_id = v.req_id(body, "program_id")
    budget_line_id = v.req_id(body, "budget_line_id")
    description = v.req_str(body, "description", 1, 200)
    amount_cents = v.req_int(body, "amount_cents", minimum=1)
    pallet_count = v.req_int(body, "pallet_count", minimum=1)
    start_raw, start_date = v.req_date(body, "delivery_window_start")
    end_raw, end_date = v.req_date(body, "delivery_window_end")
    expected_version = v.req_int(body, "expected_budget_line_version", minimum=1)
    if not end_date > start_date:
        raise v.bad("delivery_window_end must be strictly after delivery_window_start.")

    program = repo.get_program(program_id)
    line = repo.get_budget_line(budget_line_id)
    if line["program_id"] != program_id:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE",
                       "The budget line belongs to another program.")
    guards.ensure_not_stabilized(program)
    if line["version"] != expected_version:
        raise ApiError("ERR_STALE_BUDGET_LINE_VERSION")
    guards.ensure_not_frozen(program)

    occupied = _occupied_pallets(program_id, start_date, end_date)
    if occupied + pallet_count > program["storage_capacity_pallets"]:
        raise ApiError("ERR_STORAGE_CAPACITY_EXCEEDED")
    if amount_cents > line["available_cents"]:
        raise ApiError("ERR_BUDGET_WOULD_EXCEED")

    ts = db.stamp()
    order = {
        "id": db.new_id(),
        "program_id": program_id,
        "budget_line_id": budget_line_id,
        "description": description,
        "amount_cents": amount_cents,
        "pallet_count": pallet_count,
        "delivery_window_start": start_raw,
        "delivery_window_end": end_raw,
        "state": "COMMITTED",
        "received_at": None,
        "stored_bay_code": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.ose_orders[order["id"]] = order
    derive.reconcile_cost(program)
    tx.commit(budget_line_id)
    return response.created(repo.serialize(order))


@bp.get("/pre-opening/ose-orders")
@require(*ALL_ROLES)
def list_orders():
    program_id = v.q_str("program_id")
    budget_line_id = v.q_str("budget_line_id")
    state = v.q_enum("state", repo.ORDER_STATES)
    items = db.sort_created(list(store.ose_orders.values()))
    if program_id:
        items = [o for o in items if o["program_id"] == program_id]
    if budget_line_id:
        items = [o for o in items if o["budget_line_id"] == budget_line_id]
    if state:
        items = [o for o in items if o["state"] == state]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.get("/pre-opening/ose-orders/<order_id>")
@require(*ALL_ROLES)
def read_order(order_id):
    return response.ok(repo.serialize(repo.get_order(order_id)))


@bp.post("/pre-opening/ose-orders/<order_id>/receive")
@require("ProcurementManager")
def receive_order(order_id):
    body = v.body()
    stored_bay_code = v.req_str(body, "stored_bay_code", 1, 16)
    order = repo.get_order(order_id)
    program = repo.get_program(order["program_id"])
    guards.ensure_not_stabilized(program)
    if order["state"] != "COMMITTED":
        raise ApiError("ERR_INVALID_OSE_ORDER_STATE",
                       "Only a COMMITTED order may be received.")
    guards.ensure_not_frozen(program)
    today = clock.today()
    if (today < clock.parse_date_strict(order["delivery_window_start"])
            or today >= clock.parse_date_strict(order["delivery_window_end"])):
        raise ApiError("ERR_DELIVERY_OUTSIDE_WINDOW")

    order["state"] = "STORED"
    order["received_at"] = clock.fmt_instant(clock.now())
    order["stored_bay_code"] = stored_bay_code
    derive.reconcile_cost(program)
    tx.commit(order["budget_line_id"])
    return response.ok(repo.serialize(order))


@bp.post("/pre-opening/ose-orders/<order_id>/cancel")
@require("ProcurementManager")
def cancel_order(order_id):
    body = v.body()
    v.opt_str(body, "reason", 1, 500)
    order = repo.get_order(order_id)
    program = repo.get_program(order["program_id"])
    guards.ensure_not_stabilized(program)
    if order["state"] != "COMMITTED":
        raise ApiError("ERR_INVALID_OSE_ORDER_STATE",
                       "Only a COMMITTED order may be cancelled.")

    order["state"] = "CANCELLED"
    derive.reconcile_cost(program)
    tx.commit(order["budget_line_id"])
    return response.ok(repo.serialize(order))
