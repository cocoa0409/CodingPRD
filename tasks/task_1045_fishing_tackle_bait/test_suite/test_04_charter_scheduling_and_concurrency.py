"""Guide turnaround buffer, angler double-booking, license-required guard,
charter reschedule + optimistic concurrency, and booking-list pagination.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    set_clock, new_customer, new_license_type, issue_license, new_guide, new_charter,
    new_booking, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _licensed_customer(dob="1985-01-01"):
    cust = new_customer(date_of_birth=dob)
    lt = new_license_type()
    issue_license(cust["id"], lt["id"])
    return cust


# ─── Difficulty: resource_temporal_overlap / guide_charter_turnaround_buffer_conflict
def test_guide_gap_below_buffer_rejected(api):
    """PRD §3.4: "The request is refused with ERR_GUIDE_SCHEDULE_CONFLICT (HTTP 409) when the
    gap between the two windows is strictly less than 60 minutes; a gap of exactly 60 minutes
    is allowed."

    Design: Difficulty/resource_temporal_overlap/guide_charter_turnaround_buffer_conflict
    """
    guide = new_guide()
    new_charter(guide["id"], title="C1", start_at="2026-08-01T09:00:00Z",
                end_at="2026-08-01T12:00:00Z")
    res = api.create_charter(
        {"guide_id": guide["id"], "title": "C2", "start_at": "2026-08-01T12:30:00Z",
         "end_at": "2026-08-01T15:00:00Z", "capacity": 4, "price_per_seat_cents": 10000},
        MANAGER)  # 30-minute gap
    validate_error(res, "ERR_GUIDE_SCHEDULE_CONFLICT", 409)


def test_guide_gap_exactly_buffer_allowed(api):
    """PRD §3.4: "a required 60-minute turnaround buffer is enforced on both sides of the
    trip. The request is refused with ERR_GUIDE_SCHEDULE_CONFLICT (HTTP 409) when the gap
    between the two windows is strictly less than 60 minutes; a gap of exactly 60 minutes is
    allowed."

    Design: Difficulty/resource_temporal_overlap/guide_charter_turnaround_buffer_conflict
    """
    guide = new_guide()
    new_charter(guide["id"], title="C1", start_at="2026-08-01T09:00:00Z",
                end_at="2026-08-01T12:00:00Z")
    res = api.create_charter(
        {"guide_id": guide["id"], "title": "C3", "start_at": "2026-08-01T13:00:00Z",
         "end_at": "2026-08-01T15:00:00Z", "capacity": 4, "price_per_seat_cents": 10000},
        MANAGER)  # 60-minute gap
    charter = validate_success(res, 201)
    assert charter["status"] == "OPEN"


# ─── Difficulty: resource_temporal_overlap / angler_overlapping_bookings_halfopen_adjacent_allowed
def test_angler_overlapping_booking_rejected(api):
    """PRD §3.5: "The booking's charter window `[start_at, end_at)` must not overlap the
    window of any other active booking of the same customer; an overlap is refused with
    `ERR_ANGLER_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/angler_overlapping_bookings_halfopen_adjacent_allowed
    """
    set_clock("2026-07-15T00:00:00Z")
    a = _licensed_customer()
    g1, g2 = new_guide(), new_guide()
    c1 = new_charter(g1["id"], title="C1", start_at="2026-08-01T09:00:00Z",
                     end_at="2026-08-01T12:00:00Z")
    c4 = new_charter(g2["id"], title="C4", start_at="2026-08-01T11:00:00Z",
                     end_at="2026-08-01T14:00:00Z")
    new_booking(c1["id"], a["id"], seats=1)
    res = api.create_booking({"charter_id": c4["id"], "customer_id": a["id"], "seats": 1}, CLERK)
    validate_error(res, "ERR_ANGLER_SCHEDULE_CONFLICT", 409)


def test_angler_adjacent_booking_allowed(api):
    """PRD §3.5: "The booking's charter window `[start_at, end_at)` must not overlap the
    window of any other active booking of the same customer; an overlap is refused with
    `ERR_ANGLER_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/angler_overlapping_bookings_halfopen_adjacent_allowed
    """
    set_clock("2026-07-15T00:00:00Z")
    a = _licensed_customer()
    g1, g3 = new_guide(), new_guide()
    c1 = new_charter(g1["id"], title="C1", start_at="2026-08-01T09:00:00Z",
                     end_at="2026-08-01T12:00:00Z")
    c5 = new_charter(g3["id"], title="C5", start_at="2026-08-01T12:00:00Z",
                     end_at="2026-08-01T15:00:00Z")  # starts exactly when C1 ends
    new_booking(c1["id"], a["id"], seats=1)
    res = api.create_booking({"charter_id": c5["id"], "customer_id": a["id"], "seats": 1}, CLERK)
    booking = validate_success(res, 201)
    assert booking["booking_status"] == "RESERVED"


# ─── Difficulty: cross_entity_state_dependency / charter_booking_requires_active_license
def test_booking_without_license_rejected(api):
    """PRD §3.5: "The customer must already hold an ACTIVE license whose
    [valid_from, valid_until] range covers the charter's start_at date; without such a license
    the booking is refused with ERR_LICENSE_REQUIRED (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/charter_booking_requires_active_license
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = new_customer()  # no license issued
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-20T09:00:00Z",
                          end_at="2026-08-20T12:00:00Z", capacity=4)
    res = api.create_booking(
        {"charter_id": charter["id"], "customer_id": cust["id"], "seats": 1}, CLERK)
    validate_error(res, "ERR_LICENSE_REQUIRED", 422)


def test_booking_succeeds_once_license_held(api):
    """PRD §3.5: "The customer must already hold an ACTIVE license whose
    [valid_from, valid_until] range covers the charter's start_at date; without such a license
    the booking is refused with ERR_LICENSE_REQUIRED (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/charter_booking_requires_active_license
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = new_customer()
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-20T09:00:00Z",
                          end_at="2026-08-20T12:00:00Z", capacity=4)
    lt = new_license_type()
    issue_license(cust["id"], lt["id"])
    res = api.create_booking(
        {"charter_id": charter["id"], "customer_id": cust["id"], "seats": 1}, CLERK)
    booking = validate_success(res, 201)
    assert booking["booking_status"] == "RESERVED"


# ─── Corner: endpoints / reschedule_charter_updates_window_and_bumps_version
def test_reschedule_updates_window_and_bumps_version(api):
    """PRD §3.4: "A reschedule re-runs the same guide turnaround-buffer check against the new
    window, and on success updates the fields and increments the charter's version by one."

    Design: Corner/endpoints/reschedule_charter_updates_window_and_bumps_version
    """
    guide = new_guide()
    charter = new_charter(guide["id"], title="Resch", start_at="2026-08-08T09:00:00Z",
                          end_at="2026-08-08T12:00:00Z")
    assert charter["version"] == 1
    res = api.reschedule_charter(
        charter["id"],
        {"expected_charter_version": charter["version"],
         "start_at": "2026-08-08T13:00:00Z", "end_at": "2026-08-08T16:00:00Z"},
        MANAGER)
    updated = validate_success(res, 200)
    assert updated["version"] == 2
    assert updated["start_at"] == "2026-08-08T13:00:00Z"


# ─── Corner: cross_cutting_complexity_layers / occ_stale_charter_version_reschedule_rejected
def test_stale_charter_version_reschedule_rejected(api):
    """PRD §2.5: "so if the charter's `version` has advanced since the client read it, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being allowed to
    silently overwrite a change the client never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_charter_version_reschedule_rejected
    """
    guide = new_guide()
    charter = new_charter(guide["id"], title="OCC", start_at="2026-08-09T09:00:00Z",
                          end_at="2026-08-09T12:00:00Z")
    stale_version = charter["version"]  # 1
    validate_success(api.reschedule_charter(
        charter["id"],
        {"expected_charter_version": stale_version,
         "start_at": "2026-08-09T13:00:00Z", "end_at": "2026-08-09T16:00:00Z"}, MANAGER), 200)
    res = api.reschedule_charter(
        charter["id"],
        {"expected_charter_version": stale_version,  # now stale (current is 2)
         "start_at": "2026-08-09T17:00:00Z", "end_at": "2026-08-09T19:00:00Z"}, MANAGER)
    validate_error(res, "ERR_STALE_VERSION", 412)
    refreshed = get_success_data(api.get_charter(charter["id"], MANAGER))
    assert refreshed["version"] == 2


# ─── Corner: endpoints / list_charter_bookings_pagination_envelope
def test_booking_list_pagination_envelope(api):
    """PRD §2.3: "the meta block carries limit, offset, total_count (the count of all records
    matching the filter before the limit/offset window is applied), and has_more (true when
    records remain beyond the current window)."

    Design: Corner/endpoints/list_charter_bookings_pagination_envelope
    """
    set_clock("2026-07-15T00:00:00Z")
    c1 = _licensed_customer(dob="1985-01-01")
    c2 = _licensed_customer(dob="1986-01-01")
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-07T09:00:00Z",
                          end_at="2026-08-07T12:00:00Z", capacity=4)
    new_booking(charter["id"], c1["id"], seats=1)
    new_booking(charter["id"], c2["id"], seats=1)
    data, meta = validate_paginated(
        api.list_bookings(CLERK, params={"charter_id": charter["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
