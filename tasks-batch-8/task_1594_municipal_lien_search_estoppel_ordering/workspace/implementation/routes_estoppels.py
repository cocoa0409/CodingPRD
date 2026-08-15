"""EstoppelOrder routes: place (initial/renewal), receive, cancel."""
from flask import Blueprint

import db
import services
from db import touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_QUOTE_EXCEEDS_STATUTORY_CAP,
)
from helpers import body, is_int, _MISSING
from middleware import require_roles, require_any_role
from response import success

bp = Blueprint("estoppel_orders", __name__)


def get_estoppel_or_404(eid):
    e = db.estoppel_orders.get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Estoppel order not found")
    return e


@bp.get("/estoppel-orders/<eid>")
def get_estoppel(eid):
    require_any_role()
    return success(services.ser_estoppel(get_estoppel_or_404(eid)))


@bp.post("/estoppel-orders/<eid>/place")
def place_estoppel(eid):
    require_roles("ResearchAnalyst")
    e = get_estoppel_or_404(eid)
    if e["status"] not in ("DRAFT", "EXPIRED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Estoppel in {e['status']} cannot be placed",
        )
    b = body()
    fee = b.get("fee_quoted_cents", _MISSING)
    if fee is _MISSING or not is_int(fee):
        raise ApiError(ERR_INVALID_REQUEST, 400, "fee_quoted_cents is required and must be an integer")
    if fee <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "fee_quoted_cents must be greater than zero")
    order = db.search_orders.get(e["search_order_id"])
    statute = db.statutes.get(order["statute_id"]) if order else None
    cap = statute["estoppel_fee_cap_cents"] if statute else 0
    if fee > cap:
        raise ApiError(
            ERR_QUOTE_EXCEEDS_STATUTORY_CAP, 422,
            "fee_quoted_cents exceeds the pinned statute fee cap",
        )
    if e["status"] == "EXPIRED":
        # Renewal: clear the previous receipt's evidence.
        e["renewal_count"] += 1
        e["received_at"] = None
        e["payoff_amount_cents"] = None
        e["valid_through"] = None
        e["late_delivery"] = None
        e["current_fee_cents"] = 0
    e["status"] = "ORDERED"
    e["fee_quoted_cents"] = fee
    e["ordered_at"] = db.now()
    response_days = statute["estoppel_response_days"] if statute else 0
    e["statutory_due_at"] = services.statutory_due_at(e["ordered_at"], response_days)
    touch(e)
    return success(services.ser_estoppel(e))


@bp.post("/estoppel-orders/<eid>/receive")
def receive_estoppel(eid):
    require_roles("ResearchAnalyst")
    e = get_estoppel_or_404(eid)
    if e["status"] not in ("ORDERED", "OVERDUE"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Estoppel in {e['status']} cannot be received",
        )
    b = body()
    payoff = b.get("payoff_amount_cents", _MISSING)
    if payoff is _MISSING or not is_int(payoff):
        raise ApiError(ERR_INVALID_REQUEST, 400, "payoff_amount_cents is required and must be an integer")
    if payoff < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "payoff_amount_cents must be zero or greater")
    order = db.search_orders.get(e["search_order_id"])
    statute = db.statutes.get(order["statute_id"]) if order else None
    assoc = db.associations.get(e["association_id"])
    received_at = db.now()
    due_date = e["statutory_due_at"].date() if e["statutory_due_at"] else None
    late = due_date is not None and received_at.date() > due_date
    if late:
        # Statutory fee forfeiture on late response.
        current_fee = 0
    else:
        cap = statute["estoppel_fee_cap_cents"] if statute else 0
        current_fee = min(e["fee_quoted_cents"] or 0, cap)
    e["received_at"] = received_at
    e["late_delivery"] = late
    e["current_fee_cents"] = current_fee
    e["lifetime_fees_cents"] += current_fee
    e["payoff_amount_cents"] = payoff
    validity_days = assoc["estoppel_validity_days"] if assoc else 0
    e["valid_through"] = services.estoppel_valid_through(received_at, validity_days)
    e["status"] = "RECEIVED"
    touch(e)
    if order is not None:
        touch(order)  # order totals advanced by the receipt
    return success(services.ser_estoppel(e))


@bp.post("/estoppel-orders/<eid>/cancel")
def cancel_estoppel(eid):
    require_roles("ResearchAnalyst")
    e = get_estoppel_or_404(eid)
    if e["status"] not in ("DRAFT", "ORDERED", "OVERDUE"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Estoppel in {e['status']} cannot be cancelled",
        )
    e["status"] = "CANCELLED"
    touch(e)
    return success(services.ser_estoppel(e))
