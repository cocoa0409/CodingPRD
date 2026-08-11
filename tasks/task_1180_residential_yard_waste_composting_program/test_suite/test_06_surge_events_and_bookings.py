"""Surge collection events: clock-derived lifecycle, slot allocation,
waitlist promotion, booking gates, and OCC on the event version."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_surge_booking,
    assert_surge_event,
    book_surge,
    book_surge_ok,
    cancel_booking,
    create_surge_booking_payload,
    create_surge_event_payload,
    get_subscription,
    get_success_data,
    get_surge_event,
    make_resident_headers,
    set_clock,
    setup_open_surge_event,
    setup_suspended_subscription,
    validate_error,
    validate_success,
)


def _create_event(zone_id, **overrides):
    return get_success_data(api_client.create_surge_event(
        create_surge_event_payload(zone_id, **overrides), TEST_USERS["admin_headers"]))


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / subscription_cancel_releases_slot_promotes_waitlist
# ---------------------------------------------------------------------------

def _setup_cancel_promotes_scenario():
    """Universal zone; capacity-1 LEAF_SURGE event open at 2026-10-15;
    household A CONFIRMED, household B WAITLISTED."""
    ctx = setup_open_surge_event(capacity_slots=1, num_households=2)
    event = ctx["event"]
    hh_a = ctx["households"][0]["household"]
    hh_b = ctx["households"][1]["household"]
    bk_a = book_surge_ok(event["id"], hh_a, quantity_bundles=3)
    assert bk_a["status"] == "CONFIRMED"
    bk_b = book_surge_ok(event["id"], hh_b, quantity_bundles=2)
    assert bk_b["status"] == "WAITLISTED"
    ctx.update({"bk_a": bk_a, "bk_b": bk_b})
    return ctx


def test_subscription_cancel_cancels_booking_and_promotes_waitlist(api, admin_headers):
    """PRD section 3.2: "every surge booking of this household for events in
    the subscription's zone that is still `CONFIRMED` or `WAITLISTED` becomes
    `CANCELLED`; each freed confirmed slot is released and immediately
    re-offered to the waitlist per §3.7". PRD section 3.7: "among the event's
    `WAITLISTED` bookings, the earliest created wins".

    Design: Difficulty/transitive_cascade/subscription_cancel_releases_slot_promotes_waitlist
    """
    ctx = _setup_cancel_promotes_scenario()
    sub_a = ctx["households"][0]["subscription"]

    cancelled = validate_success(
        api.cancel_subscription(sub_a["id"], make_resident_headers(ctx["households"][0]["household"]["id"])),
        200)
    assert cancelled["status"] == "CANCELLED"

    bk_a_after = validate_success(api.get_surge_booking(ctx["bk_a"]["id"], admin_headers), 200)
    assert bk_a_after["status"] == "CANCELLED"
    bk_b_after = validate_success(api.get_surge_booking(ctx["bk_b"]["id"], admin_headers), 200)
    assert bk_b_after["status"] == "CONFIRMED"

    event_after = get_surge_event(ctx["event"]["id"])
    assert event_after["reserved_slots"] == 1


def test_subscription_cancel_preserves_slot_invariant(api, admin_headers):
    """PRD section 3.7: "maintaining the invariant that `capacity_slots` always
    equals `reserved_slots` plus the remaining available slots." Cancelling the
    subscriber's booking releases and re-fills the slot, leaving reserved_slots
    at 1 of capacity 1.

    Design: Difficulty/transitive_cascade/subscription_cancel_releases_slot_promotes_waitlist
    """
    ctx = _setup_cancel_promotes_scenario()
    sub_a = ctx["households"][0]["subscription"]

    api.cancel_subscription(sub_a["id"], make_resident_headers(ctx["households"][0]["household"]["id"]))

    assert get_subscription(sub_a["id"])["status"] == "CANCELLED"
    event_after = get_surge_event(ctx["event"]["id"])
    assert event_after["capacity_slots"] == 1
    assert event_after["reserved_slots"] == 1


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / surge_book_then_cancel_slots_unchanged
# ---------------------------------------------------------------------------

def test_surge_book_raises_reserved_slots(api, admin_headers):
    """PRD section 3.7: "if `reserved_slots` is still below `capacity_slots`,
    the booking is created `CONFIRMED` and `reserved_slots` rises by one".

    Design: Difficulty/compensating_invariant/surge_book_then_cancel_slots_unchanged
    """
    ctx = setup_open_surge_event(capacity_slots=2, num_households=1)
    event = ctx["event"]
    assert event["reserved_slots"] == 0

    household = ctx["households"][0]["household"]
    booking = book_surge_ok(event["id"], household, quantity_bundles=2)
    assert_surge_booking(booking)
    assert booking["status"] == "CONFIRMED"

    event_after = get_surge_event(event["id"])
    assert event_after["reserved_slots"] == 1


def test_surge_book_then_cancel_slots_unchanged(api, admin_headers):
    """PRD section 3.7: "Cancelling a `CONFIRMED` booking releases the slot —
    `reserved_slots` drops by one". With no waitlisted bookings, a book
    followed by its cancel returns reserved_slots to its pre-book value.

    Design: Difficulty/compensating_invariant/surge_book_then_cancel_slots_unchanged
    """
    ctx = setup_open_surge_event(capacity_slots=2, num_households=1)
    event = ctx["event"]
    household = ctx["households"][0]["household"]
    assert get_surge_event(event["id"])["reserved_slots"] == 0

    booking = book_surge_ok(event["id"], household, quantity_bundles=2)
    assert get_surge_event(event["id"])["reserved_slots"] == 1

    cancelled = cancel_booking(booking["id"], household)
    assert cancelled["status"] == "CANCELLED"
    assert get_surge_event(event["id"])["reserved_slots"] == 0


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / booking_state_trumps_fiscal
# ---------------------------------------------------------------------------

def _setup_suspended_with_outstanding():
    """Opt-in household: paid base 12000, then 3 strikes -> SUSPENDED with an
    unpaid 2000-cent reinstatement surcharge. A surge event is open in the zone."""
    ctx = setup_suspended_subscription()  # OPT_IN, SUSPENDED, surcharge 2000
    event = _create_event(ctx["zone"]["id"], capacity_slots=5)
    set_clock("2026-10-15T00:00:00Z")
    ctx["event"] = get_surge_event(event["id"])
    return ctx


def test_booking_state_error_trumps_fiscal_error(api, admin_headers):
    """PRD section 2.8: "Every request is validated against an ordered
    pipeline, and the first failing check wins — a request that would fail two
    checks always surfaces the earlier one." State preconditions (step 7,
    `ERR_SUBSCRIPTION_NOT_ACTIVE`) precede fiscal gates (step 12, "a surge
    booking requires the household to carry no subscription with an outstanding
    balance (`ERR_OUTSTANDING_BALANCE`)").

    Design: Difficulty/priority_pair_validation_conflict/booking_state_trumps_fiscal
    """
    ctx = _setup_suspended_with_outstanding()
    household = ctx["household"]

    res = book_surge(ctx["event"]["id"], household, quantity_bundles=2)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)


def test_booking_dual_violation_setup_holds_and_state_wins(api, admin_headers):
    """PRD section 2.8: "the first failing check wins — a request that would
    fail two checks always surfaces the earlier one." PRD section 3.7: "Booking
    requires the event to be `OPEN` (`ERR_SURGE_EVENT_NOT_OPEN`), the household
    to hold an `ACTIVE` subscription (`ERR_SUBSCRIPTION_NOT_ACTIVE`)" and "if
    the household carries any subscription whose `total_due_cents` exceeds its
    `paid_cents`, the booking is rejected with `ERR_OUTSTANDING_BALANCE`."

    Design: Difficulty/priority_pair_validation_conflict/booking_state_trumps_fiscal
    """
    ctx = _setup_suspended_with_outstanding()
    sub = get_subscription(ctx["subscription"]["id"])
    assert sub["status"] == "SUSPENDED"
    assert sub["total_due_cents"] - sub["paid_cents"] == 2000

    res = book_surge(ctx["event"]["id"], ctx["household"], quantity_bundles=2)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)


# ---------------------------------------------------------------------------
# Queue B: surge booking rules
# ---------------------------------------------------------------------------

def test_booking_over_capacity_waitlisted_not_error(api, admin_headers):
    """PRD section 3.7: "Slot allocation itself is never an error: if
    `reserved_slots` is still below `capacity_slots`, the booking is created
    `CONFIRMED` and `reserved_slots` rises by one; if the event is full, the
    booking is created `WAITLISTED`."

    Design: Corner/validations/booking_over_capacity_waitlisted_not_error
    """
    ctx = setup_open_surge_event(capacity_slots=1, num_households=2)
    event = ctx["event"]
    hh_a = ctx["households"][0]["household"]
    hh_b = ctx["households"][1]["household"]

    bk_a = book_surge_ok(event["id"], hh_a, quantity_bundles=2)
    assert bk_a["status"] == "CONFIRMED"

    res = book_surge(event["id"], hh_b, quantity_bundles=4)
    bk_b = validate_success(res, 201)
    assert bk_b["status"] == "WAITLISTED"
    assert get_surge_event(event["id"])["reserved_slots"] == 1


def test_booking_day_conflict_same_date(api, admin_headers):
    """PRD section 3.7: "no same-day conflict: a household already holding a
    `CONFIRMED` or `WAITLISTED` booking for the same `service_date` is rejected
    with `ERR_SURGE_BOOKING_DAY_CONFLICT`."

    Design: Corner/validations/booking_day_conflict_same_date
    """
    ctx = setup_open_surge_event(capacity_slots=5, num_households=1)
    household = ctx["households"][0]["household"]

    ev2 = _create_event(ctx["zone"]["id"], event_type="HOLIDAY_TREE",
                        service_date="2026-11-07", capacity_slots=5)

    bk1 = book_surge_ok(ctx["event"]["id"], household, quantity_bundles=2)
    assert bk1["status"] == "CONFIRMED"

    res = book_surge(ev2["id"], household, quantity_bundles=1)
    validate_error(res, ApiErrorId.ERR_SURGE_BOOKING_DAY_CONFLICT)
    assert get_surge_event(ev2["id"])["reserved_slots"] == 0


def test_booking_on_closed_event(api, admin_headers):
    """PRD section 3.7: "Booking requires the event to be `OPEN`
    (`ERR_SURGE_EVENT_NOT_OPEN`)". PRD section 2.4: "A surge event reads
    `SCHEDULED` before `booking_window_start`, `OPEN` from
    `booking_window_start` up to but not including `booking_window_end`,
    `CLOSED` from `booking_window_end` until the clock date passes the event's
    `service_date`, and `COMPLETED` thereafter."

    Design: Corner/validations/booking_on_closed_event
    """
    ctx = setup_open_surge_event(capacity_slots=5, num_households=1,
                                 clock="2026-11-03T00:00:00Z")
    event = get_surge_event(ctx["event"]["id"])
    assert event["status"] == "CLOSED"

    household = ctx["households"][0]["household"]
    res = book_surge(event["id"], household, quantity_bundles=2)
    validate_error(res, ApiErrorId.ERR_SURGE_EVENT_NOT_OPEN)


def test_booking_cancel_on_terminal_rejected(api, admin_headers):
    """PRD section 3.7: "A resident may cancel their own booking while it is
    `CONFIRMED` or `WAITLISTED` (otherwise `ERR_INVALID_STATE`; a non-owner is
    rejected with `ERR_RESIDENT_NOT_OWNER`)."

    Design: Corner/state_machines/booking_cancel_on_terminal_rejected
    """
    ctx = setup_open_surge_event(capacity_slots=3, num_households=1)
    household = ctx["households"][0]["household"]
    booking = book_surge_ok(ctx["event"]["id"], household, quantity_bundles=2)
    cancel_booking(booking["id"], household)

    res = api.cancel_surge_booking(booking["id"], make_resident_headers(household["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert get_surge_event(ctx["event"]["id"])["reserved_slots"] == 0


def test_surge_event_lifecycle_and_no_show_by_clock(api, admin_headers):
    """PRD section 2.4: "A surge event reads `SCHEDULED` before
    `booking_window_start`, `OPEN` from `booking_window_start` up to but not
    including `booking_window_end`, `CLOSED` from `booking_window_end` until
    the clock date passes the event's `service_date`, and `COMPLETED`
    thereafter." PRD section 3.7: "When the event completes — the clock date
    passes the `service_date` — every booking still `CONFIRMED` is marked
    `NO_SHOW`."

    Design: Corner/state_machines/surge_event_lifecycle_and_no_show_by_clock
    """
    ctx = setup_open_surge_event(capacity_slots=5, num_households=1, clock="2026-09-01T00:00:00Z")
    # The event was created while the clock (2026-09-01) sat before the booking
    # window (2026-10-01): the creation read showed SCHEDULED.
    event = ctx["event"]
    assert event["status"] == "SCHEDULED"

    set_clock("2026-10-15T00:00:00Z")
    event = get_surge_event(event["id"])
    assert event["status"] == "OPEN"
    household = ctx["households"][0]["household"]
    booking = book_surge_ok(event["id"], household, quantity_bundles=2)
    assert booking["status"] == "CONFIRMED"

    set_clock("2026-11-02T00:00:00Z")
    assert get_surge_event(event["id"])["status"] == "CLOSED"

    set_clock("2026-11-08T00:00:00Z")
    assert get_surge_event(event["id"])["status"] == "COMPLETED"
    booking_after = validate_success(api.get_surge_booking(booking["id"], admin_headers), 200)
    assert booking_after["status"] == "NO_SHOW"


def test_occ_surge_booking_stale_version(api, admin_headers):
    """PRD section 2.6: "Creating a surge booking requires the request to carry
    `expected_surge_event_version` holding the client-observed `version` of the
    surge event. Every booking creation or cancellation mutates the event's
    `reserved_slots` and `version`, so a stale expected version means the client
    decided from out-of-date capacity; the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_surge_booking_stale_version
    """
    ctx = setup_open_surge_event(capacity_slots=5, num_households=2)
    event = ctx["event"]
    stale_version = event["version"]
    hh_a = ctx["households"][0]["household"]
    hh_b = ctx["households"][1]["household"]

    bk_a = book_surge_ok(event["id"], hh_a, quantity_bundles=2)
    assert bk_a["status"] == "CONFIRMED"
    # The successful booking advanced the event version; replaying it is stale.
    res = api.create_surge_booking(
        create_surge_booking_payload(event["id"], hh_b["id"], stale_version,
                                     quantity_bundles=1),
        make_resident_headers(hh_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    bookings, meta = (lambda body: (body["data"], body["meta"]))(
        api.list_surge_bookings(admin_headers, params={"surge_event_id": event["id"]}).json())
    assert len(bookings) == 1
    assert bookings[0]["id"] == bk_a["id"]
    assert get_surge_event(event["id"])["reserved_slots"] == 1


def test_waitlist_promotion_order_earliest_first(api, admin_headers):
    """PRD section 3.7: "among the event's `WAITLISTED` bookings, the earliest
    created wins, with ties broken by smaller `quantity_bundles`, and promotion
    continues while capacity remains and waitlisted candidates exist".

    Design: Corner/cross_cutting_layers/waitlist_promotion_order_earliest_first
    """
    ctx = setup_open_surge_event(capacity_slots=1, num_households=3)
    event = ctx["event"]
    hh_a, hh_b, hh_c = (e["household"] for e in ctx["households"])

    bk_a = book_surge_ok(event["id"], hh_a, quantity_bundles=2)
    bk_b = book_surge_ok(event["id"], hh_b, quantity_bundles=5)
    bk_c = book_surge_ok(event["id"], hh_c, quantity_bundles=1)
    assert bk_b["status"] == "WAITLISTED"
    assert bk_c["status"] == "WAITLISTED"

    cancel_booking(bk_a["id"], hh_a)

    # Earliest created (B, qty 5) wins the freed slot — not the smaller bundle (C).
    assert validate_success(api.get_surge_booking(bk_b["id"], admin_headers), 200)["status"] == "CONFIRMED"
    assert validate_success(api.get_surge_booking(bk_c["id"], admin_headers), 200)["status"] == "WAITLISTED"
    assert get_surge_event(event["id"])["reserved_slots"] == 1


def test_immediate_read_after_write_consistency(api, admin_headers):
    """PRD section 2.10: "The consistency model is immediate: every side effect
    of an operation is visible in that operation's own response and in any
    subsequent read, with no asynchronous settlement."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    ctx = setup_open_surge_event(
        capacity_slots=3, num_households=1, event_type="HOLIDAY_TREE",
        service_date="2027-01-03", booking_window_start="2026-12-20T00:00:00Z",
        booking_window_end="2027-01-01T00:00:00Z", clock="2026-12-26T00:00:00Z",
        season_end_date="2027-02-28")
    event = ctx["event"]
    household = ctx["households"][0]["household"]

    booking = book_surge_ok(event["id"], household, quantity_bundles=1)
    assert booking["status"] == "CONFIRMED"  # visible in the mutating response

    event_after = get_surge_event(event["id"])
    assert event_after["reserved_slots"] == 1  # visible on the very next read
