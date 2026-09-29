"""Work orders: the cyclic repair loop with escalation and a hard reopen cap (3.7)."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import bump, db, iso, now, now_iso, parse_dt, sort_rows, today
from errors import ApiError
from services import calc, core, lookup

bp = Blueprint("work_orders", __name__)

SUBMIT_ROLES = (mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER, mw.MAINTENANCE_TECH)
ESCALATE_ROLES = (mw.SERVICE_MEMBER, mw.PROPERTY_MANAGER, mw.INSTALLATION_HOUSING_OFFICE)
REOPEN_ROLES = (mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER)

RESIDENT_REOPEN_LIMIT = 1
REOPEN_LIMIT = 2
ESCALATION_CAP = 2
ESCALATABLE = ("SUBMITTED", "ASSIGNED", "IN_PROGRESS", "REOPENED")


def _guard(order, allowed_from):
    if order["status"] == "CLOSED":
        raise ApiError("ERR_TERMINAL_STATE_LOCKED")
    if order["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


def _owner_guard(role, user_id, order):
    if order is not None and order.get("lease_id"):
        mw.require_owner(role, user_id, mw.lease_sponsor(order["lease_id"]))


@bp.post("/work-orders")
def submit_order():
    user_id, role = mw.authenticate(SUBMIT_ROLES)
    body = mw.json_body()
    raw_lease = mw.raw_ref(body, "lease_id")
    if raw_lease is not None:
        mw.require_owner(role, user_id, mw.lease_sponsor(raw_lease))
    housing_unit_id = mw.v_id(body, "housing_unit_id")
    lease_id = mw.v_id(body, "lease_id", required=False, default=None)
    parent_id = mw.v_id(body, "parent_work_order_id", required=False, default=None)
    category = mw.v_enum(body, "category", mw.WORK_ORDER_CATEGORIES)
    description = mw.v_str(body, "description")
    habitability = mw.v_bool(body, "habitability_impact", required=False, default=False)

    unit = lookup.housing_unit(housing_unit_id)
    lease = lookup.lease(lease_id) if lease_id is not None else None
    parent = lookup.work_order(parent_id) if parent_id is not None else None

    if lease is not None:
        if lease["housing_unit_id"] != unit["id"] \
                or lease["occupancy_status"] == "TERMINATED":
            raise ApiError("ERR_LEASE_UNIT_MISMATCH")
    if parent is not None and parent["housing_unit_id"] != unit["id"]:
        raise ApiError("ERR_WORK_ORDER_UNIT_MISMATCH")

    order = core.create_work_order(unit, lease["id"] if lease else None,
                                   parent["id"] if parent else None,
                                   category, description, habitability)
    return resp.created(order)


@bp.get("/work-orders/<order_id>")
def get_order(order_id):
    user_id, role = mw.authenticate(mw.ALL_ROLES)
    _owner_guard(role, user_id, lookup.maybe("work_orders", order_id))
    return resp.ok(lookup.work_order(order_id))


@bp.get("/work-orders")
def list_orders():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    housing_unit_id = mw.q_str("housing_unit_id")
    lease_id = mw.q_str("lease_id")
    parent_id = mw.q_str("parent_work_order_id")
    status = mw.q_enum("status", mw.WORK_ORDER_STATUSES)
    priority = mw.q_enum("priority_class", mw.PRIORITY_CLASSES)
    rows = sort_rows(list(db.work_orders.values()))
    if housing_unit_id is not None:
        rows = [r for r in rows if r["housing_unit_id"] == housing_unit_id]
    if lease_id is not None:
        rows = [r for r in rows if r["lease_id"] == lease_id]
    if parent_id is not None:
        rows = [r for r in rows if r["parent_work_order_id"] == parent_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if priority is not None:
        rows = [r for r in rows if r["priority_class"] == priority]
    return resp.page(rows, limit, offset)


@bp.post("/work-orders/<order_id>/assign")
def assign_order(order_id):
    mw.authenticate((mw.PROPERTY_MANAGER,))
    body = mw.json_body()
    tech = mw.v_str(body, "assigned_tech_user_id")
    order = lookup.work_order(order_id)
    _guard(order, ("SUBMITTED", "REOPENED"))
    order["assigned_tech_user_id"] = tech
    order["status"] = "ASSIGNED"
    if order["first_response_at"] is None:
        order["first_response_at"] = now_iso()
    bump(order)
    return resp.ok(order)


@bp.post("/work-orders/<order_id>/start")
def start_order(order_id):
    mw.authenticate((mw.MAINTENANCE_TECH,))
    mw.json_body()
    order = lookup.work_order(order_id)
    _guard(order, ("ASSIGNED",))
    if not order.get("assigned_tech_user_id"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The work order has no assigned technician.")
    order["status"] = "IN_PROGRESS"
    bump(order)
    return resp.ok(order)


@bp.post("/work-orders/<order_id>/complete")
def complete_order(order_id):
    mw.authenticate((mw.MAINTENANCE_TECH,))
    body = mw.json_body()
    mw.v_str(body, "completion_note", required=False, default=None)
    order = lookup.work_order(order_id)
    _guard(order, ("IN_PROGRESS",))

    completed_at = now()
    order["completed_at"] = iso(completed_at)
    order["sla_breached"] = completed_at > parse_dt(order["completion_due_at"])
    order["status"] = "CLOSED" if int(order["reopen_count"]) >= REOPEN_LIMIT \
        else "COMPLETED"
    bump(order)

    _cascade_inspection_resolved(order)
    _cascade_hazard_case(order)
    return resp.ok(order)


def _cascade_inspection_resolved(order):
    inspection, entry = core.find_inspection_for_order(order)
    if inspection is None:
        return
    entry["status"] = "RESOLVED"
    core.recompute_inspection_counts(inspection)
    if int(inspection["critical_open_count"]) == 0 \
            and inspection["status"] == "TENANT_ACKNOWLEDGED":
        inspection["status"] = "COMPLETED"
    bump(inspection)


def _cascade_hazard_case(order):
    for case in sort_rows(list(db.hazard_cases.values())):
        if case.get("remediation_work_order_id") != order["id"]:
            continue
        if case["status"] not in ("REMEDIATION_IN_PROGRESS", "DISPLACEMENT_ACTIVE"):
            continue
        was_displacing = case["status"] == "DISPLACEMENT_ACTIVE"
        case["status"] = "CLEARANCE_PENDING"
        bump(case)
        if was_displacing:
            core.close_authorized_lodgings(case, today(), cascade_account=True)
        return


@bp.post("/work-orders/<order_id>/reopen")
def reopen_order(order_id):
    user_id, role = mw.authenticate(REOPEN_ROLES)
    _owner_guard(role, user_id, lookup.maybe("work_orders", order_id))
    body = mw.json_body()
    mw.v_str(body, "reopen_reason")
    order = lookup.work_order(order_id)
    _guard(order, ("COMPLETED",))

    budget = RESIDENT_REOPEN_LIMIT if role == mw.SERVICE_MEMBER else REOPEN_LIMIT
    if int(order["reopen_count"]) >= budget:
        raise ApiError("ERR_REOPEN_LIMIT_REACHED")

    order["status"] = "REOPENED"
    order["reopen_count"] = int(order["reopen_count"]) + 1
    order["completed_at"] = None
    order["assigned_tech_user_id"] = None
    bump(order)

    inspection, entry = core.find_inspection_for_order(order)
    if inspection is not None:
        entry["status"] = "WORK_ORDER_CREATED"
        core.recompute_inspection_counts(inspection)
        if inspection["status"] == "COMPLETED":
            inspection["status"] = "TENANT_ACKNOWLEDGED"
        bump(inspection)
    return resp.ok(order)


@bp.post("/work-orders/<order_id>/escalate")
def escalate_order(order_id):
    user_id, role = mw.authenticate(ESCALATE_ROLES)
    _owner_guard(role, user_id, lookup.maybe("work_orders", order_id))
    mw.json_body()
    order = lookup.work_order(order_id)
    _guard(order, ESCALATABLE)

    target = int(order["escalation_level"]) + 1
    if target > ESCALATION_CAP:
        target = ESCALATION_CAP
    completion_due = parse_dt(order["completion_due_at"])
    moment = now()
    if not calc.escalation_due(order["priority_class"], target, completion_due, moment):
        raise ApiError("ERR_ESCALATION_NOT_DUE")

    level = int(order["escalation_level"]) + 1
    order["escalation_level"] = min(level, ESCALATION_CAP)
    order["escalated_at"] = iso(moment)
    order["sla_breached"] = moment > completion_due
    bump(order)
    return resp.ok(order)
