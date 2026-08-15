"""Container assignment endpoints (PRD section 3.8).

FCL assignments are created directly by a BookingCoordinator; LCL assignments
arise only from the consolidation stuffing flow. Gate events meter demurrage
and detention: gate-out freezes final demurrage, empty-return freezes final
detention and auto-creates the D&D invoice when charges are positive.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ASSIGNMENT_INVALID_STATE,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_FOUND,
    ERR_CONTAINER_COUNT_EXCEEDED,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    get_json_body,
    has_field,
    optional_string,
    paginate,
    parse_pagination,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("container_assignments", __name__)


def _get_assignment(assignment_id: str) -> dict:
    asg = db.container_assignments.get(assignment_id)
    if asg is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "ContainerAssignment id does not exist")
    return asg


@bp.route("/freight/container-assignments", methods=["POST"])
@require_roles("BookingCoordinator")
def create_assignment(_user_id: str, _role: str):
    body = get_json_body()

    # Band 3: booking FK existence.
    booking = None
    if has_field(body, "booking_id"):
        booking = db.bookings.get(body["booking_id"])
        if booking is None:
            raise_err(ERR_BOOKING_NOT_FOUND, "booking_id does not exist")

    # Band 5: body shape.
    require_string(body, "booking_id")
    container_number = require_string(body, "container_number")
    seal_number = optional_string(body, "seal_number")
    stuffed_weight_kg = require_number(body, "stuffed_weight_kg", strictly_positive=True)
    stuffed_volume_cbm = require_number(body, "stuffed_volume_cbm", strictly_positive=True)

    # Band 6: booking must be FCL and CONFIRMED / DOCUMENTATION_CLEARED.
    if booking["mode"] != "FCL" or booking["status"] not in ("CONFIRMED", "DOCUMENTATION_CLEARED"):
        raise_err(
            ERR_BOOKING_INVALID_STATE,
            "Direct assignment creation requires an FCL booking in CONFIRMED or DOCUMENTATION_CLEARED",
        )

    # Band 12: live assignments may not exceed container_count.
    live = [
        a
        for a in db.container_assignments.values()
        if a["booking_id"] == booking["id"] and a["status"] in ("STUFFED", "GATED_IN", "LOADED")
    ]
    if len(live) >= (booking.get("container_count") or 0):
        raise_err(ERR_CONTAINER_COUNT_EXCEEDED, "Booking already has container_count live assignments")

    asg = {
        "booking_id": booking["id"],
        "consolidation_id": None,
        "assignment_mode": "FCL",
        "container_number": container_number,
        "seal_number": seal_number,
        "stuffed_weight_kg": stuffed_weight_kg,
        "stuffed_volume_cbm": stuffed_volume_cbm,
        "stuffed_at": db.now_domain_iso(),
        "gated_in_at": None,
        "discharged_at": None,
        "gated_out_at": None,
        "empty_returned_at": None,
        "demurrage_days": 0,
        "detention_days": 0,
        "provisional_demurrage_cents": 0,
        "provisional_detention_cents": 0,
        "demurrage_charge_cents": 0,
        "detention_charge_cents": 0,
        "status": "STUFFED",
    }
    db.stamp_new(asg)
    db.container_assignments[asg["id"]] = asg
    return success_object(domain.serialize_assignment(asg), 201)


@bp.route("/freight/container-assignments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_assignments(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.container_assignments.values()))
    items = apply_filters(items, ["booking_id", "consolidation_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([domain.serialize_assignment(a) for a in page], limit, offset, total)


@bp.route("/freight/container-assignments/<assignment_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_assignment(assignment_id: str, _user_id: str, _role: str):
    return success_object(domain.serialize_assignment(_get_assignment(assignment_id)))


@bp.route("/freight/container-assignments/<assignment_id>/gate-in", methods=["POST"])
@require_roles("BookingCoordinator")
def gate_in_assignment(assignment_id: str, _user_id: str, _role: str):
    asg = _get_assignment(assignment_id)
    get_json_body()
    if asg["status"] != "STUFFED":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE, "Assignment must be STUFFED to gate in")
    booking = db.bookings.get(asg["booking_id"])
    if booking is None or booking["status"] not in ("CONFIRMED", "DOCUMENTATION_CLEARED"):
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking must be CONFIRMED or DOCUMENTATION_CLEARED to gate in")
    asg["status"] = "GATED_IN"
    asg["gated_in_at"] = db.now_domain_iso()
    db.touch(asg)
    # FCL LOADED bubble-up re-evaluation.
    domain.reevaluate_loaded_gate(booking)
    return success_object(domain.serialize_assignment(asg))


@bp.route("/freight/container-assignments/<assignment_id>/gate-out", methods=["POST"])
@require_roles("BookingCoordinator")
def gate_out_assignment(assignment_id: str, _user_id: str, _role: str):
    asg = _get_assignment(assignment_id)
    get_json_body()
    if asg["status"] != "DISCHARGED":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE, "Assignment must be DISCHARGED to gate out")
    asg["status"] = "GATED_OUT"
    asg["gated_out_at"] = db.now_domain_iso()
    # Freeze FINAL demurrage.
    contract = domain.contract_for_assignment(asg)
    if contract is not None:
        days, charge = domain.compute_demurrage(contract, asg["discharged_at"], asg["gated_out_at"])
        asg["demurrage_days"] = days
        asg["demurrage_charge_cents"] = charge
        asg["provisional_demurrage_cents"] = charge
    db.touch(asg)
    return success_object(domain.serialize_assignment(asg))


@bp.route("/freight/container-assignments/<assignment_id>/empty-return", methods=["POST"])
@require_roles("BookingCoordinator")
def empty_return_assignment(assignment_id: str, _user_id: str, _role: str):
    asg = _get_assignment(assignment_id)
    get_json_body()
    if asg["status"] != "GATED_OUT":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE, "Assignment must be GATED_OUT to return empty")
    asg["status"] = "EMPTY_RETURNED"
    asg["empty_returned_at"] = db.now_domain_iso()
    # Freeze FINAL detention.
    contract = domain.contract_for_assignment(asg)
    det_days = 0
    det_charge = 0
    det_rate = 0
    if contract is not None:
        det_days, det_charge = domain.compute_detention(contract, asg["gated_out_at"], asg["empty_returned_at"])
        det_rate = contract["detention_per_diem_cents"]
        asg["detention_days"] = det_days
        asg["detention_charge_cents"] = det_charge
        asg["provisional_detention_cents"] = det_charge
    db.touch(asg)

    # Auto-create the D&D invoice when the combined charges are positive.
    booking = db.bookings.get(asg["booking_id"])
    if (
        booking is not None
        and asg["demurrage_charge_cents"] + asg["detention_charge_cents"] > 0
    ):
        domain.create_dd_invoice(
            booking,
            asg["demurrage_days"],
            asg["demurrage_charge_cents"],
            det_days,
            det_charge,
            det_rate,
        )
        shipper = db.shippers.get(booking["shipper_id"])
        if shipper is not None:
            domain.recompute_shipper_exposure(shipper)
    return success_object(domain.serialize_assignment(asg))
