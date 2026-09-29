"""Change orders: pricing, two signatures and the client negotiation cycle."""
from decimal import Decimal

from flask import Blueprint

from errors import AppError
from store import db, now, bump, ordered
from util import (
    authorize, check_staff_identity, parse_body, ok, ok_list, paginate, qfilter,
    req_str, opt_str, opt_id, req_enum, req_money, opt_money, req_int, opt_int,
    add_days, q2,
)
from routes.common import fetch, own_project
from services.constants import (
    CHANGE_ORDER_ORIGINS, MAX_REVISION_ROUNDS, CLIENT_RESPONSE_DAYS,
)
from services.calc import change_order_priced_amount
from services.ledger import recompute_project, project_schedule_tasks
from services.rows import new_change_order_row

bp = Blueprint("change_orders", __name__)

CO_READ_ROLES = ["PlatformAdmin", "ProjectManager", "Estimator", "Controller", "Client"]
CLIENT_DECISIONS = ("APPROVE", "REQUEST_REVISION", "REJECT")


def shift_schedule(project_id, days):
    """Shift every PLANNED / RELEASED task by `days` (may be negative), processed in
    (planned_start ASC, created_at ASC) order (PRD 3.3)."""
    if not days:
        return
    tasks = [t for t in db.schedule_tasks.values()
             if t["project_id"] == project_id and t["status"] in ("PLANNED", "RELEASED")]
    tasks.sort(key=lambda t: (t["planned_start"], t["created_at"], t["_seq"]))
    for task in tasks:
        task["planned_start"] = add_days(task["planned_start"], days)
        task["planned_finish"] = add_days(task["planned_finish"], days)
        bump(task)


@bp.post("/change-orders")
def create_change_order():
    user_id, role = authorize(["ProjectManager"])
    body = parse_body()
    project_id = req_str(body, "project_id")
    origin = req_enum(body, "origin", CHANGE_ORDER_ORIGINS)
    scope_description = req_str(body, "scope_description")
    direct_cost = req_money(body, "direct_cost", minimum=Decimal("0"))
    schedule_impact_days = opt_int(body, "schedule_impact_days", 0, minimum=0)
    source_allowance_item_id = opt_id(body, "source_allowance_item_id")

    # ladder step 6
    project = db.projects.get(project_id)
    if project is None:
        raise AppError("ERR_PROJECT_NOT_FOUND")
    source_item = None
    if source_allowance_item_id is not None:
        source_item = db.allowance_items.get(source_allowance_item_id)
        if source_item is None:
            raise AppError("ERR_ALLOWANCE_ITEM_NOT_FOUND")

    check_staff_identity(user_id, role)

    # ladder step 22
    if source_item is not None and source_item["project_id"] != project_id:
        raise AppError("ERR_ALLOWANCE_PROJECT_MISMATCH")

    row = new_change_order_row(project_id, origin, scope_description, q2(direct_cost),
                               schedule_impact_days, source_allowance_item_id)
    db.change_orders[row["id"]] = row
    return ok(row, 201)


@bp.get("/change-orders/<change_order_id>")
def get_change_order(change_order_id):
    user_id, role = authorize(CO_READ_ROLES)
    row = fetch("change_orders", change_order_id)
    check_staff_identity(user_id, role)
    return ok(row, 200)


@bp.get("/change-orders")
def list_change_orders():
    user_id, role = authorize(CO_READ_ROLES)
    check_staff_identity(user_id, role)
    rows = ordered(db.change_orders.values())
    for name in ("project_id", "source_allowance_item_id", "priced_by_staff_id",
                 "submitted_by_staff_id", "status"):
        value = qfilter(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/change-orders/<change_order_id>/price")
def price_change_order(change_order_id):
    user_id, role = authorize(["Estimator", "ProjectManager"])
    order = fetch("change_orders", change_order_id)
    body = parse_body()
    direct_cost = opt_money(body, "direct_cost", None, minimum=Decimal("0"))
    schedule_impact_days = opt_int(body, "schedule_impact_days", None, minimum=0)
    check_staff_identity(user_id, role)

    # ladder step 10
    if order["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise AppError("ERR_CHANGE_ORDER_INVALID_STATE")

    # ladder step 11
    project = db.projects.get(order["project_id"])
    if project is None or project["status"] != "UNDER_CONSTRUCTION":
        raise AppError("ERR_PROJECT_NOT_UNDER_CONSTRUCTION")

    repricing = order["status"] == "REVISION_REQUESTED"

    if direct_cost is not None:
        order["direct_cost"] = q2(direct_cost)
    if schedule_impact_days is not None:
        order["schedule_impact_days"] = schedule_impact_days

    if repricing:
        order["revision_count"] = (order.get("revision_count") or 0) + 1

    markup_rate, contingency_rate, priced_amount = change_order_priced_amount(
        order["direct_cost"], order["schedule_impact_days"])
    order["markup_rate_applied"] = markup_rate
    order["contingency_rate_applied"] = contingency_rate
    order["priced_amount"] = priced_amount
    order["priced_by_staff_id"] = user_id
    order["priced_at"] = now()
    order["status"] = "PRICED"
    bump(order)
    return ok(order, 200)


@bp.post("/change-orders/<change_order_id>/submit")
def submit_change_order(change_order_id):
    user_id, role = authorize(["ProjectManager"])
    order = fetch("change_orders", change_order_id)
    parse_body()
    check_staff_identity(user_id, role)

    # ladder step 10
    if order["status"] != "PRICED":
        raise AppError("ERR_CHANGE_ORDER_INVALID_STATE")
    # ladder step 20 - segregation of duties
    if order.get("priced_by_staff_id") == user_id:
        raise AppError("ERR_SEGREGATION_OF_DUTIES",
                       "The submitter must differ from the staff member who priced it.")
    # ladder step 30
    if (order.get("revision_count") or 0) > MAX_REVISION_ROUNDS:
        raise AppError("ERR_REVISION_LIMIT_EXCEEDED")

    order["submitted_by_staff_id"] = user_id
    order["submitted_at"] = now()
    order["client_response_due_at"] = add_days(order["submitted_at"], CLIENT_RESPONSE_DAYS)
    order["status"] = "SUBMITTED"
    bump(order)
    return ok(order, 200)


@bp.post("/change-orders/<change_order_id>/client-decision")
def client_decide_change_order(change_order_id):
    user_id, role = authorize(["Client"])
    order = fetch("change_orders", change_order_id)
    body = parse_body()
    decision = req_enum(body, "decision", CLIENT_DECISIONS)
    revision_note = opt_str(body, "revision_note")

    project = db.projects.get(order["project_id"])
    own_project(project, user_id, role)

    # ladder step 10
    if order["status"] != "SUBMITTED":
        raise AppError("ERR_CHANGE_ORDER_INVALID_STATE")

    if decision == "REQUEST_REVISION":
        # ladder step 30
        if (order.get("revision_count") or 0) >= MAX_REVISION_ROUNDS:
            raise AppError("ERR_REVISION_LIMIT_EXCEEDED")
        order["status"] = "REVISION_REQUESTED"
        order["revision_note"] = revision_note
        bump(order)
        return ok(order, 200)

    if decision == "REJECT":
        order["status"] = "REJECTED"
        order["decided_at"] = now()
        bump(order)
        return ok(order, 200)

    # APPROVE - ladder step 11
    if project is None or project["status"] != "UNDER_CONSTRUCTION":
        raise AppError("ERR_PROJECT_NOT_UNDER_CONSTRUCTION")

    order["status"] = "APPROVED"
    order["decided_at"] = now()
    bump(order)

    recompute_project(project)
    bump(project)

    if (order.get("schedule_impact_days") or 0) > 0:
        shift_schedule(project["id"], order["schedule_impact_days"])

    return ok(order, 200)


@bp.post("/change-orders/<change_order_id>/void")
def void_change_order(change_order_id):
    user_id, role = authorize(["Client"])
    order = fetch("change_orders", change_order_id)
    body = parse_body()
    void_reason = req_str(body, "void_reason")

    project = db.projects.get(order["project_id"])
    own_project(project, user_id, role)

    # ladder step 10
    if order["status"] != "APPROVED":
        raise AppError("ERR_CHANGE_ORDER_INVALID_STATE")
    # ladder step 11
    if project is None or project["status"] != "UNDER_CONSTRUCTION":
        raise AppError("ERR_PROJECT_NOT_UNDER_CONSTRUCTION")

    order["status"] = "VOIDED"
    order["void_reason"] = void_reason
    order["decided_at"] = now()
    bump(order)

    recompute_project(project)
    bump(project)

    if (order.get("schedule_impact_days") or 0) > 0:
        shift_schedule(project["id"], -order["schedule_impact_days"])

    return ok(order, 200)
