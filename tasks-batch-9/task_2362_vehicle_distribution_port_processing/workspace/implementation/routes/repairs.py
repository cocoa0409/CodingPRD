"""Repair orders: escalation adjudication and damage clearance (PRD §3.4)."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid_state
from middleware import OPS_ROLES, ROLE_MANAGER, ROLE_SURVEYOR, authenticate
from response import list_response, object_response
from services import calculations as calc
from services import serializers as ser
from services import state

bp = Blueprint("repairs", __name__)


@bp.route("/vpc/repair-orders/<repair_order_id>", methods=["GET"])
def read_repair_order(repair_order_id):
    authenticate(OPS_ROLES)
    order = db.must_get("repair_orders", repair_order_id)
    return object_response(ser.repair_order(order))


@bp.route("/vpc/repair-orders", methods=["GET"])
def list_repair_orders():
    authenticate(OPS_ROLES)
    vehicle_id = v.query_filter("vehicle_id")
    claim_id = v.query_filter("carrier_claim_id")
    status = v.query_filter("status")
    tier = v.query_filter("authorization_tier")
    records = db.ordered(db.repair_orders)
    if vehicle_id is not None:
        records = [r for r in records if r["vehicle_id"] == vehicle_id]
    if claim_id is not None:
        records = [r for r in records if r["carrier_claim_id"] == claim_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if tier is not None:
        records = [r for r in records if r["authorization_tier"] == tier]
    items, limit, offset, total = v.paginate(records, ser.repair_order)
    return list_response(items, limit, offset, total)


@bp.route("/vpc/repair-orders/<repair_order_id>/authorize", methods=["POST"])
def authorize_repair(repair_order_id):
    user_id, _role = authenticate([ROLE_MANAGER])
    order = db.must_get("repair_orders", repair_order_id)
    body = v.body()
    decision = v.req_enum(body, "decision", ("AUTHORIZE", "REJECT"))

    if order["status"] != "ESCALATED":
        invalid_state("only an ESCALATED repair order can be adjudicated")

    vehicle = db.vehicles.get(order["vehicle_id"])
    if decision == "AUTHORIZE":
        live = [
            claim
            for claim in state.claims_of_vehicle(order["vehicle_id"])
            if claim["status"] in state.LIVE_CLAIM_STATUSES
        ]
        if not live:
            fail(
                "ERR_CLAIM_REQUIRED",
                "an escalated repair needs a live carrier claim behind the spend",
            )
        order["status"] = "AUTHORIZED"
        order["authorized_by_user_id"] = user_id
        db.touch(order)
        if vehicle is not None and vehicle["damage_status"] == "SURVEY_DAMAGE_OPEN":
            vehicle["damage_status"] = "REPAIR_AUTHORIZED"
            db.touch(vehicle)
    else:
        order["status"] = "REJECTED"
        db.touch(order)
    return object_response(ser.repair_order(order))


@bp.route("/vpc/repair-orders/<repair_order_id>/complete", methods=["POST"])
def complete_repair(repair_order_id):
    authenticate([ROLE_SURVEYOR])
    order = db.must_get("repair_orders", repair_order_id)
    body = v.body()
    actual = v.req_int(body, "actual_cost_cents", minimum=0)

    if order["status"] != "AUTHORIZED":
        invalid_state("only an AUTHORIZED repair order can be completed")

    order["actual_cost_cents"] = actual
    order["status"] = "COMPLETED"
    db.touch(order)

    vehicle = db.vehicles.get(order["vehicle_id"])
    if vehicle is not None:
        if vehicle["damage_status"] == "REPAIR_AUTHORIZED":
            vehicle["damage_status"] = "REPAIRED"
            vehicle["damage_cleared_at"] = db.clock_now()
            vehicle["blocked_credit_days"] = calc.blocked_credit_days(
                vehicle["damage_opened_at"], vehicle["damage_cleared_at"]
            )
            db.touch(vehicle)
        center = state.center_of_vehicle(vehicle)
        if center is not None:
            state.recompute_center(center)

    claim = db.claims.get(order["carrier_claim_id"]) if order["carrier_claim_id"] else None
    if claim is not None and claim["status"] in state.LIVE_CLAIM_STATUSES:
        claim["recoverable_basis"] = "REPAIR_ACTUAL"
        claim["recoverable_amount_cents"] = state.claim_recoverable(claim)
        db.touch(claim)
    return object_response(ser.repair_order(order))
