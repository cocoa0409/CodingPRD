"""Return delivery: shipment creation, delivery attempts, address changes and pickup."""
from flask import Blueprint

import clock
import serializers
import store
import validation
from constants import (
    API_PREFIX,
    DELIVERY_ATTEMPT_CAP,
    DELIVERY_ATTEMPT_OUTCOMES,
    DELIVERY_ESCALATION_FEE_CENTS,
    DELIVERY_ESCALATION_THRESHOLD_DAYS,
    SHIPMENT_METHODS,
)
from errors import fail
from routes.common import AUDIT_ROLES, READ_ROLES, created, endpoint, listing, ok
from services import custody, lookup, money
from validation import Body

bp = Blueprint("shipments", __name__)
P = API_PREFIX


def _complete_order(order):
    """DELIVERING -> COMPLETED; the one conditional money effect."""
    order["workflow_status"] = "COMPLETED"
    if order["refunded_cents"] == money.collected_cents(order):
        order["payment_status"] = "REFUNDED"


@bp.route(P + "/orders/<order_id>/shipments", methods=["POST"])
@endpoint("orders.shipments.create", ["CourierOps"])
def create_shipment(ctx, order_id):
    order = validation.need_order(order_id)
    body = Body(ctx.body)
    method = body.enum("method", SHIPMENT_METHODS)
    address = body.string("address_region_code")
    signature_required = body.boolean("signature_required", required=False, default=True)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(order["workflow_status"], ("APPROVED", "REJECTED"))
    if order["custody_holder"] != "SERVICE":
        fail("ERR_CUSTODY_MISMATCH")

    days_to_travel = (order["travel_date"] - clock.now().date()).days
    escalation_fee = 0
    final_method = method
    if method == "GROUND" and days_to_travel <= DELIVERY_ESCALATION_THRESHOLD_DAYS:
        final_method = "OVERNIGHT"
        escalation_fee = DELIVERY_ESCALATION_FEE_CENTS
        order["service_fee_quoted_cents"] += DELIVERY_ESCALATION_FEE_CENTS
        order["total_quoted_cents"] = (
            order["government_fee_quoted_cents"] + order["service_fee_quoted_cents"]
        )
        money.derive_payment_status(order)

    row = store.insert("shipments", {
        "order_id": order["id"],
        "method": final_method,
        "address_region_code": address,
        "signature_required": bool(signature_required),
        "delivery_status": "CREATED",
        "attempt_count": 0,
        "escalation_fee_cents": escalation_fee,
    })
    order["workflow_status"] = "DELIVERING"
    store.touch(order)
    return created(serializers.shipment(row))


@bp.route(P + "/orders/<order_id>/shipments", methods=["GET"])
@endpoint("orders.shipments.list", READ_ROLES)
def list_shipments(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    return listing(lookup.shipments_of(order), serializers.shipment)


@bp.route(P + "/shipments/<shipment_id>", methods=["GET"])
@endpoint("shipments.read", READ_ROLES)
def read_shipment(ctx, shipment_id):
    row = validation.need("shipments", shipment_id)
    validation.check_membership(ctx, lookup.order_of_shipment(row))
    return ok(serializers.shipment(row))


@bp.route(P + "/shipments/<shipment_id>/delivery-attempt", methods=["POST"])
@endpoint("shipments.delivery_attempt", ["CourierOps"])
def delivery_attempt(ctx, shipment_id):
    shipment = validation.need("shipments", shipment_id)
    order = lookup.order_of_shipment(shipment)
    body = Body(ctx.body)
    # The `outcome` field on a delivery attempt is deliberately ABSENT from the
    # rung-7 closed list: an off-set value here is ERR_VALIDATION at rung 6.
    outcome = body.non_enum_choice("outcome", DELIVERY_ATTEMPT_OUTCOMES)
    body.boolean("signature_captured", required=False, default=None)
    # Adjudication of friction 6: `signature_captured` must be present AND true;
    # absent, false or non-boolean all fail this rung-6 check.
    body.invalid(
        outcome == "DELIVERED" and shipment["signature_required"]
        and ctx.body.get("signature_captured") is not True,
        "signature_captured must be true for a DELIVERED attempt on a signature-required shipment.",
    )
    body.check()
    validation.guard_order(ctx, order)

    status = shipment["delivery_status"]
    if status in ("DELIVERED", "PICKED_UP"):
        fail("ERR_INVALID_STATE", "The shipment has already closed out.")
    # Rung 14 -- the FIRST delivery attempt only.
    if status == "CREATED" and order["custody_holder"] != "SERVICE":
        fail("ERR_CUSTODY_MISMATCH")
    # Rung 26 -- also owns the HELD_FOR_PICKUP case, which rung 10 does not.
    if status == "HELD_FOR_PICKUP" or shipment["attempt_count"] >= DELIVERY_ATTEMPT_CAP:
        fail("ERR_DELIVERY_ATTEMPT_CAP_EXCEEDED")

    order_moved = False
    shipment["attempt_count"] += 1
    if outcome == "DELIVERED":
        shipment["delivery_status"] = "DELIVERED"
        custody.handover(order, "APPLICANT", "SHIPMENT_DELIVERED")
        _complete_order(order)
        order_moved = True
    else:
        if status == "CREATED":
            shipment["delivery_status"] = "OUT_FOR_DELIVERY"
            custody.handover(order, "COURIER", "LEG_DISPATCHED")
            order_moved = True
        elif shipment["attempt_count"] >= DELIVERY_ATTEMPT_CAP:
            shipment["delivery_status"] = "HELD_FOR_PICKUP"
    store.touch(shipment)
    if order_moved:
        store.touch(order)
    return ok(serializers.shipment(shipment))


@bp.route(P + "/shipments/<shipment_id>/address", methods=["PATCH"])
@endpoint("shipments.address", ["CaseManager", "Traveler"])
def change_address(ctx, shipment_id):
    shipment = validation.need("shipments", shipment_id)
    order = lookup.order_of_shipment(shipment)
    validation.check_membership(ctx, order)
    body = Body(ctx.body)
    address = body.string("address_region_code")
    body.check()
    validation.guard_order(ctx, order)
    shipment["address_region_code"] = address
    store.touch(shipment)
    return ok(serializers.shipment(shipment))


@bp.route(P + "/shipments/<shipment_id>/pickup", methods=["POST"])
@endpoint("shipments.pickup", ["CourierOps"])
def pickup_shipment(ctx, shipment_id):
    shipment = validation.need("shipments", shipment_id)
    order = lookup.order_of_shipment(shipment)
    Body(ctx.body).check()
    validation.guard_order(ctx, order)
    validation.require_state(shipment["delivery_status"], ("HELD_FOR_PICKUP",))

    shipment["delivery_status"] = "PICKED_UP"
    store.touch(shipment)
    custody.handover(order, "APPLICANT", "SHIPMENT_PICKED_UP")
    _complete_order(order)
    store.touch(order)
    return ok(serializers.shipment(shipment))


@bp.route(P + "/orders/<order_id>/sla-segments", methods=["GET"])
@endpoint("orders.sla_segments", AUDIT_ROLES)
def list_sla_segments(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    return listing(lookup.sla_segments_of(order), serializers.sla_segment)
