"""DeliveryTicket endpoints."""

from decimal import Decimal
from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, r2, r3, to_float, req_body, require_fields, req_int, req_number,
    pagination_params, page_slice, get_or_404, touch, parse_date,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_ticket
from services import (
    recompute_plan_counters, governing_agreement,
    MOISTURE_BASE_PCT, SHRINK_PER_POINT, OVER_DELIVERY_TOLERANCE,
)
from routes.plans import _do_close_plan


bp = Blueprint("tickets", __name__)


@bp.route("/advisory/delivery-tickets", methods=["POST"])
def create_ticket():
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    body = req_body()
    require_fields(body, ["contract_id", "delivery_date", "gross_bushels", "moisture_pct"])
    contract_id = body["contract_id"]
    if not isinstance(contract_id, str):
        raise ApiError("ERR_VALIDATION", "contract_id must be a string", 400)
    delivery_date_raw = body["delivery_date"]
    if not isinstance(delivery_date_raw, str):
        raise ApiError("ERR_VALIDATION", "delivery_date must be a string", 400)
    gross = req_int(body, "gross_bushels", positive=True)
    moisture = req_number(body, "moisture_pct")

    c = DB.contracts.get(contract_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", f"SalesContract not found: {contract_id}", 404)
    check_grower_ownership(user_id, role, c["operation_id"])

    # State: cannot record against DELIVERED contract
    if c["fulfillment_status"] == "DELIVERED":
        raise ApiError("ERR_CONTRACT_FULLY_DELIVERED", "Contract is fully delivered", 409)
    if c["fulfillment_status"] in {"CANCELLED", "DEFAULTED"}:
        raise ApiError("ERR_INVALID_STATE", f"Contract in state {c['fulfillment_status']} cannot accept tickets", 409)

    # Delivery date inside [start, end)
    dd = parse_date(delivery_date_raw)
    dws = parse_date(c["delivery_window_start"])
    dwe = parse_date(c["delivery_window_end"])
    if not (dws <= dd < dwe):
        raise ApiError("ERR_DELIVERY_OUTSIDE_WINDOW", "delivery_date outside the contract delivery window", 409)

    shrink = max(Decimal("0"), moisture - MOISTURE_BASE_PCT) * SHRINK_PER_POINT
    net = r3(D(gross) * (Decimal("1") - shrink))

    tid = db.new_id()
    now = db.now_iso()
    ticket = {
        "id": tid,
        "contract_id": contract_id,
        "delivery_date": delivery_date_raw,
        "gross_bushels": gross,
        "moisture_pct": moisture,
        "shrink_pct": shrink,
        "net_bushels": net,
        "ticket_value_dollars": None,
        "status": "RECORDED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.tickets[tid] = ticket
    return success_object(ser_ticket(ticket), status=201)


@bp.route("/advisory/delivery-tickets/<ticketId>", methods=["GET"])
def get_ticket(ticketId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    t = get_or_404(DB.tickets, ticketId, "DeliveryTicket")
    c = DB.contracts.get(t["contract_id"])
    if c:
        check_grower_ownership(user_id, role, c["operation_id"])
    return success_object(ser_ticket(t))


@bp.route("/advisory/delivery-tickets", methods=["GET"])
def list_tickets():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    limit, offset = pagination_params()
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    items = list(DB.tickets.values())
    if role == "Grower":
        items = [
            t for t in items
            if (DB.contracts.get(t["contract_id"]) or {}).get("operation_id") == user_id
        ]
    if contract_id is not None:
        items = [t for t in items if t["contract_id"] == contract_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda t: t["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_ticket(t) for t in slice_], limit, offset, total)


def _evaluate_plan_auto_close(plan):
    """After confirmation: if uncommitted == 0 AND all plan contracts DELIVERED -> close."""
    if plan["status"] not in {"ACTIVE", "SUSPENDED"}:
        return
    if plan["uncommitted_bushels"] != 0:
        return
    contracts = [c for c in DB.contracts.values() if c["plan_id"] == plan["id"]]
    if contracts and all(c["fulfillment_status"] == "DELIVERED" for c in contracts):
        _do_close_plan(plan)


@bp.route("/advisory/delivery-tickets/<ticketId>/confirm", methods=["POST"])
def confirm_ticket(ticketId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    t = get_or_404(DB.tickets, ticketId, "DeliveryTicket")
    if t["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", f"Ticket in state {t['status']} cannot be confirmed", 409)
    c = DB.contracts[t["contract_id"]]
    # fulfillment gate
    if c["fulfillment_status"] == "DELIVERED":
        raise ApiError("ERR_CONTRACT_FULLY_DELIVERED", "Contract is fully delivered", 409)
    if c["fulfillment_status"] not in {"OPEN", "PARTIALLY_DELIVERED"}:
        raise ApiError("ERR_INVALID_STATE", f"Contract in state {c['fulfillment_status']} cannot be confirmed against", 409)
    # pricing gate
    if c["pricing_status"] != "PRICED":
        raise ApiError("ERR_CONTRACT_NOT_PRICED", "Contract pricing_status must be PRICED", 409)
    # over-delivery tolerance
    new_delivered = D(c["delivered_bushels"]) + D(t["net_bushels"])
    max_allowed = int((D(c["bushels"]) * OVER_DELIVERY_TOLERANCE).to_integral_value(rounding="ROUND_FLOOR"))
    if new_delivered > max_allowed:
        raise ApiError("ERR_OVER_DELIVERY_EXCEEDED", "Confirmation exceeds over-delivery tolerance", 409)

    # Apply
    ticket_value = r2(D(t["net_bushels"]) * D(c["effective_price"]))
    t["ticket_value_dollars"] = ticket_value
    t["status"] = "CONFIRMED"
    touch(t)

    c["delivered_bushels"] = D(c["delivered_bushels"]) + D(t["net_bushels"])
    c["settled_value_dollars"] = D(c["settled_value_dollars"]) + ticket_value
    # fulfillment auto-transition
    if D(c["delivered_bushels"]) >= D(c["bushels"]):
        c["fulfillment_status"] = "DELIVERED"
    elif D(c["delivered_bushels"]) > 0:
        c["fulfillment_status"] = "PARTIALLY_DELIVERED"
    touch(c)

    # Agreement billable accrual (most recent ACTIVE agreement)
    agreement = governing_agreement(c["operation_id"])
    if agreement is not None:
        agreement["billable_bushels_accrued"] = D(agreement.get("billable_bushels_accrued") or 0) + D(t["net_bushels"])
        touch(agreement)

    # Plan cascade
    plan = DB.plans[c["plan_id"]]
    recompute_plan_counters(plan)
    _evaluate_plan_auto_close(plan)
    return success_object(ser_ticket(t))


@bp.route("/advisory/delivery-tickets/<ticketId>/void", methods=["POST"])
def void_ticket(ticketId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    t = get_or_404(DB.tickets, ticketId, "DeliveryTicket")
    if t["status"] not in {"RECORDED", "CONFIRMED"}:
        raise ApiError("ERR_INVALID_STATE", f"Ticket in state {t['status']} cannot be voided", 409)
    was_confirmed = t["status"] == "CONFIRMED"
    prior_value = t.get("ticket_value_dollars")
    t["status"] = "VOIDED"
    touch(t)
    if was_confirmed:
        c = DB.contracts[t["contract_id"]]
        c["delivered_bushels"] = D(c["delivered_bushels"]) - D(t["net_bushels"])
        c["settled_value_dollars"] = D(c["settled_value_dollars"]) - D(prior_value or 0)
        # Revert fulfillment: DELIVERED -> PARTIALLY_DELIVERED, PARTIALLY_DELIVERED -> OPEN as quantities dictate
        if c["fulfillment_status"] == "DELIVERED":
            c["fulfillment_status"] = "PARTIALLY_DELIVERED"
        elif c["fulfillment_status"] == "PARTIALLY_DELIVERED":
            if D(c["delivered_bushels"]) <= 0:
                c["fulfillment_status"] = "OPEN"
        touch(c)
        agreement = governing_agreement(c["operation_id"])
        if agreement is not None:
            agreement["billable_bushels_accrued"] = D(agreement.get("billable_bushels_accrued") or 0) - D(t["net_bushels"])
            touch(agreement)
        plan = DB.plans[c["plan_id"]]
        recompute_plan_counters(plan)
        # CLOSED plan stays CLOSED: do not evaluate auto-close on void
    return success_object(ser_ticket(t))
