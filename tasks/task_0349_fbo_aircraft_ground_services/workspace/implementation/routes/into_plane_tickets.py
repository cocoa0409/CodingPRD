"""IntoPlaneTicket endpoints — reconciliation axis (PRD §3.6)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import (get_json, require_string, require_int,
                     pagination_params, paginate)
from services.calculations import into_plane_reconciliation, variance_pct_to_number

bp = Blueprint("into_plane_tickets", __name__)


def ticket_view(t):
    return {
        "id": t["id"],
        "fuel_order_id": t["fuel_order_id"],
        "delivered_gallons": t["delivered_gallons"],
        "variance_gallons": t["variance_gallons"],
        "variance_pct": t["variance_pct"],
        "outcome": t["outcome"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


@bp.route("/into-plane-tickets", methods=["POST"])
def create_ticket():
    _, role = authenticate()
    require_role(role, {"FuelTech"})
    body = get_json()
    fuel_order_id = require_string(body, "fuel_order_id")
    delivered_gallons = require_int(body, "delivered_gallons", minimum=0)

    order = db.fuel_orders.get(fuel_order_id)
    if order is None:
        raise err(errors.ERR_NOT_FOUND, "Fuel order not found.")

    # State: order must be FUELED and reconciliation NOT_STARTED.
    if order["logistics_status"] != "FUELED" or order["reconciliation_status"] != "NOT_STARTED":
        raise err(errors.ERR_INVALID_STATE,
                  "Order must be FUELED with reconciliation NOT_STARTED.")

    variance_gallons, variance_pct, outcome = into_plane_reconciliation(
        delivered_gallons, order["ordered_gallons"])

    t = db.common_create()
    t.update({
        "fuel_order_id": fuel_order_id,
        "delivered_gallons": delivered_gallons,
        "variance_gallons": variance_gallons,
        "variance_pct": variance_pct_to_number(variance_pct),
        "outcome": outcome,
    })
    db.into_plane_tickets[t["id"]] = t

    # Advance the order's reconciliation axis.
    order["reconciliation_status"] = "RECONCILED" if outcome == "RECONCILED" else "IN_REVIEW"
    db.touch(order)
    return success(ticket_view(t), 201)


@bp.route("/into-plane-tickets/<id>", methods=["GET"])
def get_ticket(id):
    _, role = authenticate()
    require_role(role, {"FuelTech", "BillingClerk", "LineManager"})
    t = db.into_plane_tickets.get(id)
    if t is None:
        raise err(errors.ERR_NOT_FOUND, "Into-plane ticket not found.")
    return success(ticket_view(t), 200)


@bp.route("/into-plane-tickets", methods=["GET"])
def list_tickets():
    _, role = authenticate()
    require_role(role, {"FuelTech", "BillingClerk", "LineManager"})
    limit, offset = pagination_params()
    records = list(db.into_plane_tickets.values())
    f_f = request.args.get("fuel_order_id")
    o_f = request.args.get("outcome")
    if f_f is not None:
        records = [r for r in records if r["fuel_order_id"] == f_f]
    if o_f is not None:
        records = [r for r in records if r["outcome"] == o_f]
    window, total = paginate(records, limit, offset)
    return list_response([ticket_view(r) for r in window], limit, offset, total)
