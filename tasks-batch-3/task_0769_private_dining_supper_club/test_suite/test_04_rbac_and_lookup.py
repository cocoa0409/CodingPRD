"""Role-based access control (peer-role denials and ownership) plus a catalog not-found lookup.

Each test translates exactly one design-index instance; docstrings end with the Design tag.
"""
import pytest
from test_helpers import (
    validate_error, NON_EXISTENT_UUID,
    provision_confirmed_booking, create_guest,
    create_series_payload, make_guest_headers,
)


# ─── Corner: errors / catalog not-found ────────────────────────────────

def test_get_nonexistent_guest_returns_not_found(api):
    """PRD §2.7: "a missing series yields ERR_SERIES_NOT_FOUND, a missing venue ERR_VENUE_NOT_FOUND,
    a missing chef ERR_CHEF_NOT_FOUND, a missing guest ERR_GUEST_NOT_FOUND, a missing event
    ERR_EVENT_NOT_FOUND, a missing seat ERR_SEAT_NOT_FOUND, a missing booking ERR_BOOKING_NOT_FOUND,
    a missing menu course ERR_MENU_COURSE_NOT_FOUND, and a missing waitlist entry
    ERR_WAITLIST_ENTRY_NOT_FOUND."

    Design: Corner/errors/get_guest_nonexistent_returns_not_found
    """
    res = api.get_guest(NON_EXISTENT_UUID, make_guest_headers("test-guest-1"))
    validate_error(res, "ERR_GUEST_NOT_FOUND")


# ─── Corner: rbac / peer-role denials ──────────────────────────────────

def test_guest_cannot_check_in_booking(api):
    """PRD §2.1: "When the caller is authenticated but the acting role — or the caller's ownership
    of the target resource — does not permit the operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/guest_cannot_check_in_booking
    """
    _ctx, guest, booking = provision_confirmed_booking(seat_count=1)
    # Check-in is a VenueManager/PlatformAdmin operation; a Guest may not perform it.
    res = api.check_in_booking(booking["id"], make_guest_headers(guest["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_other_guest_cannot_cancel_others_booking(api):
    """PRD §2.1: "When X-User-Role is Guest, X-User-ID is the id of the acting Guest; ownership
    checks on any Booking or WaitlistEntry compare that resource's guest_id to X-User-ID. A Guest
    may act only on their own bookings and waitlist entries."

    Design: Corner/rbac/other_guest_cannot_cancel_others_booking
    """
    _ctx, _g1, booking = provision_confirmed_booking(seat_count=1)
    other = create_guest(email="other@x.com")
    res = api.cancel_booking(booking["id"], {"reason": "malicious"},
                             make_guest_headers(other["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_guest_cannot_create_series(api):
    """PRD §2.1: "When X-User-Role is PlatformAdmin, X-User-ID is an opaque operator identifier
    not tied to any persisted entity. PlatformAdmin is an operator superset: it seeds catalog
    records, drives the logical clock, and may perform any Event or Booking operation without an
    ownership restriction."

    Design: Corner/rbac/guest_cannot_create_series
    """
    guest = create_guest()
    res = api.create_series(create_series_payload(), make_guest_headers(guest["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")
