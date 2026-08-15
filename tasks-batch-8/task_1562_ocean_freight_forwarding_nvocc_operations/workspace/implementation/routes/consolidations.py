"""Consolidation endpoints (PRD section 3.9).

LCL freight is stuffed into CFS consolidations; stuffing is OCC-guarded and
capacity-gated (equality allowed); HAZMAT and REEFER never mix. A CLOSED
consolidation reopens automatically when its last live member is removed.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_BOOKING_ALREADY_STUFFED,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_FOUND,
    ERR_CONSOLIDATION_CAPACITY_EXCEEDED,
    ERR_CONSOLIDATION_EMPTY,
    ERR_CONSOLIDATION_INVALID_STATE,
    ERR_CONSOLIDATION_NOT_FOUND,
    ERR_INCOMPATIBLE_CARGO_MIX,
    ERR_INVALID_REQUEST,
    ERR_STALE_CONSOLIDATION_VERSION,
    ERR_STUFFING_WINDOW_OVERLAP,
    ERR_VOYAGE_INVALID_STATE,
    ERR_VOYAGE_NOT_FOUND,
    ERR_VOYAGE_NOT_OPEN,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    dec,
    get_json_body,
    has_field,
    paginate,
    parse_pagination,
    pub,
    require_enum,
    require_number,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("consolidations", __name__)

CONTAINER_TYPES = {"20GP", "40GP", "40HC", "40RF"}


def _get_consolidation(consolidation_id: str) -> dict:
    con = db.consolidations.get(consolidation_id)
    if con is None:
        raise_err(ERR_CONSOLIDATION_NOT_FOUND, "Consolidation id does not exist")
    return con


@bp.route("/freight/consolidations", methods=["POST"])
@require_roles("BookingCoordinator")
def create_consolidation(_user_id: str, _role: str):
    body = get_json_body()

    # Band 3: FK existence for a present voyage_id.
    voyage = None
    if has_field(body, "voyage_id"):
        voyage = db.voyages.get(body["voyage_id"])
        if voyage is None:
            raise_err(ERR_VOYAGE_NOT_FOUND, "voyage_id does not exist")

    # Band 5: body shape.
    require_string(body, "voyage_id")
    cfs_location = require_string(body, "cfs_location")
    container_type = require_enum(body, "container_type", CONTAINER_TYPES)
    max_weight_kg = require_number(body, "max_weight_kg", strictly_positive=True)
    max_volume_cbm = require_number(body, "max_volume_cbm", strictly_positive=True)
    window_start = require_ts(body, "stuffing_window_start")
    window_end = require_ts(body, "stuffing_window_end")
    if not (window_end > window_start):
        raise_err(ERR_INVALID_REQUEST, "stuffing_window_end must be strictly after stuffing_window_start")

    # Band 6: voyage must be BOOKING_OPEN.
    if voyage["status"] != "BOOKING_OPEN":
        raise_err(ERR_VOYAGE_NOT_OPEN, "Voyage must be BOOKING_OPEN for consolidation creation")

    # Band 11: half-open stuffing-window overlap at the same cfs_location;
    # adjacency is allowed.
    for other in db.consolidations.values():
        if other["cfs_location"] != cfs_location:
            continue
        if other["status"] not in ("OPEN", "CLOSED", "TENDERED"):
            continue
        o_start = db.parse_iso(other["stuffing_window_start"])
        o_end = db.parse_iso(other["stuffing_window_end"])
        if window_start < o_end and o_start < window_end:
            raise_err(
                ERR_STUFFING_WINDOW_OVERLAP,
                "Another consolidation at this cfs_location has an intersecting stuffing window",
            )

    con = {
        "consolidation_number": f"CON-{db.next_seq('consolidation')}",
        "voyage_id": voyage["id"],
        "cfs_location": cfs_location,
        "container_type": container_type,
        "max_weight_kg": max_weight_kg,
        "max_volume_cbm": max_volume_cbm,
        "used_weight_kg": 0,
        "used_volume_cbm": 0,
        "stuffing_window_start": db.format_iso(window_start),
        "stuffing_window_end": db.format_iso(window_end),
        "status": "OPEN",
    }
    db.stamp_new(con)
    db.consolidations[con["id"]] = con
    return success_object(pub(con), 201)


@bp.route("/freight/consolidations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_consolidations(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.consolidations.values()))
    items = apply_filters(items, ["voyage_id", "cfs_location", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([pub(c) for c in page], limit, offset, total)


@bp.route("/freight/consolidations/<consolidation_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_consolidation(consolidation_id: str, _user_id: str, _role: str):
    return success_object(pub(_get_consolidation(consolidation_id)))


@bp.route("/freight/consolidations/<consolidation_id>/stuff", methods=["POST"])
@require_roles("BookingCoordinator")
def stuff_consolidation(consolidation_id: str, _user_id: str, _role: str):
    con = _get_consolidation(consolidation_id)
    body = get_json_body()

    # Band 3: booking FK existence.
    booking = None
    if has_field(body, "booking_id"):
        booking = db.bookings.get(body["booking_id"])
        if booking is None:
            raise_err(ERR_BOOKING_NOT_FOUND, "booking_id does not exist")

    # Band 5: body shape.
    require_string(body, "booking_id")
    if not has_field(body, "expected_consolidation_version"):
        raise_err(ERR_INVALID_REQUEST, "expected_consolidation_version is required")
    expected = body["expected_consolidation_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_consolidation_version must be an integer")

    # Band 6: consolidation OPEN; booking LCL and CONFIRMED/DOCUMENTATION_CLEARED.
    if con["status"] != "OPEN":
        raise_err(ERR_CONSOLIDATION_INVALID_STATE, "Consolidation must be OPEN to stuff")
    if booking["mode"] != "LCL" or booking["status"] not in ("CONFIRMED", "DOCUMENTATION_CLEARED"):
        raise_err(
            ERR_BOOKING_INVALID_STATE,
            "Booking must be mode LCL and in CONFIRMED or DOCUMENTATION_CLEARED to stuff",
        )

    # Band 8: commodity compatibility — HAZMAT and REEFER never share a box.
    member_commodities = set()
    for a in domain.consolidation_members(con):
        member_booking = db.bookings.get(a["booking_id"])
        if member_booking is not None:
            member_commodities.add(member_booking["commodity_type"])
    if (booking["commodity_type"] == "HAZMAT" and "REEFER" in member_commodities) or (
        booking["commodity_type"] == "REEFER" and "HAZMAT" in member_commodities
    ):
        raise_err(ERR_INCOMPATIBLE_CARGO_MIX, "HAZMAT and REEFER bookings may not share a consolidation")

    # Band 10: one in-flight LCL stuffing per booking.
    for a in db.container_assignments.values():
        if (
            a["booking_id"] == booking["id"]
            and a["assignment_mode"] == "LCL"
            and a["status"] in ("STUFFED", "GATED_IN", "LOADED")
        ):
            raise_err(ERR_BOOKING_ALREADY_STUFFED, "Booking already holds a live LCL assignment")

    # Band 12: capacity gate (<= on both axes; equality allowed).
    if dec(con["used_weight_kg"]) + dec(booking["gross_weight_kg"]) > dec(con["max_weight_kg"]) or dec(
        con["used_volume_cbm"]
    ) + dec(booking["volume_cbm"]) > dec(con["max_volume_cbm"]):
        raise_err(ERR_CONSOLIDATION_CAPACITY_EXCEEDED, "Stuffing would exceed consolidation capacity")

    # Band 14: OCC on the consolidation version.
    if expected != con["version"]:
        raise_err(ERR_STALE_CONSOLIDATION_VERSION, "Consolidation version has advanced since the client's view")

    asg = {
        "booking_id": booking["id"],
        "consolidation_id": con["id"],
        "assignment_mode": "LCL",
        "container_number": f"{con['consolidation_number']}-BX",
        "seal_number": None,
        "stuffed_weight_kg": booking["gross_weight_kg"],
        "stuffed_volume_cbm": booking["volume_cbm"],
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
    domain.recompute_consolidation_used(con)
    db.touch(con)
    return success_object(domain.serialize_assignment(asg), 201)


@bp.route("/freight/consolidations/<consolidation_id>/unstuff", methods=["POST"])
@require_roles("BookingCoordinator")
def unstuff_consolidation(consolidation_id: str, _user_id: str, _role: str):
    con = _get_consolidation(consolidation_id)
    body = get_json_body()

    booking = None
    if has_field(body, "booking_id"):
        booking = db.bookings.get(body["booking_id"])
        if booking is None:
            raise_err(ERR_BOOKING_NOT_FOUND, "booking_id does not exist")
    require_string(body, "booking_id")

    # Membership check: the booking must hold a member assignment in THIS
    # consolidation with status STUFFED or GATED_IN.
    member = None
    for a in db.container_assignments.values():
        if (
            a["booking_id"] == booking["id"]
            and a.get("consolidation_id") == con["id"]
            and a["status"] in ("STUFFED", "GATED_IN")
        ):
            member = a
            break
    if member is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "Booking holds no stuffed member assignment in this consolidation")

    # Band 6: consolidation must be OPEN or CLOSED.
    if con["status"] not in ("OPEN", "CLOSED"):
        raise_err(ERR_CONSOLIDATION_INVALID_STATE, "Consolidation must be OPEN or CLOSED to unstuff")

    # Member -> CANCELLED; used_* recompute; CLOSED with zero members -> OPEN.
    # cancel_assignment_cascade performs the single consolidation mutation
    # (recompute + optional reopen + version bump).
    domain.cancel_assignment_cascade(member, allow_reopen=True)
    return success_object(pub(con))


@bp.route("/freight/consolidations/<consolidation_id>/close", methods=["POST"])
@require_roles("BookingCoordinator")
def close_consolidation(consolidation_id: str, _user_id: str, _role: str):
    con = _get_consolidation(consolidation_id)
    get_json_body()
    if con["status"] != "OPEN":
        raise_err(ERR_CONSOLIDATION_INVALID_STATE, "Consolidation must be OPEN to close")
    members = [a for a in domain.consolidation_members(con) if a["status"] in ("STUFFED", "GATED_IN")]
    if not members:
        raise_err(ERR_CONSOLIDATION_EMPTY, "Close requires at least one stuffed or gated-in member")
    con["status"] = "CLOSED"
    db.touch(con)
    return success_object(pub(con))


@bp.route("/freight/consolidations/<consolidation_id>/tender", methods=["POST"])
@require_roles("BookingCoordinator")
def tender_consolidation(consolidation_id: str, _user_id: str, _role: str):
    con = _get_consolidation(consolidation_id)
    get_json_body()
    if con["status"] != "CLOSED":
        raise_err(ERR_CONSOLIDATION_INVALID_STATE, "Consolidation must be CLOSED to tender")
    voyage = db.voyages.get(con["voyage_id"])
    if voyage is None or voyage["status"] != "BOOKING_OPEN":
        raise_err(ERR_VOYAGE_INVALID_STATE, "Voyage must be BOOKING_OPEN to tender")

    con["status"] = "TENDERED"
    db.touch(con)
    # Member assignments STUFFED -> GATED_IN; member booking LOADED re-eval.
    member_booking_ids = []
    for a in db.container_assignments.values():
        if a.get("consolidation_id") == con["id"] and a["status"] == "STUFFED":
            a["status"] = "GATED_IN"
            db.touch(a)
            member_booking_ids.append(a["booking_id"])
    for booking_id in dict.fromkeys(member_booking_ids):
        booking = db.bookings.get(booking_id)
        if booking is not None:
            domain.reevaluate_loaded_gate(booking)
    return success_object(pub(con))


@bp.route("/freight/consolidations/<consolidation_id>/cancel", methods=["POST"])
@require_roles("BookingCoordinator")
def cancel_consolidation(consolidation_id: str, _user_id: str, _role: str):
    con = _get_consolidation(consolidation_id)
    get_json_body()
    if con["status"] not in ("OPEN", "CLOSED", "TENDERED"):
        raise_err(ERR_CONSOLIDATION_INVALID_STATE, "Consolidation must be OPEN, CLOSED, or TENDERED to cancel")
    domain.cancel_consolidation(con)
    return success_object(pub(con))
