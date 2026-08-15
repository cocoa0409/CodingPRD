"""Booking endpoints (PRD sections 3.6, 3.7, 3.15).

Lifecycle: QUOTED -> CONFIRMED -> DOCUMENTATION_CLEARED -> LOADED -> DEPARTED
-> ARRIVED -> DELIVERED; ROLLED <-> CONFIRMED cycle with caps; CANCELLED
terminal. Confirm/rebook run the forward credit gate; PATCH is OCC-guarded.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BL_NOT_RELEASED,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_CANCELLABLE,
    ERR_BOOKING_NOT_FOUND,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_OUTSTANDING_BALANCE,
    ERR_ROLLOVER_LIMIT_EXCEEDED,
    ERR_SHIPPER_NOT_FOUND,
    ERR_SHIPPER_SUSPENDED,
    ERR_STALE_BOOKING_VERSION,
    ERR_TARIFF_MISMATCH,
    ERR_TARIFF_NOT_EFFECTIVE,
    ERR_TARIFF_NOT_FOUND,
    ERR_VOYAGE_LANE_MISMATCH,
    ERR_VOYAGE_NOT_FOUND,
    ERR_VOYAGE_NOT_OPEN,
)
from middleware import ALL_ROLES, check_shipper_ownership, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    dec,
    get_json_body,
    has_field,
    optional_enum,
    optional_field,
    optional_int,
    optional_string,
    paginate,
    parse_pagination,
    pub,
    require_enum,
    require_int,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("bookings", __name__)

COMMODITY_TYPES = {"GENERAL", "REEFER", "HAZMAT"}
MODES = {"FCL", "LCL"}
CONTAINER_TYPES = {"20GP", "40GP", "40HC", "40RF"}
RATE_SOURCES = {"CONTRACT", "SPOT"}
TERMS = {"PREPAID", "COLLECT"}


def get_booking(booking_id: str) -> dict:
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise_err(ERR_BOOKING_NOT_FOUND, "Booking id does not exist")
    return booking


def _check_tariff_effective_and_matching(tariff: dict, voyage: dict, body_fields: dict) -> None:
    """Band 9 referential consistency (PRD section 3.6):
    tariff PUBLISHED with half-open window covering voyage.etd; lane /
    commodity / mode / FCL container_type consistency."""
    etd = db.parse_iso(voyage["etd"])
    if tariff["status"] != "PUBLISHED" or not (
        db.parse_iso(tariff["effective_from"]) <= etd < db.parse_iso(tariff["effective_to"])
    ):
        raise_err(ERR_TARIFF_NOT_EFFECTIVE, "Tariff is not PUBLISHED or its window does not cover the voyage etd")
    if (
        tariff["origin_port"] != voyage["origin_port"]
        or tariff["destination_port"] != voyage["destination_port"]
        or tariff["commodity_type"] != body_fields["commodity_type"]
        or tariff["mode"] != body_fields["mode"]
    ):
        raise_err(ERR_TARIFF_MISMATCH, "Tariff lane/commodity/mode inconsistent with voyage and booking")
    if body_fields["mode"] == "FCL" and tariff.get("container_type") != body_fields.get("container_type"):
        raise_err(ERR_TARIFF_MISMATCH, "FCL container_type must equal the tariff's container_type")


def _credit_gate(shipper: dict, estimate_cents: int) -> None:
    """Forward-exposure gate: forward (excluding this booking — it is not yet in
    the forward status set) + estimate <= credit_limit; equality allowed."""
    domain.recompute_shipper_exposure(shipper)
    if shipper["credit_exposure_forward_cents"] + estimate_cents > shipper["credit_limit_cents"]:
        raise_err(ERR_CREDIT_LIMIT_EXCEEDED, "Forward credit exposure would exceed the credit limit")


@bp.route("/freight/bookings", methods=["POST"])
@require_roles("Shipper", "BookingCoordinator")
def create_booking(_user_id: str, _role: str):
    body = get_json_body()

    # Band 2 ownership: a Shipper may only create for itself.
    if _role == "Shipper" and has_field(body, "shipper_id") and body["shipper_id"] != _user_id:
        from errors import ERR_INSUFFICIENT_PERMISSIONS, HTTP_STATUS
        from errors import ApiError

        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
            "Shipper may only create bookings for itself",
        )

    # Band 3: existence of present body FKs.
    voyage = None
    if has_field(body, "voyage_id"):
        voyage = db.voyages.get(body["voyage_id"])
        if voyage is None:
            raise_err(ERR_VOYAGE_NOT_FOUND, "voyage_id does not exist")
    tariff = None
    if has_field(body, "tariff_id"):
        tariff = db.tariffs.get(body["tariff_id"])
        if tariff is None:
            raise_err(ERR_TARIFF_NOT_FOUND, "tariff_id does not exist")
    resolved_shipper_id = _user_id if _role == "Shipper" else body.get("shipper_id")
    shipper = None
    if resolved_shipper_id:
        shipper = db.shippers.get(resolved_shipper_id)
        if shipper is None:
            raise_err(ERR_SHIPPER_NOT_FOUND, "shipper_id does not exist")

    # Band 5: body shape.
    require_string(body, "voyage_id")
    require_string(body, "tariff_id")
    if _role == "BookingCoordinator":
        require_string(body, "shipper_id")
    rate_source = require_enum(body, "rate_source", RATE_SOURCES)
    spot_rate = optional_int(body, "spot_rate_per_unit_cents", minimum=1)
    if rate_source == "SPOT" and spot_rate is None:
        raise_err(ERR_INVALID_REQUEST, "spot_rate_per_unit_cents is required when rate_source is SPOT")
    if rate_source == "CONTRACT" and has_field(body, "spot_rate_per_unit_cents"):
        raise_err(ERR_INVALID_REQUEST, "spot_rate_per_unit_cents is forbidden when rate_source is CONTRACT")
    mode = require_enum(body, "mode", MODES)
    container_type = optional_enum(body, "container_type", CONTAINER_TYPES)
    container_count = optional_int(body, "container_count", minimum=1)
    if mode == "FCL":
        if container_type is None:
            raise_err(ERR_INVALID_REQUEST, "container_type is required when mode is FCL")
        if container_count is None:
            raise_err(ERR_INVALID_REQUEST, "container_count is required when mode is FCL")
    else:
        if has_field(body, "container_type"):
            raise_err(ERR_INVALID_REQUEST, "container_type is forbidden when mode is LCL")
        if has_field(body, "container_count"):
            raise_err(ERR_INVALID_REQUEST, "container_count is forbidden when mode is LCL")
    commodity_type = require_enum(body, "commodity_type", COMMODITY_TYPES)
    gross_weight_kg = require_number(body, "gross_weight_kg", strictly_positive=True)
    volume_cbm = require_number(body, "volume_cbm", strictly_positive=True)
    terms = require_enum(body, "terms", TERMS)

    # Band 6: voyage must be BOOKING_OPEN; shipper must be ACTIVE.
    if voyage["status"] != "BOOKING_OPEN":
        raise_err(ERR_VOYAGE_NOT_OPEN, "Voyage must be BOOKING_OPEN for booking creation")
    if shipper["status"] != "ACTIVE":
        raise_err(ERR_SHIPPER_SUSPENDED, "Shipper is SUSPENDED")

    # Band 9: tariff effectiveness + consistency.
    fields = {"commodity_type": commodity_type, "mode": mode, "container_type": container_type}
    _check_tariff_effective_and_matching(tariff, voyage, fields)

    booking = {
        "booking_number": f"BK-{db.next_seq('booking')}",
        "shipper_id": shipper["id"],
        "voyage_id": voyage["id"],
        "tariff_id": tariff["id"],
        "rate_source": rate_source,
        "spot_rate_per_unit_cents": spot_rate,
        "mode": mode,
        "container_type": container_type,
        "container_count": container_count,
        "commodity_type": commodity_type,
        "gross_weight_kg": gross_weight_kg,
        "volume_cbm": volume_cbm,
        "terms": terms,
        "chargeable_weight_rt": 0,
        "estimated_freight_cents": 0,
        "rollover_count": 0,
        "rolled_reason": None,
        "pending_rollover_fee_cents": 0,
        "status": "QUOTED",
    }
    db.stamp_new(booking)
    db.bookings[booking["id"]] = booking
    domain.recompute_booking_estimate(booking)
    return success_object(pub(booking), 201)


@bp.route("/freight/bookings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_bookings(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.bookings.values()))
    items = apply_filters(items, ["shipper_id", "voyage_id", "tariff_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([pub(b) for b in page], limit, offset, total)


@bp.route("/freight/bookings/<booking_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_booking(booking_id: str, _user_id: str, _role: str):
    return success_object(pub(get_booking(booking_id)))


@bp.route("/freight/bookings/<booking_id>", methods=["PATCH"])
@require_roles("BookingCoordinator")
def amend_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking(booking_id)
    body = get_json_body()

    # Band 5: body shape.
    if not has_field(body, "expected_booking_version"):
        raise_err(ERR_INVALID_REQUEST, "expected_booking_version is required")
    expected = body["expected_booking_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_booking_version must be an integer")
    gross_weight_kg = None
    volume_cbm = None
    container_count = None
    if has_field(body, "gross_weight_kg"):
        gross_weight_kg = require_number(body, "gross_weight_kg", strictly_positive=True)
    if has_field(body, "volume_cbm"):
        volume_cbm = require_number(body, "volume_cbm", strictly_positive=True)
    commodity_type = optional_enum(body, "commodity_type", COMMODITY_TYPES)
    if has_field(body, "container_count"):
        container_count = require_int(body, "container_count", minimum=1)
    terms = optional_enum(body, "terms", TERMS)

    # Band 6: amendable while QUOTED or CONFIRMED.
    if booking["status"] not in ("QUOTED", "CONFIRMED"):
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking must be QUOTED or CONFIRMED to amend")

    # Band 9: commodity change re-validated against the pinned tariff.
    if commodity_type is not None:
        tariff = db.tariffs.get(booking["tariff_id"])
        if tariff is not None and tariff["commodity_type"] != commodity_type:
            raise_err(ERR_TARIFF_MISMATCH, "commodity_type must equal the tariff's commodity_type")

    # Band 14: optimistic concurrency on Booking.version.
    if expected != booking["version"]:
        raise_err(ERR_STALE_BOOKING_VERSION, "Booking version has advanced since the client's view")

    estimate_dirty = False
    if gross_weight_kg is not None:
        booking["gross_weight_kg"] = gross_weight_kg
        estimate_dirty = True
    if volume_cbm is not None:
        booking["volume_cbm"] = volume_cbm
        estimate_dirty = True
    if container_count is not None:
        booking["container_count"] = container_count
        estimate_dirty = True
    if commodity_type is not None:
        booking["commodity_type"] = commodity_type
    if terms is not None:
        booking["terms"] = terms
    if estimate_dirty:
        domain.recompute_booking_estimate(booking)
    db.touch(booking)

    shipper = db.shippers.get(booking["shipper_id"])
    if shipper is not None:
        domain.recompute_shipper_exposure(shipper)
    return success_object(pub(booking))


@bp.route("/freight/bookings/<booking_id>/confirm", methods=["POST"])
@require_roles("BookingCoordinator")
def confirm_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking(booking_id)
    get_json_body()
    # Band 6: state + shipper not suspended.
    if booking["status"] != "QUOTED":
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking must be QUOTED to confirm")
    shipper = db.shippers.get(booking["shipper_id"])
    if shipper is not None and shipper["status"] != "ACTIVE":
        raise_err(ERR_SHIPPER_SUSPENDED, "Shipper is SUSPENDED")

    # Estimate recomputed and frozen per ocean_freight_charge.
    domain.recompute_booking_estimate(booking)

    # Band 13: credit gate (forward variant; equality allowed).
    if shipper is not None:
        _credit_gate(shipper, booking["estimated_freight_cents"])

    booking["status"] = "CONFIRMED"
    db.touch(booking)
    if shipper is not None:
        domain.recompute_shipper_exposure(shipper)
    return success_object(pub(booking))


@bp.route("/freight/bookings/<booking_id>/cancel", methods=["POST"])
@require_roles("Shipper", "BookingCoordinator")
def cancel_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking(booking_id)
    get_json_body()  # optional reason
    # Band 2 ownership for the entity-backed Shipper role.
    check_shipper_ownership(_role, _user_id, booking["shipper_id"])

    # Band 6: cancellable states.
    if booking["status"] not in ("QUOTED", "CONFIRMED", "DOCUMENTATION_CLEARED"):
        raise_err(ERR_BOOKING_NOT_CANCELLABLE, "Booking is not in a cancellable state")

    # Band 13: no issued unpaid invoice may block cancellation.
    for inv in db.invoices.values():
        if (
            inv["booking_id"] == booking["id"]
            and inv["status"] in ("ISSUED", "PARTIALLY_PAID")
            and inv["balance_cents"] > 0
        ):
            raise_err(ERR_OUTSTANDING_BALANCE, "Booking has an outstanding invoice balance")

    fee_bearing = booking["status"] in ("CONFIRMED", "DOCUMENTATION_CLEARED")
    booking["status"] = "CANCELLED"
    booking["rolled_reason"] = None
    db.touch(booking)

    # Cascade: assignments, B/Ls, DRAFT FREIGHT invoices, policies.
    domain.booking_dependent_cascade(booking)
    domain.cancel_policies_for_booking(booking)

    # Cancellation fee from CONFIRMED onwards (DRAFT CANCELLATION invoice).
    if fee_bearing:
        domain.create_cancellation_invoice(booking)

    shipper = db.shippers.get(booking["shipper_id"])
    if shipper is not None:
        domain.recompute_shipper_exposure(shipper)
    return success_object(pub(booking))


@bp.route("/freight/bookings/<booking_id>/roll", methods=["POST"])
@require_roles("Shipper", "BookingCoordinator")
def roll_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking(booking_id)
    get_json_body()  # optional reason
    check_shipper_ownership(_role, _user_id, booking["shipper_id"])

    # Band 6: state.
    if booking["status"] not in ("CONFIRMED", "DOCUMENTATION_CLEARED"):
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking must be CONFIRMED or DOCUMENTATION_CLEARED to roll")
    # Band 12: rollover cap.
    if booking["rollover_count"] >= domain.MAX_ROLLOVERS:
        raise_err(ERR_ROLLOVER_LIMIT_EXCEEDED, "Rollover count cap reached")

    domain.roll_booking(booking, "SHIPPER_REQUEST")
    shipper = db.shippers.get(booking["shipper_id"])
    if shipper is not None:
        domain.recompute_shipper_exposure(shipper)
    return success_object(pub(booking))


@bp.route("/freight/bookings/<booking_id>/rebook", methods=["POST"])
@require_roles("BookingCoordinator")
def rebook_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking(booking_id)
    body = get_json_body()

    # Band 3: new_voyage_id FK existence (when present).
    new_voyage = None
    if has_field(body, "new_voyage_id"):
        new_voyage = db.voyages.get(body["new_voyage_id"])
        if new_voyage is None:
            raise_err(ERR_VOYAGE_NOT_FOUND, "new_voyage_id does not exist")

    # Band 5: body shape.
    require_string(body, "new_voyage_id")

    # Band 6: booking must be ROLLED; target voyage must be BOOKING_OPEN.
    if booking["status"] != "ROLLED":
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking must be ROLLED to rebook")
    if new_voyage["status"] != "BOOKING_OPEN":
        raise_err(ERR_VOYAGE_NOT_OPEN, "Target voyage must be BOOKING_OPEN")

    # Band 9: pinned tariff must still be PUBLISHED and cover the new etd.
    tariff = db.tariffs.get(booking["tariff_id"])
    etd = db.parse_iso(new_voyage["etd"])
    if (
        tariff is None
        or tariff["status"] != "PUBLISHED"
        or not (db.parse_iso(tariff["effective_from"]) <= etd < db.parse_iso(tariff["effective_to"]))
    ):
        raise_err(ERR_TARIFF_NOT_EFFECTIVE, "Pinned tariff is not effective for the new voyage")

    # Band 11: same-lane requirement.
    current_voyage = db.voyages.get(booking["voyage_id"])
    if current_voyage is not None and (
        new_voyage["origin_port"] != current_voyage["origin_port"]
        or new_voyage["destination_port"] != current_voyage["destination_port"]
    ):
        raise_err(ERR_VOYAGE_LANE_MISMATCH, "Target voyage must share origin and destination ports")

    # Rollover charge variant: fresh quote against the pinned tariff and the
    # new voyage; SHIPPER_REQUEST reprices + fees, carrier-caused takes min().
    reason = booking.get("rolled_reason")
    fresh = domain.compute_freight(
        mode=booking["mode"],
        container_count=booking.get("container_count"),
        chargeable_rt=booking["chargeable_weight_rt"],
        rate_source=booking["rate_source"],
        spot_rate_per_unit_cents=booking.get("spot_rate_per_unit_cents"),
        tariff=tariff,
    )
    old_estimate = booking["estimated_freight_cents"]
    if reason == "SHIPPER_REQUEST":
        booking["estimated_freight_cents"] = fresh["total_cents"]
        booking["_freight"] = fresh
        booking["pending_rollover_fee_cents"] = (
            booking.get("pending_rollover_fee_cents", 0) + domain.ROLLOVER_FEE_CENTS
        )
    else:
        if fresh["total_cents"] < old_estimate:
            booking["estimated_freight_cents"] = fresh["total_cents"]
            booking["_freight"] = fresh
        # else: keep the cheaper old estimate and its decomposition

    # Band 13: credit gate re-run with the recomputed estimate.
    shipper = db.shippers.get(booking["shipper_id"])
    if shipper is not None:
        _credit_gate(shipper, booking["estimated_freight_cents"])

    booking["voyage_id"] = new_voyage["id"]
    booking["status"] = "CONFIRMED"
    booking["rolled_reason"] = None
    db.touch(booking)
    if shipper is not None:
        domain.recompute_shipper_exposure(shipper)
    return success_object(pub(booking))


@bp.route("/freight/bookings/<booking_id>/deliver", methods=["POST"])
@require_roles("BookingCoordinator")
def deliver_booking(booking_id: str, _user_id: str, _role: str):
    booking = get_booking(booking_id)
    get_json_body()
    if booking["status"] != "ARRIVED":
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking must be ARRIVED to deliver")

    # A RELEASED bill of lading is required.
    released = any(
        bl["booking_id"] == booking["id"] and bl["status"] == "RELEASED"
        for bl in db.bills_of_lading.values()
    )
    if not released:
        raise_err(ERR_BL_NOT_RELEASED, "Booking has no RELEASED bill of lading")

    # Band 13: COLLECT terms require every FREIGHT invoice PAID (VOID ignored).
    if booking["terms"] == "COLLECT":
        for inv in db.invoices.values():
            if (
                inv["booking_id"] == booking["id"]
                and inv["invoice_type"] == "FREIGHT"
                and inv["status"] not in ("PAID", "VOID")
            ):
                raise_err(ERR_OUTSTANDING_BALANCE, "COLLECT booking has an unpaid FREIGHT invoice")

    booking["status"] = "DELIVERED"
    db.touch(booking)
    # BOUND policies expire at delivery.
    for pol in db.insurance_policies.values():
        if pol["booking_id"] == booking["id"] and pol["status"] == "BOUND":
            pol["status"] = "EXPIRED"
            db.touch(pol)
    shipper = db.shippers.get(booking["shipper_id"])
    if shipper is not None:
        domain.recompute_shipper_exposure(shipper)
    return success_object(pub(booking))
