"""Queue tickets: booking, confirm gates, cancel, preempt, requeue (PRD §3.4)."""

from decimal import Decimal

from flask import Blueprint, request

from db import current_date, parse_date, public, sort_by_creation, stamp_new, store, touch
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import check_grower_on_ticket, get_lot, get_ticket, get_unit, scope_by_lot_for_grower
from services.calculations import DRYER_INTAKE_LIMIT_PCT, committed_bushels, drying_charge, find_schedule
from validation import get_body, paginate, req_date, req_int

bp = Blueprint("tickets", __name__)

READ_ROLES = {"ElevatorManager", "Grower", "DryerOperator"}
TICKET_TERMINAL = {"CANCELLED", "EXPIRED"}


def _lot_for(ticket):
    return store.lots.get(ticket["lot_id"])


@bp.post("/queue-tickets")
def create_ticket():
    ctx = get_ctx()
    require_roles(ctx, {"Grower", "ElevatorManager"})
    body = get_body()
    # priority 4: body FK existence (lot_id then unit_id, input order)
    lot = None
    if body.get("lot_id") is not None:
        lot = get_lot(body["lot_id"])
    if body.get("unit_id") is not None:
        get_unit(body["unit_id"])
    # priority 3: grower books only on own account's lots
    if lot is not None and ctx["role"] == "Grower" and lot["customer_id"] != ctx["user_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Grower acting on a resource owned by another customer")
    # priority 5: shape
    lot_id = body.get("lot_id")
    if not isinstance(lot_id, str) or not lot_id:
        raise_err("ERR_INVALID_REQUEST", "Field lot_id is required")
    unit_id = body.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise_err("ERR_INVALID_REQUEST", "Field unit_id is required")
    window_date = req_date(body, "window_date")
    requested = req_int(body, "requested_bushels")  # value sign checked at priority 10
    # priority 6: lot state must permit booking
    if lot["status"] == "DAMAGE_HOLD":
        raise_err("ERR_LOT_ON_DAMAGE_HOLD", "Operation blocked while lot is in DAMAGE_HOLD")
    if lot["status"] not in ("RECEIVED", "TESTED"):
        raise_err("ERR_INVALID_STATE", "Lot state does not permit booking dryer time")
    # priority 10: window not in past, bushels positive, target below certified intake
    if parse_date(window_date) < current_date():
        raise_err("ERR_TICKET_WINDOW_INVALID", "window_date is in the past")
    if requested <= 0:
        raise_err("ERR_TICKET_WINDOW_INVALID", "requested_bushels must be positive")
    if lot["intake_moisture_pct"] is not None and lot["target_moisture_pct"] >= lot["intake_moisture_pct"]:
        raise_err("ERR_TARGET_MOISTURE_INVALID", "Lot target already meets or exceeds its certified intake moisture")
    # priority 12: suspension
    customer = store.customers.get(lot["customer_id"])
    if customer is not None and customer["account_status"] == "SUSPENDED":
        raise_err("ERR_CUSTOMER_SUSPENDED", "Ticket create/confirm for a SUSPENDED customer")
    rec = stamp_new(
        {
            "lot_id": lot["id"],
            "unit_id": unit_id,
            "window_date": window_date,
            "requested_bushels": requested,
            "priority_class": customer["priority_class"] if customer else "STANDARD",
            "status": "PENDING",
            "preemption_count": 0,
        }
    )
    store.tickets[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.get("/queue-tickets")
def list_tickets():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = scope_by_lot_for_grower(ctx, list(store.tickets.values()), "lot_id")
    for field in ("lot_id", "unit_id", "window_date", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/queue-tickets/<tid>")
def get_one_ticket(tid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_ticket(tid)
    check_grower_on_ticket(ctx, rec)
    return success(public(rec))


@bp.post("/queue-tickets/<tid>/confirm")
def confirm_ticket(tid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_ticket(tid)
    lot = _lot_for(rec)
    # priority 6: state
    if rec["status"] in TICKET_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Ticket is in a terminal state")
    if rec["status"] != "PENDING":
        raise_err("ERR_INVALID_STATE", "Only a PENDING ticket may be confirmed")
    if lot is None or lot["status"] == "DAMAGE_HOLD":
        raise_err("ERR_LOT_ON_DAMAGE_HOLD", "Operation blocked while lot is in DAMAGE_HOLD")
    if lot["status"] != "TESTED":
        raise_err("ERR_INVALID_STATE", "Lot must be TESTED to confirm a ticket")
    # priority 9: dryer safety
    if Decimal(str(lot["intake_moisture_pct"])) > DRYER_INTAKE_LIMIT_PCT:
        raise_err("ERR_MOISTURE_EXCEEDS_DRYER_LIMIT", "intake_moisture_pct exceeds the 26.0 dryer safety limit")
    # priority 10: window still valid
    if parse_date(rec["window_date"]) < current_date():
        raise_err("ERR_TICKET_WINDOW_INVALID", "window_date is in the past")
    # priority 11: class + total daily capacity (equality at the cap allowed)
    unit = store.units.get(rec["unit_id"])
    standard_committed, total_committed = committed_bushels(rec["unit_id"], rec["window_date"])
    if rec["priority_class"] == "STANDARD":
        if standard_committed + rec["requested_bushels"] > unit["standard_class_cap_bushels"]:
            raise_err("ERR_CAPACITY_EXCEEDED", "Confirmation would breach the standard-class cap")
    if total_committed + rec["requested_bushels"] > unit["daily_capacity_bushels"]:
        raise_err("ERR_CAPACITY_EXCEEDED", "Confirmation would breach the daily total cap")
    # priority 12: fiscal gates
    customer = store.customers.get(lot["customer_id"])
    if customer is not None and customer["account_status"] == "SUSPENDED":
        raise_err("ERR_CUSTOMER_SUSPENDED", "Ticket create/confirm for a SUSPENDED customer")
    schedule = find_schedule(lot["commodity"], parse_date(rec["window_date"]))
    estimate = drying_charge(lot, schedule)["drying_charge_cents"] if schedule is not None else 0
    outstanding = sum(
        inv["amount_due_cents"]
        for inv in store.invoices.values()
        if inv["customer_id"] == lot["customer_id"] and inv["status"] == "ISSUED"
    )
    if customer is not None and estimate + outstanding > customer["credit_limit_cents"]:
        raise_err("ERR_CREDIT_LIMIT_EXCEEDED", "Estimated drying charge plus outstanding dues exceeds credit_limit")
    rec["status"] = "CONFIRMED"
    touch(rec)
    lot["status"] = "QUEUED"
    touch(lot)
    return success(public(rec))


@bp.post("/queue-tickets/<tid>/cancel")
def cancel_ticket(tid):
    ctx = get_ctx()
    require_roles(ctx, {"Grower", "ElevatorManager"})
    rec = get_ticket(tid)
    check_grower_on_ticket(ctx, rec)
    if rec["status"] in TICKET_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Ticket is in a terminal state")
    if rec["status"] == "PENDING":
        rec["status"] = "CANCELLED"
        touch(rec)
        return success(public(rec))
    if rec["status"] == "CONFIRMED":
        rec["status"] = "CANCELLED"
        touch(rec)
        lot = _lot_for(rec)
        if lot is not None and lot["status"] == "QUEUED":
            lot["status"] = "TESTED"
            touch(lot)
        return success(public(rec))
    raise_err("ERR_INVALID_STATE", "Only a PENDING or CONFIRMED ticket may be cancelled")


@bp.post("/queue-tickets/<tid>/preempt")
def preempt_ticket(tid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_ticket(tid)
    if rec["status"] in TICKET_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Ticket is in a terminal state")
    # priority 11: preemption eligibility (not CONFIRMED or not STANDARD)
    if rec["status"] != "CONFIRMED" or rec["priority_class"] != "STANDARD":
        raise_err("ERR_PREEMPTION_NOT_ALLOWED", "Preempt target not CONFIRMED or not STANDARD class")
    rec["status"] = "PREEMPTED"
    rec["preemption_count"] += 1
    touch(rec)
    lot = _lot_for(rec)
    if lot is not None and lot["status"] == "QUEUED":
        lot["status"] = "TESTED"
        touch(lot)
    return success(public(rec))


@bp.post("/queue-tickets/<tid>/requeue")
def requeue_ticket(tid):
    ctx = get_ctx()
    require_roles(ctx, {"Grower", "ElevatorManager"})
    rec = get_ticket(tid)
    check_grower_on_ticket(ctx, rec)
    if rec["status"] in TICKET_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Ticket is in a terminal state")
    if rec["status"] != "PREEMPTED" or rec["preemption_count"] >= 2:
        raise_err("ERR_INVALID_STATE", "Only a PREEMPTED ticket with fewer than two preemptions may requeue")
    rec["status"] = "PENDING"
    touch(rec)
    return success(public(rec))
