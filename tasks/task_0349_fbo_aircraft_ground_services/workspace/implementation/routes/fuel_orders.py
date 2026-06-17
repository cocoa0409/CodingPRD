"""FuelOrder endpoints — parallel state machine + pricing (PRD §3.6, §3.2)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import (get_json, require_string, require_int, require_enum,
                     require_bool, pagination_params, paginate)
from services.calculations import fuel_order_cost
from services.derived import compute_invoice_total, recompute_open_invoice_balance

bp = Blueprint("fuel_orders", __name__)


def order_view(o):
    return {
        "id": o["id"],
        "service_visit_id": o["service_visit_id"],
        "aircraft_id": o["aircraft_id"],
        "fuel_contract_id": o["fuel_contract_id"],
        "product": o["product"],
        "ordered_gallons": o["ordered_gallons"],
        "tankering": o["tankering"],
        "logistics_status": o["logistics_status"],
        "reconciliation_status": o["reconciliation_status"],
        "priced_amount_cents": o["priced_amount_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def _owner_operator_id(order):
    visit = db.service_visits.get(order["service_visit_id"])
    return visit["operator_id"] if visit else None


@bp.route("/fuel-orders", methods=["POST"])
def create_order():
    user_id, role = authenticate()
    require_role(role, {"FuelTech", "OpsDispatcher", "Operator"})
    body = get_json()
    service_visit_id = require_string(body, "service_visit_id")
    aircraft_id = require_string(body, "aircraft_id")
    fuel_contract_id = require_string(body, "fuel_contract_id")
    product = require_enum(body, "product", {"JET_A", "AVGAS"})
    ordered_gallons = require_int(body, "ordered_gallons", minimum=1)
    tankering = require_bool(body, "tankering", False)

    # Existence left to right.
    visit = db.service_visits.get(service_visit_id)
    if visit is None:
        raise err(errors.ERR_NOT_FOUND, "Service visit not found.")
    aircraft = db.aircraft.get(aircraft_id)
    if aircraft is None:
        raise err(errors.ERR_NOT_FOUND, "Aircraft not found.")
    contract = db.fuel_contracts.get(fuel_contract_id)
    if contract is None:
        raise err(errors.ERR_NOT_FOUND, "Fuel contract not found.")

    # Ownership for Operator role (own visit).
    if role == "Operator" and user_id != visit["operator_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may order only for its own visits.")

    # Product/operator coherence.
    if not (product == aircraft["fuel_type"]
            and product == contract["product"]
            and contract["operator_id"] == aircraft["operator_id"]):
        raise err(errors.ERR_PRODUCT_MISMATCH, "Product/operator coherence failed.")

    o = db.common_create()
    o.update({
        "service_visit_id": service_visit_id,
        "aircraft_id": aircraft_id,
        "fuel_contract_id": fuel_contract_id,
        "product": product,
        "ordered_gallons": ordered_gallons,
        "tankering": tankering,
        "logistics_status": "REQUESTED",
        "reconciliation_status": "NOT_STARTED",
        "priced_amount_cents": 0,
    })
    db.fuel_orders[o["id"]] = o
    return success(order_view(o), 201)


@bp.route("/fuel-orders/<id>", methods=["GET"])
def get_order(id):
    user_id, role = authenticate()
    require_role(role, {"FuelTech", "OpsDispatcher", "BillingClerk", "LineManager", "Operator"})
    o = db.fuel_orders.get(id)
    if o is None:
        raise err(errors.ERR_NOT_FOUND, "Fuel order not found.")
    if role == "Operator" and user_id != _owner_operator_id(o):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may read only its own orders.")
    return success(order_view(o), 200)


@bp.route("/fuel-orders", methods=["GET"])
def list_orders():
    user_id, role = authenticate()
    require_role(role, {"FuelTech", "OpsDispatcher", "BillingClerk", "LineManager", "Operator"})
    limit, offset = pagination_params()
    records = list(db.fuel_orders.values())
    if role == "Operator":
        records = [r for r in records if _owner_operator_id(r) == user_id]
    v_f = request.args.get("service_visit_id")
    a_f = request.args.get("aircraft_id")
    c_f = request.args.get("fuel_contract_id")
    l_f = request.args.get("logistics_status")
    if v_f is not None:
        records = [r for r in records if r["service_visit_id"] == v_f]
    if a_f is not None:
        records = [r for r in records if r["aircraft_id"] == a_f]
    if c_f is not None:
        records = [r for r in records if r["fuel_contract_id"] == c_f]
    if l_f is not None:
        records = [r for r in records if r["logistics_status"] == l_f]
    window, total = paginate(records, limit, offset)
    return list_response([order_view(r) for r in window], limit, offset, total)


def _price(order, gallons, prev_cumulative):
    """Price `gallons` for `order` using the supplied cumulative baseline.

    PRD §3.2: the engine keys on the operator's `jeta_month_cumulative_gallons` "as it
    stands at dispatch time as the count of gallons already on the books this month" —
    i.e. the cumulative BEFORE this order's own gallons are added (which happens only at
    complete-fueling). The same dispatch-time snapshot is reused when adjust-billing
    re-runs the engine with delivered_gallons, so the marginal tier walk reproduces the
    original pricing context rather than counting this order's own already-fueled gallons.
    """
    contract = db.fuel_contracts.get(order["fuel_contract_id"])
    return fuel_order_cost(
        order["tankering"], gallons,
        contract["base_price_cents_per_gal"],
        contract["tankering_fee_cents_per_gal"],
        order["product"], prev_cumulative,
    )


@bp.route("/fuel-orders/<id>/dispatch", methods=["POST"])
def dispatch(id):
    _, role = authenticate()
    require_role(role, {"FuelTech"})
    o = db.fuel_orders.get(id)
    if o is None:
        raise err(errors.ERR_NOT_FOUND, "Fuel order not found.")
    if o["logistics_status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "dispatch requires REQUESTED logistics status.")
    visit = db.service_visits.get(o["service_visit_id"])
    if visit["status"] not in ("ON_GROUND", "SERVICING"):
        raise err(errors.ERR_VISIT_NOT_SERVICEABLE, "Parent visit must be ON_GROUND or SERVICING.")
    contract = db.fuel_contracts.get(o["fuel_contract_id"])
    aircraft = db.aircraft.get(o["aircraft_id"])
    # Product/operator coherence re-checked at dispatch.
    if not (o["product"] == aircraft["fuel_type"]
            and o["product"] == contract["product"]
            and contract["operator_id"] == aircraft["operator_id"]):
        raise err(errors.ERR_PRODUCT_MISMATCH, "Product/operator coherence failed.")
    if contract["contract_status"] != "ACTIVE":
        raise err(errors.ERR_CONTRACT_EXPIRED, "Fuel contract is expired.")

    # Snapshot the operator's cumulative as it stands at dispatch time (gallons already
    # on the books, BEFORE this order). Reused verbatim by adjust-billing's re-price.
    operator = db.operators.get(_owner_operator_id(o))
    dispatch_cumulative = operator["jeta_month_cumulative_gallons"] if operator else 0
    o["_dispatch_cumulative_gallons"] = dispatch_cumulative
    o["priced_amount_cents"] = _price(o, o["ordered_gallons"], dispatch_cumulative)
    o["logistics_status"] = "DISPATCHED"
    db.touch(o)
    return success(order_view(o), 200)


@bp.route("/fuel-orders/<id>/complete-fueling", methods=["POST"])
def complete_fueling(id):
    _, role = authenticate()
    require_role(role, {"FuelTech"})
    o = db.fuel_orders.get(id)
    if o is None:
        raise err(errors.ERR_NOT_FOUND, "Fuel order not found.")
    if o["logistics_status"] != "DISPATCHED":
        raise err(errors.ERR_INVALID_STATE, "complete-fueling requires DISPATCHED status.")
    o["logistics_status"] = "FUELED"
    db.touch(o)
    # LEDGER SYNC: non-tankering JET_A adds ordered_gallons to operator cumulative.
    if not o["tankering"] and o["product"] == "JET_A":
        operator = db.operators.get(_owner_operator_id(o))
        if operator is not None:
            operator["jeta_month_cumulative_gallons"] += o["ordered_gallons"]
            db.touch(operator)
    return success(order_view(o), 200)


@bp.route("/fuel-orders/<id>/cancel", methods=["POST"])
def cancel_order(id):
    _, role = authenticate()
    require_role(role, {"FuelTech", "OpsDispatcher"})
    o = db.fuel_orders.get(id)
    if o is None:
        raise err(errors.ERR_NOT_FOUND, "Fuel order not found.")
    if o["logistics_status"] not in ("REQUESTED", "DISPATCHED"):
        raise err(errors.ERR_INVALID_STATE, "cancel requires REQUESTED or DISPATCHED status.")
    if o["logistics_status"] == "DISPATCHED":
        o["priced_amount_cents"] = 0
    o["logistics_status"] = "CANCELLED"
    db.touch(o)
    return success(order_view(o), 200)


@bp.route("/fuel-orders/<id>/adjust-billing", methods=["POST"])
def adjust_billing(id):
    _, role = authenticate()
    require_role(role, {"BillingClerk"})
    o = db.fuel_orders.get(id)
    if o is None:
        raise err(errors.ERR_NOT_FOUND, "Fuel order not found.")
    if o["reconciliation_status"] != "IN_REVIEW":
        raise err(errors.ERR_INVALID_STATE, "adjust-billing requires IN_REVIEW reconciliation status.")

    # Find the order's into-plane ticket for delivered_gallons.
    delivered = None
    for tk in db.into_plane_tickets.values():
        if tk["fuel_order_id"] == o["id"]:
            delivered = tk["delivered_gallons"]
            break
    if delivered is None:
        delivered = o["ordered_gallons"]

    # COMPENSATING RE-PRICE cascade. Re-run the engine with delivered_gallons against
    # the same dispatch-time cumulative snapshot (PRD §3.2 / §3.6), so the marginal tier
    # walk reproduces the original pricing context and does not count this order's own
    # already-fueled gallons.
    dispatch_cumulative = o.get("_dispatch_cumulative_gallons", 0)
    o["priced_amount_cents"] = _price(o, delivered, dispatch_cumulative)
    o["reconciliation_status"] = "ADJUSTED"
    db.touch(o)

    visit_id = o["service_visit_id"]
    # If the parent visit already has an ISSUED invoice, recompute its total.
    operator = db.operators.get(_owner_operator_id(o))
    for inv in db.invoices.values():
        if inv["service_visit_id"] == visit_id and inv["status"] == "ISSUED":
            inv["total_cents"] = compute_invoice_total(visit_id)
            db.touch(inv)
    if operator is not None:
        recompute_open_invoice_balance(operator)
    return success(order_view(o), 200)
