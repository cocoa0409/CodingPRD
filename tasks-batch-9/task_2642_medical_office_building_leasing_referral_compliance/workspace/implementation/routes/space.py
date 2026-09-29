"""Shared clinical space bookings (PRD Section 3.9)."""

from flask import Blueprint

import enums
import serializers as ser
import validators as v
from db import by_creation, db, stamp_new, touch
from errors import ApiError, bad_request
from lookups import get_lease, get_resource, paged
from middleware import endpoint, is_portal_user, acting_user_id, require_tenant_scope
from response import object_response
from services import calc

bp = Blueprint("space", __name__)

SCHEDULE_REQUIRED_SPACE_TYPES = ("WAITING_ROOM", "PROCEDURE_ROOM")


@bp.post("/shared-space-bookings")
@endpoint("LeasingAgent", "TenantPortalUser")
def create_booking():
    body = v.json_body()
    shared_space_id = v.get_string(body, "shared_space_id")
    lease_id = v.get_string(body, "lease_id")
    window_start, window_start_raw = v.get_instant(body, "window_start")
    window_end, window_end_raw = v.get_instant(body, "window_end")
    if window_end <= window_start:
        raise bad_request("Field 'window_end' must be later than 'window_start'.")
    occupant_count = v.get_int(body, "occupant_count", minimum=1)

    # Rung 7 outranks rung 8: the lease resolves before the shared space.
    lease = get_lease(lease_id)
    space = get_resource(db.shared_spaces, shared_space_id, "Shared space")
    require_tenant_scope(lease["tenant_id"])
    if lease["status"] in calc.CLOSED_LEASE_STATUSES:
        raise ApiError(
            "ERR_INVALID_LEASE_STATE",
            "Lease '%s' has reached %s." % (lease["id"], lease["status"]),
        )

    tenant = db.tenants[lease["tenant_id"]]
    if tenant["compliance_watch_status"] == "WATCH":
        raise ApiError(
            "ERR_TENANT_ON_COMPLIANCE_WATCH",
            "Tenant '%s' is on referral-compliance watch." % tenant["id"],
        )
    if space["space_type"] in SCHEDULE_REQUIRED_SPACE_TYPES and not lease[
        "space_sharing_schedule_on_file"
    ]:
        raise ApiError(
            "ERR_SPACE_SHARING_SCHEDULE_MISSING",
            "A %s booking requires a space-sharing schedule on file for lease '%s'."
            % (space["space_type"], lease["id"]),
        )

    after_hours = calc.is_after_hours(
        window_start, window_end, space["opens_at"], space["closes_at"]
    )
    # Rung 34 sits above rung 37: an unauthorised window is refused on the
    # authorization ground even when the room is entirely empty.
    if after_hours and not lease["after_hours_authorized"]:
        raise ApiError(
            "ERR_AFTER_HOURS_NOT_AUTHORIZED",
            "Lease '%s' is not authorized for after-hours access." % lease["id"],
        )

    peak = calc.peak_overlap_load(
        space["id"], window_start, window_end, occupant_count
    )
    if peak > space["capacity_seats"]:
        raise ApiError(
            "ERR_SHARED_SPACE_CAPACITY_EXCEEDED",
            "The requested window would load %d seats against a capacity of %d."
            % (peak, space["capacity_seats"]),
        )

    row = {
        "shared_space_id": space["id"],
        "lease_id": lease["id"],
        "window_start": window_start,
        "window_end": window_end,
        "window_start_raw": window_start_raw,
        "window_end_raw": window_end_raw,
        "occupant_count": occupant_count,
        "is_after_hours": after_hours,
        "status": "BOOKED",
        "cancellation_source": None,
    }
    stamp_new(row)
    db.bookings[row["id"]] = row
    return object_response(ser.booking_out(row), 201)


@bp.get("/shared-space-bookings")
@endpoint()
def list_bookings():
    limit, offset = v.pagination()
    shared_space_id = v.query_string("shared_space_id")
    lease_id = v.query_string("lease_id")
    status = v.query_enum("status", enums.BOOKING_STATUSES)

    rows = list(db.bookings.values())
    if is_portal_user():
        owned = {
            l["id"]
            for l in db.leases.values()
            if l["tenant_id"] == acting_user_id()
        }
        rows = [b for b in rows if b["lease_id"] in owned]
    if shared_space_id is not None:
        rows = [b for b in rows if b["shared_space_id"] == shared_space_id]
    if lease_id is not None:
        rows = [b for b in rows if b["lease_id"] == lease_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    return paged(by_creation(rows), ser.booking_out, limit, offset)


@bp.get("/shared-space-bookings/<booking_id>")
@endpoint()
def get_booking(booking_id):
    booking = get_resource(db.bookings, booking_id, "Shared-space booking")
    lease = db.leases[booking["lease_id"]]
    require_tenant_scope(lease["tenant_id"])
    return object_response(ser.booking_out(booking))


@bp.post("/shared-space-bookings/<booking_id>/cancel")
@endpoint("LeasingAgent", "TenantPortalUser")
def cancel_booking(booking_id):
    body = v.json_body()
    # cancellation_note is accepted and optional; the entity records only the
    # provenance, so the note is validated and discarded.
    v.get_string(body, "cancellation_note", required=False, allow_empty=True)

    booking = get_resource(db.bookings, booking_id, "Shared-space booking")
    lease = db.leases[booking["lease_id"]]
    require_tenant_scope(lease["tenant_id"])
    if booking["status"] != "BOOKED":
        raise ApiError(
            "ERR_INVALID_RECORD_STATE",
            "Booking '%s' is in status %s; only a BOOKED window may be cancelled."
            % (booking["id"], booking["status"]),
        )
    if booking["window_start"] <= db.clock:
        raise ApiError(
            "ERR_TERM_NOT_YET_STARTED",
            "Booking '%s' is already under way and can no longer be cancelled."
            % booking["id"],
        )

    booking["status"] = "CANCELLED"
    booking["cancellation_source"] = "REQUESTED"
    touch(booking)
    return object_response(ser.booking_out(booking))
