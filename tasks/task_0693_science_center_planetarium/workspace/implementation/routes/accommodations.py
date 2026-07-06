"""AccommodationRequest endpoints (PRD §3.9)."""
from flask import Blueprint, request

from db import db, new_record, touch
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_ACCOMMODATION_SUBJECT_MISMATCH,
    ERR_ACCESSIBLE_SEATS_UNAVAILABLE,
    ERR_NOT_FOUND,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_enum,
    parse_pagination,
    paginate,
)
from services.lookups import (
    get_show_booking,
    get_registration,
    get_rental,
    get_accommodation,
    get_show,
)
from services.serialize import accommodation_view
from services.show_logic import accessible_seats_of, accessible_seats_used

bp = Blueprint("accommodations", __name__)

SUBJECT_TYPES = {"SHOW_BOOKING", "REGISTRATION", "RENTAL"}
ACCOMMODATION_KINDS = {"WHEELCHAIR", "ASL_INTERPRETER", "SENSORY_FRIENDLY", "ASSISTIVE_LISTENING"}


@bp.route("/accommodations", methods=["POST"])
def create_accommodation():
    _, role = authenticate()
    require_role(role, {"AccessibilityCoordinator"})
    body = get_body()
    subject_type = require_enum(body, "subject_type", SUBJECT_TYPES)
    accommodation_kind = require_enum(body, "accommodation_kind", ACCOMMODATION_KINDS)
    show_booking_id = body.get("show_booking_id")
    registration_id = body.get("registration_id")
    rental_event_id = body.get("rental_event_id")

    with db.lock:
        # Existence (priority 3) of any present FK, validated left-to-right.
        if show_booking_id is not None:
            get_show_booking(show_booking_id)
        if registration_id is not None:
            get_registration(registration_id)
        if rental_event_id is not None:
            get_rental(rental_event_id)

        # Subject coherence (priority 18): exactly one identifier present and it
        # must agree with subject_type.
        present = [
            ("SHOW_BOOKING", show_booking_id),
            ("REGISTRATION", registration_id),
            ("RENTAL", rental_event_id),
        ]
        present_ids = [t for t, v in present if v is not None]
        if len(present_ids) != 1 or present_ids[0] != subject_type:
            raise err(ERR_ACCOMMODATION_SUBJECT_MISMATCH,
                      "Exactly one subject id matching subject_type is required")

        rec = new_record(with_version=True)
        rec.update({
            "subject_type": subject_type,
            "show_booking_id": show_booking_id,
            "registration_id": registration_id,
            "rental_event_id": rental_event_id,
            "accommodation_kind": accommodation_kind,
            "status": "SUBMITTED",
        })
        db.accommodations[rec["id"]] = rec
    return success(accommodation_view(rec), status=201)


@bp.route("/accommodations", methods=["GET"])
def list_accommodations():
    _, role = authenticate()
    require_role(role, {"AccessibilityCoordinator"})
    limit, offset = parse_pagination()
    show_booking_id = request.args.get("show_booking_id")
    registration_id = request.args.get("registration_id")
    rental_event_id = request.args.get("rental_event_id")
    status = request.args.get("status")
    with db.lock:
        records = list(db.accommodations.values())
        if show_booking_id is not None:
            records = [a for a in records if a["show_booking_id"] == show_booking_id]
        if registration_id is not None:
            records = [a for a in records if a["registration_id"] == registration_id]
        if rental_event_id is not None:
            records = [a for a in records if a["rental_event_id"] == rental_event_id]
        if status is not None:
            records = [a for a in records if a["status"] == status]
        page, meta = paginate(records, limit, offset)
        data = [accommodation_view(a) for a in page]
    return success(data, status=200, pagination=meta)


@bp.route("/accommodations/<aid>", methods=["GET"])
def get_one_accommodation(aid):
    _, role = authenticate()
    require_role(role, {"AccessibilityCoordinator"})
    with db.lock:
        a = get_accommodation(aid)
        return success(accommodation_view(a), status=200)


@bp.route("/accommodations/<aid>/approve", methods=["POST"])
def approve_accommodation(aid):
    _, role = authenticate()
    require_role(role, {"AccessibilityCoordinator"})
    with db.lock:
        a = get_accommodation(aid)
        # State (priority 5): must be SUBMITTED.
        if a["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Accommodation is not SUBMITTED")
        # For WHEELCHAIR on a SHOW_BOOKING, check accessible-seat availability
        # (priority 7).
        if a["accommodation_kind"] == "WHEELCHAIR" and a["subject_type"] == "SHOW_BOOKING":
            booking = get_show_booking(a["show_booking_id"])
            show = get_show(booking["show_event_id"])
            requested = booking.get("accessible_seats_requested", 0)
            # Remaining accessible seats excluding this booking's own claim.
            remaining = accessible_seats_of(show) - accessible_seats_used(show, exclude_booking_id=booking["id"])
            if requested > remaining:
                raise err(ERR_ACCESSIBLE_SEATS_UNAVAILABLE, "Not enough accessible seats remain")
        a["status"] = "APPROVED"
        touch(a)
        return success(accommodation_view(a), status=200)


@bp.route("/accommodations/<aid>/deny", methods=["POST"])
def deny_accommodation(aid):
    _, role = authenticate()
    require_role(role, {"AccessibilityCoordinator"})
    with db.lock:
        a = get_accommodation(aid)
        # Defined from SUBMITTED.
        if a["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Accommodation is not SUBMITTED")
        a["status"] = "DENIED"
        touch(a)
        return success(accommodation_view(a), status=200)


@bp.route("/accommodations/<aid>/fulfill", methods=["POST"])
def fulfill_accommodation(aid):
    _, role = authenticate()
    require_role(role, {"AccessibilityCoordinator"})
    with db.lock:
        a = get_accommodation(aid)
        # Defined from APPROVED.
        if a["status"] != "APPROVED":
            raise err(ERR_INVALID_STATE, "Accommodation is not APPROVED")
        a["status"] = "FULFILLED"
        touch(a)
        return success(accommodation_view(a), status=200)
