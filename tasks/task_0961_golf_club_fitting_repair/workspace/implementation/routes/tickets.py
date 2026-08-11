"""Repair ticket endpoints (work + payment parallel dimensions)."""
from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_pagination, apply_pagination
from services.calculations import repair_quote, recompute_credit_balance
from services.common import (
    new_entity, touch, get_ticket, get_customer, get_component_item,
    check_ownership, check_create_ownership, append_ledger_entry,
)
from services.serializers import serialize_repair_ticket
from services.sweeps import allocation_sweep

bp = Blueprint("tickets", __name__)

READ_ROLES = {"Customer", "RepairTechnician", "ShopManager"}
SERVICE_TYPES = {"REGRIP", "RESHAFT", "LOFT_LIE_ADJUST"}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/repair-tickets")
def create_ticket():
    user_id, role = get_auth()
    require_role(role, {"Customer", "RepairTechnician"})
    data = _body()
    customer_id = data.get("customer_id")
    club_description = data.get("club_description")
    service_type = data.get("service_type")
    rush = data.get("rush", False)
    shaft_item_id = data.get("shaft_item_id")

    # Body shape validation (priority 3)
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise_err("ERR_VALIDATION", "customer_id is required")
    if not isinstance(club_description, str):
        raise_err("ERR_VALIDATION", "club_description is required")
    if service_type not in SERVICE_TYPES:
        raise_err("ERR_VALIDATION", "invalid service_type")
    if not isinstance(rush, bool):
        raise_err("ERR_VALIDATION", "rush must be a boolean")
    if shaft_item_id is not None and (
            not isinstance(shaft_item_id, str) or not shaft_item_id.strip()):
        raise_err("ERR_VALIDATION", "shaft_item_id must be a string id")

    # Existence of body FK ids (priority 4)
    get_customer(customer_id)
    shaft_item = None
    if shaft_item_id is not None:
        shaft_item = get_component_item(shaft_item_id)

    # Ownership (priority 5)
    check_create_ownership(customer_id, user_id, role)

    # Structural constraint (priority 11): reshaft requires a SHAFT item
    if service_type == "RESHAFT":
        if shaft_item_id is None or shaft_item["component_type"] != "SHAFT":
            raise_err("ERR_RESHAFT_REQUIRES_SHAFT_ITEM",
                      "RESHAFT requires shaft_item_id referencing a SHAFT item")

    t = new_entity()
    quoted_total_cents, promised_at, deposit_cents = repair_quote(
        service_type, rush, t["created_at"]
    )
    t.update({
        "customer_id": customer_id,
        "club_description": club_description,
        "service_type": service_type,
        "rush": rush,
        "shaft_item_id": shaft_item_id if service_type == "RESHAFT" else shaft_item_id,
        "quoted_total_cents": quoted_total_cents,
        "promised_at": promised_at,
        "deposit_cents": deposit_cents,
        "work_status": "QUOTED",
        "payment_status": "UNPAID",
        "rework_count": 0,
        "picked_up_at": None,
        # Internal accounting: amounts paid by CREDIT (for refunds)
        "_credit_paid_cents": 0,
    })
    db.repair_tickets[t["id"]] = t
    return success_response(serialize_repair_ticket(t), status=201)


@bp.get("/repair-tickets/<tid>")
def read_ticket(tid):
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    t = get_ticket(tid)
    check_ownership(t, user_id, role)
    return success_response(serialize_repair_ticket(t))


@bp.get("/repair-tickets")
def list_tickets():
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.repair_tickets.values())
    if role == "Customer":
        items = [t for t in items if t["customer_id"] == user_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [t for t in items
                 if t["work_status"] == status_filter or t["payment_status"] == status_filter]
    for field in ("customer_id", "shaft_item_id"):
        val = request.args.get(field)
        if val is not None:
            items = [t for t in items if t.get(field) == val]
    items.sort(key=lambda t: t["created_at"])
    page, pagination = apply_pagination(items, limit, offset)
    return success_response(
        [serialize_repair_ticket(t) for t in page],
        response_type="array", pagination=pagination,
    )


@bp.post("/repair-tickets/<tid>/approve")
def approve_ticket(tid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    t = get_ticket(tid)
    check_ownership(t, user_id, role)
    if t["work_status"] != "QUOTED":
        raise_err("ERR_TICKET_NOT_QUOTED", "approve called on a ticket not in QUOTED")
    customer = db.customers[t["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise_err("ERR_CUSTOMER_SUSPENDED", "customer is suspended")
    t["work_status"] = "APPROVED"
    touch(t)
    return success_response(serialize_repair_ticket(t))


@bp.post("/repair-tickets/<tid>/start-work")
def start_work_ticket(tid):
    user_id, role = get_auth()
    require_role(role, {"RepairTechnician"})
    t = get_ticket(tid)
    if t["work_status"] != "APPROVED":
        raise_err("ERR_TICKET_NOT_APPROVED", "start-work called on a ticket not in APPROVED")
    # Fiscal: deposit before work
    if t["payment_status"] not in ("DEPOSIT_PAID", "PAID"):
        raise_err("ERR_DEPOSIT_REQUIRED", "deposit must be paid before work starts")
    # Structural: shaft stock for reshafts
    if t["shaft_item_id"] is not None:
        item = db.component_items[t["shaft_item_id"]]
        if item["stock_on_hand"] < 1:
            raise_err("ERR_COMPONENT_SHORTAGE", "required shaft has no stock on hand")
        item["stock_on_hand"] -= 1
        item["stock_reserved"] += 1
        touch(item)
    t["work_status"] = "IN_PROGRESS"
    touch(t)
    return success_response(serialize_repair_ticket(t))


@bp.post("/repair-tickets/<tid>/submit-qc")
def submit_qc_ticket(tid):
    user_id, role = get_auth()
    require_role(role, {"RepairTechnician"})
    data = _body()
    passed = data.get("passed")
    if not isinstance(passed, bool):
        raise_err("ERR_VALIDATION", "passed must be a boolean")
    t = get_ticket(tid)
    if t["work_status"] != "IN_PROGRESS":
        raise_err("ERR_TICKET_NOT_IN_PROGRESS",
                  "submit-qc called on a ticket not in IN_PROGRESS")
    if passed:
        if t["shaft_item_id"] is not None:
            item = db.component_items[t["shaft_item_id"]]
            item["stock_reserved"] -= 1
            item["consumed_total"] += 1
            touch(item)
        t["work_status"] = "READY"
    else:
        t["rework_count"] += 1
    touch(t)
    return success_response(serialize_repair_ticket(t))


@bp.post("/repair-tickets/<tid>/pickup")
def pickup_ticket(tid):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RepairTechnician"})
    t = get_ticket(tid)
    check_ownership(t, user_id, role)
    if t["work_status"] != "READY":
        raise_err("ERR_TICKET_NOT_READY", "pickup called on a ticket not in READY")
    if t["payment_status"] != "PAID":
        raise_err("ERR_TICKET_UNPAID", "ticket must be fully paid before pickup")
    t["work_status"] = "PICKED_UP"
    t["picked_up_at"] = db.logical_now
    touch(t)
    return success_response(serialize_repair_ticket(t))


@bp.post("/repair-tickets/<tid>/cancel")
def cancel_ticket(tid):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RepairTechnician"})
    t = get_ticket(tid)
    check_ownership(t, user_id, role)
    if t["work_status"] not in ("QUOTED", "APPROVED", "IN_PROGRESS"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "cancel is not defined from the ticket's current state")
    released_shaft = False
    # Refund CREDIT payments
    if t["payment_status"] in ("DEPOSIT_PAID", "PAID"):
        if t["_credit_paid_cents"] > 0:
            append_ledger_entry(t["customer_id"], t["_credit_paid_cents"],
                                "TICKET_REFUND", t["id"])
            recompute_credit_balance(t["customer_id"])
            touch(db.customers[t["customer_id"]])
        t["payment_status"] = "REFUNDED"
    # Release shaft reservation held from IN_PROGRESS
    if t["work_status"] == "IN_PROGRESS" and t["shaft_item_id"] is not None:
        item = db.component_items[t["shaft_item_id"]]
        item["stock_reserved"] -= 1
        item["stock_on_hand"] += 1
        touch(item)
        released_shaft = True
    t["work_status"] = "CANCELLED"
    touch(t)
    if released_shaft:
        allocation_sweep()
    return success_response(serialize_repair_ticket(t))


@bp.post("/repair-tickets/<tid>/payments")
def pay_ticket(tid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    data = _body()
    kind = data.get("kind")
    method = data.get("method")
    if kind not in ("DEPOSIT", "BALANCE"):
        raise_err("ERR_VALIDATION", "kind must be DEPOSIT or BALANCE")
    if method not in ("CREDIT", "EXTERNAL"):
        raise_err("ERR_VALIDATION", "method must be CREDIT or EXTERNAL")
    t = get_ticket(tid)
    check_ownership(t, user_id, role)
    # State guard: payments refused unless work_status is active
    if t["work_status"] not in ("QUOTED", "APPROVED", "IN_PROGRESS", "READY"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "payments not accepted in the ticket's current work state")
    # Payment sequence
    if t["payment_status"] == "UNPAID":
        if kind != "DEPOSIT":
            raise_err("ERR_PAYMENT_SEQUENCE", "DEPOSIT expected while UNPAID")
        amount = t["deposit_cents"]
        next_status = "DEPOSIT_PAID"
    elif t["payment_status"] == "DEPOSIT_PAID":
        if kind != "BALANCE":
            raise_err("ERR_PAYMENT_SEQUENCE", "BALANCE expected while DEPOSIT_PAID")
        amount = t["quoted_total_cents"] - t["deposit_cents"]
        next_status = "PAID"
    else:
        raise_err("ERR_PAYMENT_SEQUENCE",
                  "no payment accepted while PAID or REFUNDED")
    # Credit sufficiency
    customer = db.customers[t["customer_id"]]
    if method == "CREDIT":
        if customer["credit_balance_cents"] < amount:
            raise_err("ERR_INSUFFICIENT_CREDIT", "credit balance does not cover the payment")
        append_ledger_entry(t["customer_id"], -amount, "TICKET_PAYMENT", t["id"])
        recompute_credit_balance(t["customer_id"])
        touch(customer)
        t["_credit_paid_cents"] += amount
    t["payment_status"] = next_status
    touch(t)
    return success_response(serialize_repair_ticket(t))
