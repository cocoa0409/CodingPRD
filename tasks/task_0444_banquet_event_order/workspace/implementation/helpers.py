"""Pagination + path-resource lookup helpers."""
from flask import request

import db
import errors

ALL_ROLES = {"PlatformAdmin", "SalesManager", "BanquetCaptain", "AccountingClerk"}


def parse_pagination():
    """limit defaults 10, [1,100]; offset defaults 0, >=0 (PRD §2.3).

    A non-integer or out-of-range pagination param is a malformed request
    -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset, serializer):
    """Sort by created_at asc (tie-broken by insertion seq), slice, serialize."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(r) for r in page], total


def get_event_or_404(event_id):
    e = db.events.get(event_id)
    if e is None:
        raise errors.not_found("Event not found: " + str(event_id))
    return e


def get_function_room_or_404(room_id):
    r = db.function_rooms.get(room_id)
    if r is None:
        raise errors.not_found("FunctionRoom not found: " + str(room_id))
    return r


def get_block_or_404(block_id):
    b = db.hotel_room_blocks.get(block_id)
    if b is None:
        raise errors.not_found("HotelRoomBlock not found: " + str(block_id))
    return b


def get_booking_or_404(event_id, booking_id):
    b = db.bookings.get(booking_id)
    if b is None or b["event_id"] != event_id:
        raise errors.not_found("Booking not found: " + str(booking_id))
    return b


def get_menu_line_or_404(event_id, menu_line_id):
    m = db.menu_lines.get(menu_line_id)
    if m is None or m["event_id"] != event_id:
        raise errors.not_found("MenuLine not found: " + str(menu_line_id))
    return m


def get_service_line_or_404(event_id, service_line_id):
    s = db.service_lines.get(service_line_id)
    if s is None or s["event_id"] != event_id:
        raise errors.not_found("ServiceLine not found: " + str(service_line_id))
    return s


def get_link_or_404(event_id, link_id):
    l = db.room_block_links.get(link_id)
    if l is None or l["event_id"] != event_id:
        raise errors.not_found("RoomBlockLink not found: " + str(link_id))
    return l


def get_payment_or_404(event_id, payment_id):
    p = db.payments.get(payment_id)
    if p is None or p["event_id"] != event_id:
        raise errors.not_found("Payment not found: " + str(payment_id))
    return p
