"""Optimistic concurrency control on the two shared finite parent counts
(ClassTrip.version for bookings, PermitAllocation.version for permit passes).

Queue-B: cross_cutting OCC instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_member, new_class_trip, new_permit_allocation, book, issue_permit,
    create_booking_payload, create_permit_pass_payload, make_member_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


def test_booking_occ_correct_version_succeeds_and_bumps_classtrip_version(api):
    """PRD §2.7: "Creating a booking against a class or trip requires the client to
    submit expected_classtrip_version carrying the version of the target ClassTrip
    that the client last observed."
    PRD §2.4: "version is an integer that starts at its initial value on creation and
    increments by one on every mutation".

    Design: Corner/cross_cutting/booking_occ_correct_version_succeeds_and_bumps_classtrip_version
    """
    member = new_member(credit=3000)
    trip = new_class_trip(capacity=3, price_cents=3000, title="Cc Trip",
                          start_at="2026-08-14T08:00:00Z", end_at="2026-08-14T10:00:00Z")
    ctv0 = trip["version"]
    booking = book(member, trip, expected_version=ctv0)
    assert booking["status"] == "BOOKED"
    trip_after = validate_success(api.get_class_trip(trip["id"], STAFF), 200)
    assert trip_after["version"] == ctv0 + 1


def test_booking_occ_stale_version_rejected(api):
    """PRD §2.7: "If that value does not match the trip's current version — because
    another writer has since created a booking that advanced the trip's version and
    may have changed whether a fresh request would seat or waitlist — the create is
    rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/booking_occ_stale_version_rejected
    """
    ma = new_member(credit=3000)
    mb = new_member(credit=3000)
    trip = new_class_trip(capacity=3, price_cents=3000, title="Cc2 Trip",
                          start_at="2026-08-16T08:00:00Z", end_at="2026-08-16T10:00:00Z")
    ctv0 = trip["version"]
    book(ma, trip, expected_version=ctv0)   # advances trip.version past ctv0
    stale_payload = create_booking_payload(mb["id"], trip["id"], ctv0)
    res = api.create_booking(stale_payload, make_member_headers(mb["id"]))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


def test_permit_occ_stale_version_rejected(api):
    """PRD §2.7: "Issuing a permit pass requires expected_allocation_version carrying
    the last observed version of the target PermitAllocation; if another writer has
    since drawn a permit and advanced the pool's version, the issue is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/permit_occ_stale_version_rejected
    """
    ma = new_member(credit=5000)
    mb = new_member(credit=5000)
    alloc = new_permit_allocation(total_quota=5, price_cents=2000, park_name="North Cascades")
    pav0 = alloc["version"]
    issue_permit(ma, alloc, "2026-08-18T00:00:00Z", expected_version=pav0)  # advances version
    stale_payload = create_permit_pass_payload(mb["id"], alloc["id"], "2026-08-19T00:00:00Z", pav0)
    res = api.create_permit_pass(stale_payload, make_member_headers(mb["id"]))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
