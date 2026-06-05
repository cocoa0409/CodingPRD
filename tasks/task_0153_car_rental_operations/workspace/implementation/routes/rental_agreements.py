"""RentalAgreement endpoints + state machine (PRD §3.5, §3.7, §3.9)."""
from flask import Blueprint, request

import db
import lookup
import serialize
import util
from errors import err
from middleware import get_principal, require_roles
from pagination import paginate
from response import array_response, object_response
from services import calc, fleet, loyalty, settlement

bp = Blueprint("rental_agreements", __name__)


@bp.route("/rental-agreements", methods=["POST"])
def pickup():
    """Pickup: realize a CONFIRMED reservation into an OPEN agreement."""
    _, role = get_principal()
    require_roles(role, {"RentalAgent"})
    body = request.get_json(silent=True) or {}

    reservation_id = util.require_str(body, "reservation_id")
    vehicle_id = util.require_str(body, "vehicle_id")
    odometer_out = util.require_int(body, "odometer_out", minimum=0)
    fuel_out = util.require_int_in_range(body, "fuel_out_eighths", 0, 8)

    # Existence: reservation, then vehicle.
    reservation = lookup.get_reservation(reservation_id)
    vehicle = lookup.get_vehicle(vehicle_id)

    # State: reservation must be CONFIRMED.
    if reservation["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "reservation is not CONFIRMED")

    # Priority 10: pickup only within the grace window.
    now = db.current_utc()
    hold_expires = util.parse_iso8601(reservation["hold_expires_at"])
    if now > hold_expires:
        raise err("ERR_GRACE_WINDOW_EXPIRED", "pickup attempted after the grace window")

    # Class/location match (ERR_CLASS_MISMATCH).
    if (
        vehicle["class_id"] != reservation["class_id"]
        or vehicle["location_id"] != reservation["pickup_location_id"]
    ):
        raise err("ERR_CLASS_MISMATCH", "vehicle class/location does not match reservation")

    # Vehicle usable: either RESERVED-held by this reservation, or AVAILABLE of
    # the reserved class at the pickup location (ERR_NO_AVAILABILITY otherwise).
    held_by_this = (
        vehicle["status"] == "RESERVED"
        and vehicle["held_by_reservation_id"] == reservation_id
    )
    assignable = vehicle["status"] == "AVAILABLE"
    if not (held_by_this or assignable):
        raise err("ERR_NO_AVAILABILITY", "named vehicle is not usable for this pickup")

    # Apply: create agreement, advance reservation, transition vehicle.
    was_reserved = vehicle["status"] == "RESERVED"
    vehicle["status"] = "ON_RENT"
    vehicle["held_by_reservation_id"] = None
    util.touch(vehicle)
    fleet.reconcile_class(db.vehicle_classes[vehicle["class_id"]])

    reservation["status"] = "PICKED_UP"
    util.touch(reservation)

    agreement = util.stamp_new(
        {
            "reservation_id": reservation_id,
            "vehicle_id": vehicle_id,
            "odometer_out": odometer_out,
            "fuel_out_eighths": fuel_out,
            "odometer_in": None,
            "fuel_in_eighths": None,
            "status": "OPEN",
            "final_total_cents": None,
            "miles_driven": 0,
        }
    )
    db.agreements[agreement["id"]] = agreement

    # Provisional settlement: date-driven ledger lines only.
    settlement.emit_provisional(agreement, reservation)
    return object_response(serialize.agreement(agreement), 201)


@bp.route("/rental-agreements", methods=["GET"])
def list_agreements():
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})

    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")
    matches = [
        a
        for a in db.agreements.values()
        if (vehicle_id is None or a["vehicle_id"] == vehicle_id)
        and (status is None or a["status"] == status)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.agreement(a) for a in page], limit, offset, total, 200
    )


@bp.route("/rental-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    rec = lookup.get_agreement(agreement_id)
    return object_response(serialize.agreement(rec), 200)


@bp.route("/rental-agreements/<agreement_id>/loyalty-accruals", methods=["GET"])
def list_agreement_accruals(agreement_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    lookup.get_agreement(agreement_id)
    matches = [
        a for a in db.loyalty_accruals.values() if a["agreement_id"] == agreement_id
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.loyalty_accrual(a) for a in page], limit, offset, total, 200
    )


@bp.route("/rental-agreements/<agreement_id>/ledger-entries", methods=["GET"])
def list_agreement_ledger(agreement_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    lookup.get_agreement(agreement_id)
    kind = request.args.get("kind")
    matches = [
        e
        for e in db.ledger_entries.values()
        if e["agreement_id"] == agreement_id and (kind is None or e["kind"] == kind)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.ledger_entry(e) for e in page], limit, offset, total, 200
    )


@bp.route("/rental-agreements/<agreement_id>/incident-reports", methods=["GET"])
def list_agreement_incidents(agreement_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    lookup.get_agreement(agreement_id)
    status = request.args.get("status")
    matches = [
        i
        for i in db.incidents.values()
        if i["agreement_id"] == agreement_id and (status is None or i["status"] == status)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.incident(i) for i in page], limit, offset, total, 200
    )


def _has_filed_incident_of(agreement_id, severities):
    for inc in db.incidents.values():
        if (
            inc["agreement_id"] == agreement_id
            and inc["status"] == "FILED"
            and inc["severity"] in severities
        ):
            return True
    return False


@bp.route("/rental-agreements/<agreement_id>/close", methods=["POST"])
def close_agreement(agreement_id):
    _, role = get_principal()
    require_roles(role, {"RentalAgent"})
    body = request.get_json(silent=True) or {}

    agreement = lookup.get_agreement(agreement_id)
    odometer_in = util.require_int(body, "odometer_in", minimum=0)
    fuel_in = util.require_int_in_range(body, "fuel_in_eighths", 0, 8)

    # State: agreement must be OPEN.
    if agreement["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "agreement is not OPEN")

    # Priority 11: odometer must not roll backward.
    if odometer_in < agreement["odometer_out"]:
        raise err("ERR_ODOMETER_ROLLBACK", "odometer_in is less than odometer_out")

    # Priority 12: a FILED TOTAL incident blocks close (must be written off).
    if _has_filed_incident_of(agreement_id, {"TOTAL"}):
        raise err(
            "ERR_TOTAL_LOSS_REQUIRES_WRITEOFF",
            "agreement carries a FILED TOTAL incident; write off instead",
        )

    reservation = db.reservations[agreement["reservation_id"]]
    vehicle = db.vehicles[agreement["vehicle_id"]]

    # Record return readings, advance state, recompute miles.
    agreement["odometer_in"] = odometer_in
    agreement["fuel_in_eighths"] = fuel_in
    agreement["status"] = "CLOSED"
    agreement["miles_driven"] = odometer_in - agreement["odometer_out"]

    # Final settlement (adds usage rows, re-sums).
    settlement.emit_final_usage(agreement, reservation, vehicle)
    util.touch(agreement)

    # Vehicle transition: clean (AVAILABLE) vs damaged (MAINTENANCE).
    damaged = _has_filed_incident_of(agreement_id, {"MAJOR", "TOTAL"})
    vehicle["odometer_miles"] = odometer_in
    vehicle["fuel_level_eighths"] = fuel_in
    if damaged:
        vehicle["status"] = "MAINTENANCE"
    else:
        vehicle["status"] = "AVAILABLE"
    util.touch(vehicle)
    fleet.reconcile_class(db.vehicle_classes[vehicle["class_id"]])

    # Loyalty accrual (full rate) + tier re-evaluation; order pinned after settlement.
    member = db.members[reservation["member_id"]]
    loyalty.emit_accrual(agreement, member, half_rate=False)

    return object_response(serialize.agreement(agreement), 200)


@bp.route("/rental-agreements/<agreement_id>/write-off", methods=["POST"])
def write_off_agreement(agreement_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager"})
    body = request.get_json(silent=True) or {}

    agreement = lookup.get_agreement(agreement_id)
    odometer_in = util.require_int(body, "odometer_in", minimum=0)
    fuel_in = util.require_int_in_range(body, "fuel_in_eighths", 0, 8)

    if agreement["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "agreement is not OPEN")

    # Priority 13: write-off requires at least one TOTAL-severity incident.
    has_total = any(
        inc["agreement_id"] == agreement_id and inc["severity"] == "TOTAL"
        for inc in db.incidents.values()
    )
    if not has_total:
        raise err("ERR_NO_TOTAL_INCIDENT", "no TOTAL-severity incident on this agreement")

    reservation = db.reservations[agreement["reservation_id"]]
    vehicle = db.vehicles[agreement["vehicle_id"]]

    agreement["odometer_in"] = odometer_in
    agreement["fuel_in_eighths"] = fuel_in
    agreement["status"] = "WRITE_OFF"
    agreement["miles_driven"] = odometer_in - agreement["odometer_out"]

    # Final settlement including full damage charge.
    settlement.emit_final_usage(agreement, reservation, vehicle)
    util.touch(agreement)

    # Total-loss cascade: ON_RENT -> RETIRED.
    vehicle["odometer_miles"] = odometer_in
    vehicle["fuel_level_eighths"] = fuel_in
    vehicle["status"] = "RETIRED"
    util.touch(vehicle)
    fleet.reconcile_class(db.vehicle_classes[vehicle["class_id"]])

    # Half-rate loyalty accrual + tier re-evaluation.
    member = db.members[reservation["member_id"]]
    loyalty.emit_accrual(agreement, member, half_rate=True)

    return object_response(serialize.agreement(agreement), 200)
