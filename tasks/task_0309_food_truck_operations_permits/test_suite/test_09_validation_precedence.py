"""Validation precedence (the deterministic §3.9 ordering), the booking-create OCC check, and
the remaining business-constraint rejections.

Queue A: priority_pair_validation_conflict/arrive_state_before_window_temporal,
         priority_pair_validation_conflict/booking_create_outside_event_before_occ,
         cross_entity_state_dependency/booking_create_stale_truck_version_rejected.
Queue B: issue_second_active_permit_rejected, insufficient_prepared_units_blocks_settle,
         discard_below_consumed_rejected, clock_rewind_rejected,
         utility_log_generator_missing_delta_invalid.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_reserved_booking, setup_captured_order,
    create_commissary, create_truck, issue_permit, add_propane, add_shift,
    create_spot, create_event, reserve_booking, read_truck_version, set_clock,
    add_menu_item, add_prep_batch, open_order, add_line, authorize, capture, settle,
    api_client, TEST_USERS, make_operator_truck_headers,
    create_booking_payload, issue_health_permit_payload, create_utility_log_payload,
    set_clock_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
HEALTH_INSPECTOR = TEST_USERS["health_inspector_headers"]
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]


# ─── priority_pair / arrive: state (P6) before window (P9) ──────────────────

def test_arrive_state_check_precedes_window_check(api):
    """PRD §3.9: "Sixth, the target's own state precondition for the requested transition (the
    various ERR_..._NOT_..._ state errors named throughout §3) ... Ninth, the arrive
    clock-within-window check (ERR_OUTSIDE_BOOKING_WINDOW)."

    A CANCELLED booking arrived while the clock is outside its window fails the earlier state
    check (ERR_BOOKING_NOT_RESERVED) rather than the later window check.

    Design: Difficulty/priority_pair_validation_conflict/arrive_state_before_window_temporal
    """
    set_clock("2026-06-09T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    add_propane(truck["id"], 50)
    add_shift(truck["id"], "DRIVER", "2026-06-09T08:00:00.000Z", "2026-06-09T23:59:00.000Z", staff_name="Dee")
    add_shift(truck["id"], "COOK", "2026-06-09T08:00:00.000Z", "2026-06-09T23:59:00.000Z", staff_name="Coe")
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=0)
    event = create_event("2026-06-09T18:00:00.000Z", "2026-06-09T23:00:00.000Z")
    booking = reserve_booking(truck["id"], spot["id"], event["id"],
                              "2026-06-09T19:00:00.000Z", "2026-06-09T22:00:00.000Z")
    h = make_operator_truck_headers(truck["id"])
    # Cancel it (now CANCELLED), clock still 10:00 (outside the 19:00-22:00 window).
    validate_success(api.cancel_booking(booking["id"], h), 200)
    res = api.arrive_booking(booking["id"], h)
    validate_error(res, "ERR_BOOKING_NOT_RESERVED")


def test_arrive_window_check_when_state_ok(api):
    """PRD §3.4: "the current clock must fall within the booking's window — at or after
    window_start and strictly before window_end (else ERR_OUTSIDE_BOOKING_WINDOW)."

    The complement: when the booking is validly RESERVED but the clock is outside its window,
    arrive fails specifically on the window check — confirming the two checks are distinct rules.

    Design: Difficulty/priority_pair_validation_conflict/arrive_state_before_window_temporal
    """
    # Clock before the window opens; booking still RESERVED.
    ctx = setup_reserved_booking(
        "2026-07-31", clock_iso="2026-07-31T10:00:00.000Z",
        window_start="2026-07-31T19:00:00.000Z", window_end="2026-07-31T22:00:00.000Z",
        event_start="2026-07-31T18:00:00.000Z", event_end="2026-07-31T23:00:00.000Z")
    h = make_operator_truck_headers(ctx["truck"]["id"])
    res = api.arrive_booking(ctx["booking"]["id"], h)
    validate_error(res, "ERR_OUTSIDE_BOOKING_WINDOW")


# ─── priority_pair / booking create: outside-event (P14) before OCC (P16) ───

def test_booking_outside_event_check_precedes_occ(api):
    """PRD §3.9: "Fourteenth, the booking-within-event-window containment check
    (`ERR_BOOKING_OUTSIDE_EVENT`) ... And last, the booking-create optimistic-concurrency check on
    `expected_truck_version` (`ERR_STALE_TRUCK_VERSION`)."

    A booking whose window falls outside the event AND carries a stale expected_truck_version
    fails the earlier outside-event check (ERR_BOOKING_OUTSIDE_EVENT), not the later OCC check.

    Design: Difficulty/priority_pair_validation_conflict/booking_create_outside_event_before_occ
    """
    set_clock("2026-06-10T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=1000)
    event = create_event("2026-06-10T18:00:00.000Z", "2026-06-10T22:00:00.000Z")
    version = read_truck_version(truck["id"])
    h = make_operator_truck_headers(truck["id"])
    # Window 23:00-01:00 is outside the 18:00-22:00 event; expected version is stale (V-1).
    res = api.create_booking(
        create_booking_payload(truck["id"], spot["id"], event["id"],
                               "2026-06-10T23:00:00.000Z", "2026-06-11T01:00:00.000Z",
                               version - 1), h)
    validate_error(res, "ERR_BOOKING_OUTSIDE_EVENT")


def test_booking_within_event_with_fresh_version_succeeds(api):
    """PRD §3.4: "The booking's window must also fall entirely within the parent event's
    window — at or after the event's starts_at and at or before its ends_at; a window that
    escapes the event window is rejected with ERR_BOOKING_OUTSIDE_EVENT."

    The complement: a window inside the event with a fresh expected_truck_version passes both the
    containment and OCC checks and reserves successfully.

    Design: Difficulty/priority_pair_validation_conflict/booking_create_outside_event_before_occ
    """
    set_clock("2026-08-01T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=1000)
    event = create_event("2026-08-01T18:00:00.000Z", "2026-08-01T22:00:00.000Z")
    version = read_truck_version(truck["id"])
    h = make_operator_truck_headers(truck["id"])
    res = api.create_booking(
        create_booking_payload(truck["id"], spot["id"], event["id"],
                               "2026-08-01T19:00:00.000Z", "2026-08-01T20:00:00.000Z", version), h)
    booking = validate_success(res, 201)
    assert booking["status"] == "RESERVED"


# ─── cross_entity / booking create stale truck version ─────────────────────

def test_booking_create_stale_truck_version_rejected(api):
    """PRD §2.7: "If expected_truck_version does not equal the truck's current version, the
    booking create is rejected with ERR_STALE_TRUCK_VERSION (HTTP 412)."
    PRD §3.2: "Issuance recomputes the owning truck's operability ... this recompute writes the
    truck row and so advances its version."

    A booking carrying the version captured at truck-create — stale after a later permit issue
    bumped the version — is rejected with ERR_STALE_TRUCK_VERSION.

    Design: Difficulty/cross_entity_state_dependency/booking_create_stale_truck_version_rejected
    """
    set_clock("2026-06-19T18:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    v_at_create = truck["version"]
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=500)
    event = create_event("2026-06-19T17:00:00.000Z", "2026-06-19T22:00:00.000Z")
    # Permit issue bumps the truck version, making v_at_create stale.
    issue_permit(truck["id"])
    h = make_operator_truck_headers(truck["id"])
    res = api.create_booking(
        create_booking_payload(truck["id"], spot["id"], event["id"],
                               "2026-06-19T17:30:00.000Z", "2026-06-19T19:00:00.000Z",
                               v_at_create), h)
    validate_error(res, "ERR_STALE_TRUCK_VERSION")


def test_booking_create_current_version_after_permit_succeeds(api):
    """PRD §2.7: "The server compares it to the truck's current version ... A create-booking
    request must carry an expected_truck_version field holding the version of the target
    OperatorTruck that the client last observed."

    Re-reading the truck after the permit issue and supplying the refreshed version lets the
    booking create succeed — the deterministic counterpart to the stale-version rejection.

    Design: Difficulty/cross_entity_state_dependency/booking_create_stale_truck_version_rejected
    """
    set_clock("2026-08-02T18:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=500)
    event = create_event("2026-08-02T17:00:00.000Z", "2026-08-02T22:00:00.000Z")
    issue_permit(truck["id"])
    fresh_version = read_truck_version(truck["id"])
    h = make_operator_truck_headers(truck["id"])
    res = api.create_booking(
        create_booking_payload(truck["id"], spot["id"], event["id"],
                               "2026-08-02T17:30:00.000Z", "2026-08-02T19:00:00.000Z",
                               fresh_version), h)
    booking = validate_success(res, 201)
    assert booking["status"] == "RESERVED"


# ─── Corner: validations + errors ───────────────────────────────────────────

def test_issue_second_active_permit_rejected(api):
    """PRD §3.2: "Because a truck may hold at most one active permit at a time, issuing a second
    permit for a truck that already has an ACTIVE one is rejected with
    ERR_DUPLICATE_ACTIVE_PERMIT."

    A truck that already holds one ACTIVE permit rejects a second permit issue with
    ERR_DUPLICATE_ACTIVE_PERMIT.

    Design: Corner/validations/issue_second_active_permit_rejected
    """
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"], permit_number="PP1")
    res = api.issue_health_permit(
        issue_health_permit_payload(truck["id"], permit_number="PP2"), HEALTH_INSPECTOR)
    validate_error(res, "ERR_DUPLICATE_ACTIVE_PERMIT")


def test_insufficient_prepared_units_blocks_settle(api):
    """PRD §3.7: "the settlement must not drive any menu item's prepared_units below 0 (else
    ERR_INSUFFICIENT_PREPARED_UNITS)."

    Settling an order whose line quantity (5) exceeds the item's prepared_units (3) is rejected
    with ERR_INSUFFICIENT_PREPARED_UNITS; the order stays OPEN.

    Design: Corner/validations/insufficient_prepared_units_blocks_settle
    """
    ctx = setup_captured_order(
        "2026-07-09", clock_iso="2026-07-09T18:00:00.000Z",
        line_specs=[5], item_price_cents=300, prepared_units=3)
    h = make_operator_truck_headers(ctx["truck"]["id"])
    res = api.settle_order(ctx["order"]["id"], h, {"discount_code": "NONE"})
    validate_error(res, "ERR_INSUFFICIENT_PREPARED_UNITS")
    after = validate_success(api.get_order(ctx["order"]["id"], DISPATCHER), 200)
    assert after["lifecycle_status"] == "OPEN"


def test_discard_below_consumed_rejected(api):
    """PRD §3.5: "if removing the batch would drive prepared_units below the count already
    consumed by settled orders (that is, below 0), the discard is rejected with
    ERR_PREPARED_UNITS_NEGATIVE."

    After a SETTLED order consumes all 5 prepared units, discarding the only OPEN 5-unit batch
    would make prepared_units negative; it is rejected with ERR_PREPARED_UNITS_NEGATIVE.

    Design: Corner/validations/discard_below_consumed_rejected
    """
    ctx = setup_captured_order(
        "2026-07-10", clock_iso="2026-07-10T18:00:00.000Z",
        line_specs=[5], item_price_cents=300, prepared_units=5)
    truck_id = ctx["truck"]["id"]
    h = make_operator_truck_headers(truck_id)
    # The setup prep batch is the only batch for this item; settle consumes all 5 units.
    settle(truck_id, ctx["order"]["id"], discount_code="NONE")
    batches, _ = validate_paginated(
        api.list_prep_batches(DISPATCHER, params={"menu_item_id": ctx["item"]["id"]}))
    batch_id = batches[0]["id"]
    res = api.discard_prep_batch(batch_id, h)
    validate_error(res, "ERR_PREPARED_UNITS_NEGATIVE")


def test_clock_rewind_rejected(api):
    """PRD §3.10: "The target must be at or after the current clock; rewinding it is rejected
    with ERR_CLOCK_REWIND."

    Setting the clock to a time earlier than the current clock is rejected with ERR_CLOCK_REWIND.

    Design: Corner/errors/clock_rewind_rejected
    """
    validate_success(api.set_clock(set_clock_payload("2026-07-13T12:00:00.000Z"), PLATFORM_ADMIN), 200)
    res = api.set_clock(set_clock_payload("2026-07-13T11:00:00.000Z"), PLATFORM_ADMIN)
    validate_error(res, "ERR_CLOCK_REWIND")


def test_utility_log_generator_missing_delta_invalid(api):
    """PRD §3.8: "A `PROPANE` log missing its `propane_psi_after`, or a `GENERATOR` log missing
    its `generator_delta_hours`, is a malformed request."

    A GENERATOR utility log without generator_delta_hours is rejected with ERR_INVALID_REQUEST.

    Design: Corner/errors/utility_log_generator_missing_delta_invalid
    """
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    h = make_operator_truck_headers(truck["id"])
    res = api.create_utility_log(create_utility_log_payload(truck["id"], "GENERATOR"), h)
    validate_error(res, "ERR_INVALID_REQUEST")
