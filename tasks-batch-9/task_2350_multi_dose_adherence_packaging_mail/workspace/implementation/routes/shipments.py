"""Dispatch, delivery, the cold-chain reversal and pickup confirmation."""

import uuid

from flask import Blueprint

import clock
import db
import engine
import enums
import middleware
import response
import store
import validators
from errors import ApiError

bp = Blueprint("shipments", __name__)

IN_FLIGHT_STATUSES = ("IN_TRANSIT", "DELIVERED", "PICKED_UP")
TERMINAL_SHIPMENT_STATUSES = (
    "PICKED_UP",
    "PICKUP_MISSED",
    "EXCEPTION_RETURNED",
    "CANCELLED",
)
# The completing dispatch moves the cycle *from* VERIFIED to SHIPPED, so a cycle that
# has not yet cleared the bench is never finalised by a dispatch.
COMPLETABLE_PACKAGING_STATUS = "VERIFIED"


@bp.post("/shipments/<shipment_id>/dispatch")
def dispatch(shipment_id):
    middleware.authenticate(("PharmacyOperations",))
    shipment = middleware.lookup("shipment", shipment_id)

    if shipment["status"] != "STAGED":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE")

    cycle = db.fill_cycles[shipment["cycle_id"]]
    if shipment["shipment_kind"] == "POUCH_ROLL":
        rolls = engine.rolls_of_cycle(cycle["id"])
        roll = rolls[-1] if rolls else None
        if roll is None or roll["verification_status"] != "PASSED":
            raise ApiError("ERR_ROLL_NOT_VERIFIED")

    shipment["status"] = "IN_TRANSIT"
    shipment["tracking_number"] = "TRK-" + uuid.uuid4().hex[:12].upper()
    shipment["dispatched_at"] = clock.now_iso()
    store.touch(shipment)

    if _cycle_is_complete(cycle):
        _finalise_cycle(cycle)

    store.commit()
    return response.object_response(store.serialize(shipment))


def _required_kinds(cycle):
    kinds = set()
    for line in engine.lines_of_cycle(cycle["id"]):
        if line["line_status"] != "ADJUDICATED":
            continue
        route = line["packable_route"]
        if route in enums.ROUTE_TO_KIND:
            kinds.add(enums.ROUTE_TO_KIND[route])
    return kinds


def _cycle_is_complete(cycle):
    if cycle["packaging_status"] != COMPLETABLE_PACKAGING_STATUS:
        return False
    required = _required_kinds(cycle)
    if not required:
        return False
    in_flight = {
        shipment["shipment_kind"]
        for shipment in engine.shipments_of_cycle(cycle["id"])
        if shipment["status"] in IN_FLIGHT_STATUSES
    }
    return required.issubset(in_flight)


def _finalise_cycle(cycle):
    """The dispatch that completes the cycle carries its financial close."""
    final_cents = engine.final_copay_cents(cycle)
    delta = cycle["total_copay_cents"] - final_cents
    cycle["packaging_status"] = "SHIPPED"
    cycle["final_copay_cents"] = final_cents
    cycle["rounding_delta_cents"] = delta
    store.touch(cycle)

    if delta >= 1:
        engine.issue_memo(
            engine.patient_of_cycle(cycle), cycle["id"], "ROUNDING_TRUEUP", delta
        )

    for line in engine.lines_of_cycle(cycle["id"]):
        if line["line_status"] == "ADJUDICATED":
            line["line_status"] = "PACKED_OUT"
            store.touch(line)


@bp.post("/shipments/<shipment_id>/deliver")
def deliver(shipment_id):
    middleware.authenticate(("PharmacyOperations",))
    body = validators.json_body()
    excursion_minutes = validators.integer(
        body, "cold_chain_excursion_minutes", required=False, default=0, minimum=0
    )

    shipment = middleware.lookup("shipment", shipment_id)
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE")

    shipment["cold_chain_excursion_minutes"] = excursion_minutes
    shipment["delivered_at"] = clock.now_iso()
    store.touch(shipment)

    spoiled = (
        shipment["shipment_kind"] == "COLD_CHAIN"
        and excursion_minutes > enums.COLD_CHAIN_EXCURSION_LIMIT_MINUTES
    )
    if not spoiled:
        shipment["status"] = "DELIVERED"
        store.commit()
        return response.object_response(store.serialize(shipment))

    # The exception branch unwinds the whole dispense.
    shipment["status"] = "EXCEPTION_RETURNED"
    cycle = db.fill_cycles[shipment["cycle_id"]]
    patient = engine.patient_of_cycle(cycle)

    credited_total = 0
    for line_id in shipment["covers_line_ids"]:
        line = db.cycle_lines.get(line_id)
        if line is None:
            continue
        credited_total += line["copay_cents"]
        line["line_status"] = "CREDITED"
        store.touch(line)
        engine.reverse_dispense(db.prescriptions[line["prescription_id"]], line)

    engine.issue_memo(patient, cycle["id"], "COLD_CHAIN_EXCURSION", credited_total)
    engine.recompute_total_copay(cycle)
    store.touch(cycle)
    engine.append_event(
        cycle["id"], "DELIVERY_EXCEPTION", clock.now_iso(), "SYSTEM_SCAN"
    )

    store.commit()
    return response.object_response(store.serialize(shipment))


@bp.post("/shipments/<shipment_id>/confirm-pickup")
def confirm_pickup(shipment_id):
    user_id, role = middleware.authenticate(("Patient",))
    shipment = middleware.lookup("shipment", shipment_id)
    middleware.enforce_scope(role, user_id, "shipment", shipment)

    if shipment["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE")

    shipment["status"] = "PICKED_UP"
    shipment["pickup_confirmed_at"] = clock.now_iso()
    store.touch(shipment)

    cycle = db.fill_cycles[shipment["cycle_id"]]
    engine.append_event(
        cycle["id"], "PICKUP_CONFIRMED", clock.now_iso(), "PATIENT_REPORTED"
    )

    patient = engine.patient_of_cycle(cycle)
    if patient["consecutive_missed_pickups"] != 0:
        patient["consecutive_missed_pickups"] = 0
        store.touch(patient)

    siblings = engine.shipments_of_cycle(cycle["id"])
    if all(other["status"] in TERMINAL_SHIPMENT_STATUSES for other in siblings):
        if cycle["packaging_status"] == "SHIPPED":
            cycle["packaging_status"] = "CLOSED"
    store.touch(cycle)

    store.commit()
    return response.object_response(store.serialize(shipment))
