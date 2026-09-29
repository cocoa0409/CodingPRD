"""Reorder holds, auto-reorder schedules and the auto-reorder run."""

from flask import Blueprint

from db import db, make_row, sort_rows, touch
from errors import ApiError
from middleware import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE,
    ROLE_CUSTOMER,
    ROLE_FULFILLMENT,
    identity,
    lookup,
    paginate,
    parse_body,
    parse_pagination,
    parse_query,
    require_owner,
    require_role,
)
from response import list_response, object_response
from services import calc
from services.events import append_event
from services.ledger import has_open_hold, reconcile_customer_id
from services.workflow import auto_reorder_run, open_hold

bp = Blueprint("fulfillment", __name__)

HOLD_REASONS = ("PRESCRIBER_DENIED", "PRESCRIPTION_EXPIRED", "DISPUTE_UPHELD", "MANUAL")
HOLD_STATUSES = ("OPEN", "RELEASED", "ESCALATED")
CADENCE_BASES = ("NOMINAL", "USAGE_ADJUSTED")
SCHEDULE_STATUSES = ("ACTIVE", "PAUSED", "CANCELLED")


# ------------------------------------------------------------------ reorder holds


@bp.post("/reorder-holds")
def create_reorder_hold():
    user_id, role = identity()
    body = parse_body(
        {
            "customer_id": {"type": "uuid", "required": True},
            "prescription_id": {"type": "uuid", "required": True},
            "reason": {"type": "enum", "values": HOLD_REASONS, "required": True},
        }
    )
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    lookup("customer", body["customer_id"])
    lookup("prescription", body["prescription_id"])
    hold = open_hold(body["customer_id"], body["prescription_id"], body["reason"], user_id)
    append_event(
        body["prescription_id"], "HOLD_OPENED", "ReorderHold", hold["id"], (role, user_id)
    )
    reconcile_customer_id(body["customer_id"])
    return object_response(hold, 201)


@bp.get("/reorder-holds/<hold_id>")
def get_reorder_hold(hold_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER])
    hold = lookup("reorder_hold", hold_id)
    require_owner(role, user_id, hold["customer_id"])
    return object_response(hold)


@bp.get("/reorder-holds")
def list_reorder_holds():
    user_id, role = identity()
    filters = parse_query(
        {
            "customer_id": {"type": "string"},
            "prescription_id": {"type": "string"},
            "reason": {"type": "enum", "values": HOLD_REASONS},
            "status": {"type": "enum", "values": HOLD_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER])
    rows = list(db.reorder_holds.values())
    if role == ROLE_CUSTOMER:
        rows = [r for r in rows if r["customer_id"] == user_id]
    for field in ("customer_id", "prescription_id", "reason", "status"):
        if filters[field]:
            rows = [r for r in rows if r[field] == filters[field]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/reorder-holds/<hold_id>/release")
def release_reorder_hold(hold_id):
    user_id, role = identity()
    parse_body({"note": {"type": "string"}})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    hold = lookup("reorder_hold", hold_id)
    if hold.get("opened_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if hold["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    prescription = db.prescriptions.get(hold["prescription_id"])
    if prescription is None or prescription["status"] != "VERIFIED_ACTIVE":
        raise ApiError("ERR_PRESCRIPTION_NOT_VERIFIED")
    for dispute in db.prescriber_disputes.values():
        if dispute["prescription_id"] == hold["prescription_id"] and dispute["status"] == "OPEN":
            raise ApiError("ERR_OPEN_DISPUTE_BLOCKS_RELEASE")
    hold["status"] = "RELEASED"
    hold["released_by_user_id"] = user_id
    touch(hold)
    append_event(
        hold["prescription_id"], "HOLD_RELEASED", "ReorderHold", hold["id"], (role, user_id)
    )
    reconcile_customer_id(hold["customer_id"])
    return object_response(hold)


@bp.post("/reorder-holds/<hold_id>/escalate")
def escalate_reorder_hold(hold_id):
    user_id, role = identity()
    body = parse_body({"escalated_reason": {"type": "string", "required": True}})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    hold = lookup("reorder_hold", hold_id)
    if hold["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    hold["status"] = "ESCALATED"
    hold["escalated_reason"] = body["escalated_reason"]
    touch(hold)
    append_event(
        hold["prescription_id"], "HOLD_ESCALATED", "ReorderHold", hold["id"], (role, user_id)
    )
    reconcile_customer_id(hold["customer_id"])
    return object_response(hold)


# ------------------------------------------------------------ auto-reorder schedules


@bp.post("/auto-reorder-schedules")
def create_auto_reorder_schedule():
    user_id, role = identity()
    body = parse_body(
        {
            "customer_id": {"type": "uuid", "required": True},
            "prescription_id": {"type": "uuid", "required": True},
            "product_id": {"type": "uuid", "required": True},
            "boxes_per_run": {"type": "int", "required": True, "min": 1},
            "anchor_date": {"type": "date", "required": True},
            "cadence_basis": {"type": "enum", "values": CADENCE_BASES, "default": "NOMINAL"},
            "observed_days_per_box": {"type": "int", "min": 1},
        }
    )
    if body["cadence_basis"] == "USAGE_ADJUSTED" and body["observed_days_per_box"] is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "USAGE_ADJUSTED cadence requires observed_days_per_box."
        )
    require_role(role, [ROLE_CUSTOMER, ROLE_ADMIN])
    customer = lookup("customer", body["customer_id"])
    prescription = lookup("prescription", body["prescription_id"])
    product = lookup("product", body["product_id"])
    require_owner(role, user_id, customer["id"])
    if prescription["status"] != "VERIFIED_ACTIVE":
        raise ApiError("ERR_PRESCRIPTION_NOT_VERIFIED")
    if product["status"] == "INACTIVE":
        raise ApiError("ERR_PRODUCT_INACTIVE")
    cadence_days = calc.cadence_days_for(
        product, body["boxes_per_run"], body["cadence_basis"], body["observed_days_per_box"]
    )
    row = make_row(
        {
            "customer_id": body["customer_id"],
            "prescription_id": body["prescription_id"],
            "product_id": body["product_id"],
            "boxes_per_run": body["boxes_per_run"],
            "cadence_basis": body["cadence_basis"],
            "observed_days_per_box": body["observed_days_per_box"],
            "cadence_days": cadence_days,
            "anchor_date": body["anchor_date"],
            "next_run_at": calc.run_instant(body["anchor_date"], cadence_days),
            "consecutive_skip_count": 0,
            "pause_reason": None,
            "status": "ACTIVE",
        }
    )
    db.auto_reorder_schedules[row["id"]] = row
    reconcile_customer_id(body["customer_id"])
    return object_response(row, 201)


@bp.get("/auto-reorder-schedules/<schedule_id>")
def get_auto_reorder_schedule(schedule_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_FULFILLMENT, ROLE_CUSTOMER])
    schedule = lookup("schedule", schedule_id)
    require_owner(role, user_id, schedule["customer_id"])
    return object_response(schedule)


@bp.get("/auto-reorder-schedules")
def list_auto_reorder_schedules():
    user_id, role = identity()
    filters = parse_query(
        {
            "customer_id": {"type": "string"},
            "prescription_id": {"type": "string"},
            "product_id": {"type": "string"},
            "status": {"type": "enum", "values": SCHEDULE_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_FULFILLMENT, ROLE_CUSTOMER])
    rows = list(db.auto_reorder_schedules.values())
    if role == ROLE_CUSTOMER:
        rows = [r for r in rows if r["customer_id"] == user_id]
    for field in ("customer_id", "prescription_id", "product_id", "status"):
        if filters[field]:
            rows = [r for r in rows if r[field] == filters[field]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/auto-reorder-schedules/<schedule_id>/pause")
def pause_auto_reorder_schedule(schedule_id):
    user_id, role = identity()
    parse_body({})
    require_role(role, [ROLE_CUSTOMER, ROLE_ADMIN])
    schedule = lookup("schedule", schedule_id)
    require_owner(role, user_id, schedule["customer_id"])
    if schedule["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    schedule["status"] = "PAUSED"
    schedule["pause_reason"] = "CUSTOMER_REQUEST"
    touch(schedule)
    reconcile_customer_id(schedule["customer_id"])
    return object_response(schedule)


@bp.post("/auto-reorder-schedules/<schedule_id>/resume")
def resume_auto_reorder_schedule(schedule_id):
    user_id, role = identity()
    parse_body({})
    require_role(role, [ROLE_CUSTOMER, ROLE_ADMIN])
    schedule = lookup("schedule", schedule_id)
    require_owner(role, user_id, schedule["customer_id"])
    if schedule["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    prescription = db.prescriptions.get(schedule["prescription_id"])
    if prescription is None or prescription["status"] != "VERIFIED_ACTIVE":
        raise ApiError("ERR_PRESCRIPTION_NOT_VERIFIED")
    if has_open_hold(schedule["customer_id"]):
        raise ApiError("ERR_HOLD_OPEN_BLOCKS_ACTION")
    schedule["status"] = "ACTIVE"
    schedule["pause_reason"] = None
    schedule["consecutive_skip_count"] = 0
    touch(schedule)
    reconcile_customer_id(schedule["customer_id"])
    return object_response(schedule)


@bp.post("/auto-reorder-schedules/<schedule_id>/cancel")
def cancel_auto_reorder_schedule(schedule_id):
    user_id, role = identity()
    parse_body({})
    require_role(role, [ROLE_CUSTOMER, ROLE_ADMIN])
    schedule = lookup("schedule", schedule_id)
    require_owner(role, user_id, schedule["customer_id"])
    if schedule["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    schedule["status"] = "CANCELLED"
    touch(schedule)
    reconcile_customer_id(schedule["customer_id"])
    return object_response(schedule)


@bp.post("/fulfillment/auto-reorder-run")
def run_auto_reorder():
    _, role = identity()
    parse_body({})
    require_role(role, [ROLE_FULFILLMENT, ROLE_ADMIN])
    return object_response(auto_reorder_run())
