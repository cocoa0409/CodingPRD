"""Resource order and crew assignment routes."""
from flask import Blueprint

from core import (
    DB,
    ApiError,
    Validator,
    auth,
    body,
    ok,
    paginate,
    parse_date,
    require_role,
    stamp_new,
    touch,
)
from domain import (
    contractor_available_units,
    contractor_standing,
    get_assignment,
    get_contractor,
    get_order,
    get_plan,
    recompute_order_fill,
    required_holding_force,
    ser_assignment,
    ser_order,
    window_conflicts,
)

bp = Blueprint("orders", __name__)


def _plan_of_order(order):
    return DB["plans"].get(order["burn_plan_id"])


def _author_of_plan_or_403(plan, uid):
    if plan is None or uid != plan["author_boss_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the plan's author")


# ---------------------------------------------------------------------------
# Resource orders
# ---------------------------------------------------------------------------


@bp.post("/burn-plans/<pid>/resource-orders")
def create_order(pid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    plan = get_plan(pid)
    _author_of_plan_or_403(plan, uid)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409, "Plan must be APPROVED")
    parcel = DB["parcels"].get(plan["parcel_id"])
    required = required_holding_force(plan, parcel)
    order = stamp_new(
        {
            "burn_plan_id": plan["id"],
            **required,
            "status": "DRAFT",
        }
    )
    DB["orders"][order["id"]] = order
    return ok(ser_order(order), 201)


@bp.get("/resource-orders/<oid>")
def get_one_order(oid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_order(get_order(oid)))


@bp.get("/burn-plans/<pid>/resource-orders")
def list_plan_orders(pid):
    _, role = auth()
    require_role(role, None)
    plan = get_plan(pid)
    items = [o for o in DB["orders"].values() if o["burn_plan_id"] == plan["id"]]
    return paginate(items, ser_order)


@bp.post("/resource-orders/<oid>/submit")
def submit_order(oid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    order = get_order(oid)
    _author_of_plan_or_403(_plan_of_order(order), uid)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", 409, "ResourceOrder must be DRAFT")
    order["status"] = "SUBMITTED"
    touch(order)
    return ok(ser_order(order))


# ---------------------------------------------------------------------------
# Crew assignments
# ---------------------------------------------------------------------------


@bp.post("/resource-orders/<oid>/assignments")
def create_assignment(oid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    order = get_order(oid)
    _author_of_plan_or_403(_plan_of_order(order), uid)
    if order["status"] not in ("SUBMITTED", "PARTIALLY_FILLED"):
        raise ApiError(
            "ERR_ORDER_NOT_OPEN", 409, "ResourceOrder must be SUBMITTED or PARTIALLY_FILLED"
        )
    contractor_id = data.get("contractor_id")
    contractor = None
    if isinstance(contractor_id, str):
        contractor = get_contractor(contractor_id)
    # standing gate (priority 9)
    if contractor is not None and contractor_standing(contractor) != "GOOD_STANDING":
        raise ApiError("ERR_CONTRACTOR_SUSPENDED", 403, "Contractor is suspended")
    # capacity + window conflict (priority 11), evaluated when inputs are typed
    units = data.get("units")
    ws = parse_date(data.get("window_start"))
    we = parse_date(data.get("window_end"))
    typed_units = units if (isinstance(units, int) and not isinstance(units, bool)) else None
    if contractor is not None and typed_units is not None and typed_units > 0:
        if contractor_available_units(contractor) < typed_units:
            raise ApiError(
                "ERR_CONTRACTOR_CAPACITY_EXCEEDED",
                409,
                "Assignment units exceed contractor.available_units",
            )
    if contractor is not None and ws is not None and we is not None and we > ws:
        if window_conflicts(contractor["id"], ws, we):
            raise ApiError(
                "ERR_CONTRACTOR_WINDOW_CONFLICT",
                409,
                "Contractor has a conflicting assignment window (1-day rest buffer)",
            )
    v = Validator(data, {"contractor_id", "units", "window_start", "window_end"})
    v.req("contractor_id", str)
    v.req("units", int)
    if typed_units is not None and typed_units <= 0:
        v.prescription("units must be a positive integer")
    v.date("window_start")
    v.date("window_end")
    if ws is not None and we is not None and we <= ws:
        v.prescription("window_end must be after window_start")
    v.finish()
    assignment = stamp_new(
        {
            "resource_order_id": order["id"],
            "contractor_id": contractor["id"],
            "units": data["units"],
            "window_start": ws,
            "window_end": we,
            "status": "ASSIGNED",
        }
    )
    DB["assignments"][assignment["id"]] = assignment
    return ok(ser_assignment(assignment), 201)


@bp.get("/resource-orders/<oid>/assignments")
def list_order_assignments(oid):
    _, role = auth()
    require_role(role, None)
    order = get_order(oid)
    items = [a for a in DB["assignments"].values() if a["resource_order_id"] == order["id"]]
    return paginate(items, ser_assignment)


@bp.post("/assignments/<aid>/confirm")
def confirm_assignment(aid):
    body()
    uid, role = auth()
    require_role(role, {"Contractor"})
    assignment = get_assignment(aid)
    # ownership (priority 4) before state (priority 7)
    if uid != assignment["contractor_id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the assignment's contractor"
        )
    if assignment["status"] != "ASSIGNED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_ASSIGNED", 409, "CrewAssignment must be ASSIGNED"
        )
    contractor = DB["contractors"].get(assignment["contractor_id"])
    if contractor is not None and contractor_standing(contractor) != "GOOD_STANDING":
        raise ApiError("ERR_CONTRACTOR_SUSPENDED", 403, "Contractor is suspended")
    if contractor is not None:
        # available_units excludes this ASSIGNED row's own units? No: ASSIGNED rows
        # already consume availability; at confirm time the units are already held.
        # The check re-validates that the contractor is not over-committed.
        used = sum(
            a["units"]
            for a in DB["assignments"].values()
            if a["contractor_id"] == contractor["id"]
            and a["status"] in ("ASSIGNED", "CONFIRMED")
        )
        if used > contractor["capacity_units"]:
            raise ApiError(
                "ERR_CONTRACTOR_CAPACITY_EXCEEDED",
                409,
                "Assignment units exceed contractor.available_units",
            )
        if window_conflicts(
            contractor["id"],
            assignment["window_start"],
            assignment["window_end"],
            exclude_assignment_id=assignment["id"],
        ):
            raise ApiError(
                "ERR_CONTRACTOR_WINDOW_CONFLICT",
                409,
                "Contractor has a conflicting assignment window (1-day rest buffer)",
            )
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    order = DB["orders"].get(assignment["resource_order_id"])
    if order is not None:
        recompute_order_fill(order)
    return ok(ser_assignment(assignment))


@bp.post("/assignments/<aid>/decline")
def decline_assignment(aid):
    body()
    uid, role = auth()
    require_role(role, {"Contractor"})
    assignment = get_assignment(aid)
    if uid != assignment["contractor_id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the assignment's contractor"
        )
    if assignment["status"] != "ASSIGNED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_ASSIGNED", 409, "CrewAssignment must be ASSIGNED"
        )
    assignment["status"] = "DECLINED"
    touch(assignment)
    return ok(ser_assignment(assignment))


@bp.post("/assignments/<aid>/release")
def release_assignment(aid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    assignment = get_assignment(aid)
    order = DB["orders"].get(assignment["resource_order_id"])
    _author_of_plan_or_403(_plan_of_order(order) if order else None, uid)
    if assignment["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_CONFIRMED", 409, "CrewAssignment must be CONFIRMED"
        )
    assignment["status"] = "RELEASED"
    touch(assignment)
    if order is not None:
        recompute_order_fill(order)
    return ok(ser_assignment(assignment))


@bp.post("/assignments/<aid>/mark-no-show")
def mark_no_show(aid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    assignment = get_assignment(aid)
    order = DB["orders"].get(assignment["resource_order_id"])
    _author_of_plan_or_403(_plan_of_order(order) if order else None, uid)
    if assignment["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_CONFIRMED", 409, "CrewAssignment must be CONFIRMED"
        )
    assignment["status"] = "NO_SHOW"
    touch(assignment)
    contractor = DB["contractors"].get(assignment["contractor_id"])
    if contractor is not None:
        contractor["no_show_count"] += 1
    if order is not None:
        recompute_order_fill(order)
    return ok(ser_assignment(assignment))
