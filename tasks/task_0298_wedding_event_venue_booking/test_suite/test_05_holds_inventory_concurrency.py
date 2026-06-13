"""Space-hold inventory: optimistic-concurrency on hold creation, the buffered
space-double-booking rule, the unbuffered walkthrough-overlap rule, and the
hold-expiry sweep.

Translates difficulty rule `resource_temporal_overlap` and corner `errors`
(stale version) and `state_machines` (hold expiry) instances.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_booking_payload,
    create_hold_payload,
    create_walkthrough_payload,
    create_inventory,
    create_inquiry_booking,
    add_both_holds,
    place_soft_hold,
    pay_deposit,
    confirm,
    set_clock,
    get_holds,
)

VA = TEST_USERS["venue_admin_headers"]
FO = TEST_USERS["finance_officer_headers"]


# ───────────── Rule 8: space-hold overlap PADS by turnover_buffer_minutes ─────────────

def test_space_hold_overlap_includes_turnover_buffer(api):
    """PRD §3.3: "Overlap is judged on the occupation interval extended by the
    space's `turnover_buffer_minutes`: a new occupation may not begin until at least
    that many minutes have elapsed after a conflicting occupation ends on that space.
    A collision is rejected with `ERR_SPACE_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/space_hold_overlap_includes_turnover_buffer
    """
    inv = create_inventory(space_overrides={"turnover_buffer_minutes": 60})
    coord = inv["coord_headers"]
    space_id = inv["space_id"]
    # Booking A: reception T22:00 → T03:00 committed.
    bkA = create_inquiry_booking(inv, booking_overrides={
        "reception_start": "2026-09-12T22:00:00Z", "reception_end": "2026-09-13T03:00:00Z"})
    bkA, _, _ = add_both_holds(inv, bkA, space_id)
    bkA = place_soft_hold(inv, bkA["id"])
    pay_deposit(inv, bkA["id"])
    confirm(inv, bkA["id"])
    # Booking B: ceremony starts T03:30 — only 30 min after A ends, < 60 buffer.
    bkB = get_success_data(api.create_booking(
        create_booking_payload(
            inv["client_id"], inv["venue_id"], inv["package_id"],
            event_date="2026-09-13",
            ceremony_start="2026-09-13T03:30:00Z", ceremony_end="2026-09-13T04:30:00Z",
            reception_start="2026-09-13T04:30:00Z", reception_end="2026-09-13T09:00:00Z",
            expected_guest_count=80),
        inv["client_headers"]))
    res = api.create_hold(
        bkB["id"], create_hold_payload(space_id, "CEREMONY", bkB["version"]), coord)
    validate_error(res, ApiErrorId.ERR_SPACE_DOUBLE_BOOKED.value)


def test_space_hold_distinct_space_no_conflict(api):
    """PRD §3.3: "the occupation must not collide with any other booking's blocking
    hold on the same space."

    Design: Difficulty/resource_temporal_overlap/space_hold_overlap_includes_turnover_buffer
    """
    inv = create_inventory(space_overrides={"turnover_buffer_minutes": 60})
    coord = inv["coord_headers"]
    # A second, separate space — overlap is judged per-space, so the same interval
    # on a different space does not collide.
    space_b = get_success_data(api.create_space(
        inv["venue_id"],
        {"name": "Hall B", "space_kind": "DUAL", "max_capacity": 200,
         "base_rental_cents": 500_000, "turnover_buffer_minutes": 60}, VA))
    bkA = create_inquiry_booking(inv, booking_overrides={
        "reception_start": "2026-09-12T22:00:00Z", "reception_end": "2026-09-13T03:00:00Z"})
    bkA, _, _ = add_both_holds(inv, bkA, inv["space_id"])
    bkA = place_soft_hold(inv, bkA["id"])
    pay_deposit(inv, bkA["id"])
    confirm(inv, bkA["id"])
    # Booking B holds the SAME ceremony interval but on space_b → allowed.
    bkB = get_success_data(api.create_booking(
        create_booking_payload(
            inv["client_id"], inv["venue_id"], inv["package_id"],
            event_date="2026-09-13",
            ceremony_start="2026-09-13T03:30:00Z", ceremony_end="2026-09-13T04:30:00Z",
            reception_start="2026-09-13T04:30:00Z", reception_end="2026-09-13T09:00:00Z",
            expected_guest_count=80),
        inv["client_headers"]))
    res = api.create_hold(
        bkB["id"], create_hold_payload(space_b["id"], "CEREMONY", bkB["version"]), coord)
    data = get_success_data(res)
    assert data["hold_status"] == "HELD"
    assert data["space_id"] == space_b["id"]


# ───────────── Rule 8: walkthrough overlap is plain half-open, no buffer ─────────────

def test_walkthrough_overlap_rejected_on_same_coordinator(api):
    """PRD §3.8: "the appointment must not overlap another `SCHEDULED` walkthrough on
    the same coordinator's calendar; a clash is rejected with
    `ERR_WALKTHROUGH_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/walkthrough_overlap_plain_halfopen_no_buffer
    """
    inv = create_inventory(with_space=False)
    coord = inv["coord_headers"]
    bk1 = create_inquiry_booking(inv)
    get_success_data(api.create_walkthrough(
        bk1["id"], create_walkthrough_payload("2026-08-01T14:00:00Z", "2026-08-01T15:00:00Z"),
        coord))
    bk2 = create_inquiry_booking(inv, booking_overrides={
        "event_date": "2026-09-19",
        "ceremony_start": "2026-09-19T20:00:00Z", "ceremony_end": "2026-09-19T21:00:00Z",
        "reception_start": "2026-09-19T21:00:00Z", "reception_end": "2026-09-20T02:00:00Z",
        "expected_guest_count": 90})
    res = api.create_walkthrough(
        bk2["id"], create_walkthrough_payload("2026-08-01T14:30:00Z", "2026-08-01T15:30:00Z"),
        coord)
    validate_error(res, ApiErrorId.ERR_WALKTHROUGH_CONFLICT.value)


def test_walkthrough_adjacent_no_buffer_accepted(api):
    """PRD §3.8: "the appointment must not overlap another `SCHEDULED` walkthrough on
    the same coordinator's calendar; a clash is rejected with
    `ERR_WALKTHROUGH_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/walkthrough_overlap_plain_halfopen_no_buffer
    """
    inv = create_inventory(with_space=False)
    coord = inv["coord_headers"]
    bk1 = create_inquiry_booking(inv)
    get_success_data(api.create_walkthrough(
        bk1["id"], create_walkthrough_payload("2026-08-01T14:00:00Z", "2026-08-01T15:00:00Z"),
        coord))
    bk2 = create_inquiry_booking(inv, booking_overrides={
        "event_date": "2026-09-19",
        "ceremony_start": "2026-09-19T20:00:00Z", "ceremony_end": "2026-09-19T21:00:00Z",
        "reception_start": "2026-09-19T21:00:00Z", "reception_end": "2026-09-20T02:00:00Z",
        "expected_guest_count": 90})
    # Starts exactly when W1 ends (adjacent, half-open) → no overlap, accepted.
    res = api.create_walkthrough(
        bk2["id"], create_walkthrough_payload("2026-08-01T15:00:00Z", "2026-08-01T16:00:00Z"),
        coord)
    data = get_success_data(res)
    assert data["walkthrough_status"] == "SCHEDULED"


# ───────────── Corner: stale booking version on hold create (OCC) ─────────────

def test_stale_booking_version_on_hold_create(api):
    """PRD §2.6: "If that value does not match the booking's current `version`, the
    create is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_booking_version_on_hold_create
    """
    inv = create_inventory()
    coord = inv["coord_headers"]
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    v_initial = booking["version"]
    # First hold consumes v_initial and advances the booking version.
    get_success_data(api.create_hold(
        booking["id"], create_hold_payload(inv["space_id"], "CEREMONY", v_initial), coord))
    # Second hold reuses the now-stale v_initial.
    res = api.create_hold(
        booking["id"], create_hold_payload(inv["space_id"], "RECEPTION", v_initial), coord)
    validate_error(res, ApiErrorId.ERR_STALE_BOOKING_VERSION.value)


def test_hold_create_with_current_version_succeeds(api):
    """PRD §2.6: "A request to create a `SpaceHold` against a booking must carry
    `expected_booking_version`, a non-optional field whose value is the `version` of
    the parent `Booking` the client last observed."

    Design: Corner/errors/stale_booking_version_on_hold_create
    """
    inv = create_inventory()
    coord = inv["coord_headers"]
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    h1 = get_success_data(api.create_hold(
        booking["id"], create_hold_payload(inv["space_id"], "CEREMONY", booking["version"]), coord))
    assert h1["hold_status"] == "HELD"
    # Refetch the advanced version and use it for the second hold → accepted.
    refreshed = get_success_data(api.get_booking(booking["id"], coord))
    h2 = get_success_data(api.create_hold(
        booking["id"], create_hold_payload(inv["space_id"], "RECEPTION", refreshed["version"]), coord))
    assert h2["hold_status"] == "HELD"


# ───────────── Corner: hold-expiry sweep ─────────────

def test_hold_expiry_releases_holds_and_cancels_booking(api):
    """PRD §3.3: "If the booking is `HELD` and the current clock has reached or
    passed `hold_expires_at`, the sweep moves `booking_status` from `HELD` to
    `CANCELLED`, releases every `HELD` hold to `RELEASED`, records `cancelled_reason`
    as `NONPAYMENT`, and clears `hold_expires_at`."

    Design: Corner/state_machines/hold_expiry_releases_holds_and_cancels_booking
    """
    inv, booking = None, None
    inv = create_inventory()
    booking = create_inquiry_booking(inv)
    booking, _, _ = add_both_holds(inv, booking)
    booking = place_soft_hold(inv, booking["id"])
    # Advance the clock well past the 6-hour soft-hold window.
    set_clock("2026-06-15T00:00:00Z")
    res = api.expire_hold(booking["id"], inv["coord_headers"])
    data = get_success_data(res)
    assert data["booking_status"] == "CANCELLED"
    assert data["cancelled_reason"] == "NONPAYMENT"
    holds = get_holds(inv, booking["id"])
    assert all(h["hold_status"] == "RELEASED" for h in holds)
