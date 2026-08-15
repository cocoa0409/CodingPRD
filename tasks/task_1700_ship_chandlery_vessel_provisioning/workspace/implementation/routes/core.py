"""Logical clock, ShipAgent, VesselCall routes."""
from flask import Blueprint, request

import db
from db import stamp_new, touch, _parse_iso, _format_iso
from errors import (err_agent_not_found, err_vessel_call_not_found,
                    err_vessel_call_not_arrivable, err_vessel_call_not_in_port,
                    err_vessel_call_not_cancellable, err_customs_state_invalid,
                    err_invalid_request)
from middleware import require_roles, require_any_authenticated
from response import success_object, success_list, parse_pagination
from services.exposure import recompute_agent_exposure
from services.stock import release_allocations
from services.validate import (get_body, req_string, req_int, req_bool,
                               req_datetime, req_enum)

bp = Blueprint("core", __name__)

CURRENCIES = ("USD", "EUR", "GBP", "SGD")


# ---------------------------------------------------------------------------
# Logical clock (test-driving; ChandlerOpsManager only)
# ---------------------------------------------------------------------------

@bp.route("/chandlery/_clock/set_current_utc", methods=["POST"])
@require_roles("ChandlerOpsManager")
def set_clock(user_id, role):
    body = get_body()
    target = body.get("to_iso8601")
    if not isinstance(target, str):
        raise err_invalid_request("missing or invalid field: to_iso8601")
    try:
        new_now = db.CLOCK.set(target)
    except Exception:
        raise err_invalid_request("invalid ISO8601 datetime: to_iso8601")
    return success_object({"now_iso8601": _format_iso(new_now)}, status=200)


# ---------------------------------------------------------------------------
# ShipAgent
# ---------------------------------------------------------------------------

def agent_view(agent):
    # exposures recomputed continuously; refresh on read for consistency
    recompute_agent_exposure(agent["id"])
    return agent


@bp.route("/chandlery/ship-agents", methods=["POST"])
@require_roles("FinanceController")
def create_agent(user_id, role):
    body = get_body()
    agent = {
        "name": req_string(body, "name"),
        "settlement_currency": req_enum(body, "settlement_currency", CURRENCIES),
        "credit_limit_cents": req_int(body, "credit_limit_cents", minimum=0),
        "payment_terms_days": req_int(body, "payment_terms_days", minimum=0),
        "committed_exposure_cents": 0,
        "settled_exposure_cents": 0,
    }
    stamp_new(agent)
    db.ship_agents[agent["id"]] = agent
    return success_object(agent, status=201)


@bp.route("/chandlery/ship-agents/<agent_id>", methods=["GET"])
@require_any_authenticated
def get_agent(user_id, role, agent_id):
    agent = db.ship_agents.get(agent_id)
    if agent is None:
        raise err_agent_not_found()
    return success_object(agent_view(agent))


@bp.route("/chandlery/ship-agents/<agent_id>/vessel-calls", methods=["GET"])
@require_any_authenticated
def list_agent_vessel_calls(user_id, role, agent_id):
    if agent_id not in db.ship_agents:
        raise err_agent_not_found()
    items = [vc for vc in db.vessel_calls.values() if vc["agent_id"] == agent_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


@bp.route("/chandlery/ship-agents/<agent_id>/orders", methods=["GET"])
@require_any_authenticated
def list_agent_orders(user_id, role, agent_id):
    if agent_id not in db.ship_agents:
        raise err_agent_not_found()
    items = [o for o in db.orders.values() if o["agent_id"] == agent_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


# ---------------------------------------------------------------------------
# VesselCall
# ---------------------------------------------------------------------------

def vessel_call_view(vc):
    return vc


@bp.route("/chandlery/vessel-calls", methods=["POST"])
@require_roles("ChandlerOpsManager")
def create_vessel_call(user_id, role):
    body = get_body()
    agent_id = body.get("agent_id")
    if not isinstance(agent_id, str) or agent_id.strip() == "":
        raise err_invalid_request("missing or invalid field: agent_id")
    # existence: referenced agent must exist (path/body-referenced ids exist)
    if agent_id not in db.ship_agents:
        raise err_agent_not_found()
    eta = req_datetime(body, "scheduled_eta")
    etd = req_datetime(body, "scheduled_etd")
    if not (etd > eta):
        raise err_invalid_request("scheduled_etd must be strictly after scheduled_eta")
    vc = {
        "vessel_name": req_string(body, "vessel_name"),
        "imo_number": req_string(body, "imo_number"),
        "agent_id": agent_id,
        "port_code": req_string(body, "port_code"),
        "scheduled_eta": _format_iso(eta),
        "scheduled_etd": _format_iso(etd),
        "actual_eta": None,
        "actual_etd": None,
        "foreign_going": req_bool(body, "foreign_going"),
        "status": "SCHEDULED",
        "customs_clearance_status": "PENDING",
    }
    stamp_new(vc)
    db.vessel_calls[vc["id"]] = vc
    return success_object(vc, status=201)


@bp.route("/chandlery/vessel-calls/<vc_id>", methods=["GET"])
@require_any_authenticated
def get_vessel_call(user_id, role, vc_id):
    vc = db.vessel_calls.get(vc_id)
    if vc is None:
        raise err_vessel_call_not_found()
    return success_object(vessel_call_view(vc))


@bp.route("/chandlery/vessel-calls/<vc_id>/arrive", methods=["POST"])
@require_roles("ChandlerOpsManager")
def arrive_vessel_call(user_id, role, vc_id):
    vc = db.vessel_calls.get(vc_id)
    if vc is None:
        raise err_vessel_call_not_found()
    if vc["status"] != "SCHEDULED":
        raise err_vessel_call_not_arrivable()
    vc["status"] = "IN_PORT"
    vc["actual_eta"] = db.now_iso()
    touch(vc)
    return success_object(vc)


@bp.route("/chandlery/vessel-calls/<vc_id>/depart", methods=["POST"])
@require_roles("ChandlerOpsManager")
def depart_vessel_call(user_id, role, vc_id):
    vc = db.vessel_calls.get(vc_id)
    if vc is None:
        raise err_vessel_call_not_found()
    if vc["status"] != "IN_PORT":
        raise err_vessel_call_not_in_port()
    vc["status"] = "DEPARTED"
    vc["actual_etd"] = db.now_iso()
    touch(vc)

    affected_agents = set()
    # Cascade hop 1 (VesselCall -> Delivery): all non-terminal deliveries of
    # all orders of this call -> FAILED.
    call_orders = [o for o in db.orders.values() if _order_call_id(o) == vc_id]
    for order in call_orders:
        for delivery in db.deliveries.values():
            if delivery["order_id"] == order["id"] and delivery["status"] in (
                    "SCHEDULED", "OUT_FOR_DELIVERY"):
                delivery["status"] = "FAILED"
                touch(delivery)
    # Cascade hop 1 (VesselCall -> Order): OPEN orders -> CANCELLED with
    # release + invoice VOID; PARTIALLY_DELIVERED orders release remainder.
    for order in call_orders:
        if order["fulfillment_status"] == "OPEN":
            order["fulfillment_status"] = "CANCELLED"
            touch(order)
            release_allocations(order)
            # void unpaid ISSUED invoice
            for inv in db.invoices.values():
                if inv["order_id"] == order["id"] and inv["status"] == "ISSUED" \
                        and _invoice_payment_count(inv["id"]) == 0:
                    inv["status"] = "VOID"
                    inv["outstanding_cents"] = _recompute_outstanding(inv)
                    touch(inv)
        elif order["fulfillment_status"] == "PARTIALLY_DELIVERED":
            release_allocations(order)
            touch(order)
        affected_agents.add(order["agent_id"])
    # Cascade hop 3 (Invoice -> ShipAgent): exposures recomputed.
    for agent_id in affected_agents:
        recompute_agent_exposure(agent_id)
    return success_object(vc)


@bp.route("/chandlery/vessel-calls/<vc_id>/cancel", methods=["POST"])
@require_roles("ChandlerOpsManager")
def cancel_vessel_call(user_id, role, vc_id):
    vc = db.vessel_calls.get(vc_id)
    if vc is None:
        raise err_vessel_call_not_found()
    if vc["status"] != "SCHEDULED":
        raise err_vessel_call_not_cancellable()
    vc["status"] = "CANCELLED"
    touch(vc)
    # Cascade: all Requisitions of this call in DRAFT | SUBMITTED | QUOTED -> CLOSED
    for req in db.requisitions.values():
        if req["vessel_call_id"] == vc_id and req["status"] in ("DRAFT", "SUBMITTED", "QUOTED"):
            req["status"] = "CLOSED"
            touch(req)
    return success_object(vc)


@bp.route("/chandlery/vessel-calls/<vc_id>/customs-clearance", methods=["POST"])
@require_roles("PortCustomsOfficer")
def customs_clearance(user_id, role, vc_id):
    vc = db.vessel_calls.get(vc_id)
    if vc is None:
        raise err_vessel_call_not_found()
    body = get_body()
    decision = req_enum(body, "decision", ("CLEARED", "REJECTED"))
    # state: decision merely restating current value is inadmissible
    if decision == vc["customs_clearance_status"]:
        raise err_customs_state_invalid()
    # customs decisions may only occur while status IN {SCHEDULED, IN_PORT}
    if vc["status"] not in ("SCHEDULED", "IN_PORT"):
        raise err_vessel_call_not_in_port()
    vc["customs_clearance_status"] = decision
    touch(vc)
    return success_object(vc)


# ---------------------------------------------------------------------------
# helpers used across route modules
# ---------------------------------------------------------------------------

def _order_call_id(order):
    """Resolve an order's vessel call id via its quotation -> requisition."""
    quotation = db.quotations.get(order.get("quotation_id"))
    if quotation is None:
        return None
    requisition = db.requisitions.get(quotation.get("requisition_id"))
    if requisition is None:
        return None
    return requisition.get("vessel_call_id")


def _invoice_payment_count(invoice_id):
    return sum(1 for p in db.payments.values() if p["invoice_id"] == invoice_id)


def _recompute_outstanding(inv):
    return (inv["total_cents"] - inv["paid_amount_cents"]
            - inv["credited_amount_cents"] - inv["fx_writeoff_cents"])
