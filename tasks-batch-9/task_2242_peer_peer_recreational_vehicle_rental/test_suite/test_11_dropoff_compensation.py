"""Releasing a drop-off slot: the void that unwinds a quote, the handover that
promotes somebody else's waitlisted window, and the second void that fails."""

from test_helpers import (
    ApiErrorId,
    AssignmentStatus,
    DeliveryOption,
    LoyaltyTier,
    PLATFORM_ADMIN_HEADERS,
    SettlementStatus,
    TripStatus,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_WINDOW = ("2026-08-29T14:00:00Z", "2026-08-29T16:00:00Z")
SECOND_WINDOW = ("2026-08-29T18:00:00Z", "2026-08-29T20:00:00Z")


def _scheduled_count(api, campground_id):
    _rows, meta = validate_paginated(
        api.list_delivery_assignments(
            factories.page_params(
                campground_id=campground_id, status=AssignmentStatus.SCHEDULED
            ),
            PLATFORM_ADMIN_HEADERS,
        )
    )
    return meta["total_count"]


def _slot_holder(api, world):
    """A drop-off booking on the canonical listing holding the only daily slot."""
    campground = fixtures.seed_campground(api, daily_dropoff_capacity=1)
    booking, assignment = fixtures.seed_scheduled_dropoff(
        api,
        world,
        campground_id=campground["id"],
        distance_miles=10,
        setup_fee_cents=0,
        window_start=FIRST_WINDOW[0],
        window_end=FIRST_WINDOW[1],
    )
    return campground, booking, assignment


def _two_confirmed_bookings_one_slot(api, world):
    """The slot holder plus a second renter-funded booking left on the waitlist."""
    campground = fixtures.seed_campground(api, daily_dropoff_capacity=1)
    first = fixtures.seed_dropoff_booking(api, world)
    first_assignment = fixtures.create_delivery_assignment(
        api,
        world,
        first["id"],
        campground["id"],
        first["version"],
        window_start=FIRST_WINDOW[0],
        window_end=FIRST_WINDOW[1],
        distance_miles=10,
        setup_fee_cents=0,
    )
    fixtures.approve_booking(api, world, first["id"])
    first_confirmed = fixtures.confirm_booking(api, world, first["id"])

    second_listing = fixtures.add_second_listed_listing(api, world)
    second = validate_success(
        api.create_booking(
            factories.booking_payload(
                second_listing["id"],
                world.renter_id,
                world.plan_id,
                world.policy_id,
                delivery_option=DeliveryOption.CAMPGROUND_DROPOFF,
            ),
            world.renter_headers,
        ),
        201,
    )
    second_assignment = fixtures.create_delivery_assignment(
        api,
        world,
        second["id"],
        campground["id"],
        second["version"],
        window_start=SECOND_WINDOW[0],
        window_end=SECOND_WINDOW[1],
        distance_miles=20,
        setup_fee_cents=0,
    )
    fixtures.approve_booking(api, world, second["id"])
    second_confirmed = fixtures.confirm_booking(api, world, second["id"])

    assert first_assignment["status"] == AssignmentStatus.SCHEDULED
    assert second_assignment["status"] == AssignmentStatus.WAITLISTED
    assert first_confirmed["hold_amount_cents"] == 157643
    assert second_confirmed["hold_amount_cents"] == 146063

    return {
        "campground": campground,
        "first_booking": first_confirmed,
        "first_assignment": first_assignment,
        "second_booking": second_confirmed,
        "second_assignment": second_assignment,
    }


def test_voiding_the_window_puts_the_quote_back_where_it_started(api):
    """PRD 3.6: "Voiding a `SCHEDULED` assignment sets its `status` to `VOIDED`,
    decreases the campground's `scheduled_assignment_count` by one, increments the
    campground's `version`, sets the booking's `delivery_fee_cents` back to 0 and
    recomputes the booking's quote, and runs the promotion procedure for that
    campground and `dropoff_date`." Recomputing means all six steps, and PRD 3.5 keys
    the second of them on the sum the delivery fee just left: "Step two selects the
    `loyalty_tier` from that **pre-discount figure and from nothing else**".

    Design: Difficulty/compensating_invariant/voiding_a_scheduled_dropoff_releases_the_slot_and_unwinds_the_delivery_fee
    """
    world = fixtures.seed_marketplace(api)
    _campground, booking, assignment = _slot_holder(api, world)
    assert booking["quoted_total_cents"] == 146063
    billed = validate_success(
        api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert billed["quoted_total_cents"] == 157643

    voided = validate_success(
        api.void_delivery_assignment(
            assignment["id"],
            factories.void_payload("tow vehicle unavailable, renter will pick up"),
            world.owner_headers,
        ),
        200,
    )
    assert voided["status"] == AssignmentStatus.VOIDED

    restored = validate_success(
        api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert restored["delivery_fee_cents"] == 0
    assert restored["loyalty_tier"] == LoyaltyTier.TIER_1
    assert restored["loyalty_discount_cents"] == 5434
    assert restored["service_fee_cents"] == 15650
    assert restored["quoted_total_cents"] == 146063


def test_voiding_the_window_returns_the_slot_and_promotes_nobody(api):
    """PRD 2.3: "The compensation guarantee here mirrors the ledger's: scheduling an
    assignment and then voiding it, on a campground whose waitlist for that drop-off
    date is empty, returns `scheduled_assignment_count` to exactly its pre-scheduling
    value." PRD 3.6 licenses the empty waitlist: "If the candidate list is empty, or
    if every candidate's window conflicts, no promotion occurs and the campground's
    `scheduled_assignment_count` simply remains at its decremented value — this is a
    normal outcome, not an error."

    Design: Difficulty/compensating_invariant/voiding_a_scheduled_dropoff_releases_the_slot_and_unwinds_the_delivery_fee
    """
    world = fixtures.seed_marketplace(api)
    campground, _booking, assignment = _slot_holder(api, world)
    occupied = validate_success(
        api.get_campground(campground["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert occupied["scheduled_assignment_count"] == 1

    validate_success(
        api.void_delivery_assignment(
            assignment["id"],
            factories.void_payload("tow vehicle unavailable, renter will pick up"),
            world.owner_headers,
        ),
        200,
    )

    released = validate_success(
        api.get_campground(campground["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert released["scheduled_assignment_count"] == 0
    assert _scheduled_count(api, campground["id"]) == 0


def test_handover_completes_one_window_and_promotes_the_waiting_one(api):
    """PRD 3.7: "Because the booking entered `IN_TRIP`, the delivery assignment on
    that booking whose `status` is `SCHEDULED` transitions to `COMPLETED`. Because
    that assignment left `SCHEDULED`, the campground's `scheduled_assignment_count`
    decreases by one and the promotion procedure of §3.6 runs for that campground and
    `dropoff_date`, moving the selected waitlisted assignment to `SCHEDULED` with
    `promoted_from_waitlist` set true." PRD 3.6 says the same of the promoted row: it
    "moves `WAITLISTED → SCHEDULED`, sets `promoted_from_waitlist` to true, and
    increases the campground's `scheduled_assignment_count` by one."

    Design: Difficulty/transitive_cascade/trip_start_promotes_a_waitlisted_dropoff_and_re_debits_the_other_renters_hold
    """
    world = fixtures.seed_marketplace(api)
    stage = _two_confirmed_bookings_one_slot(api, world)
    fixtures.record_pre_trip_evidence(api, world, stage["first_booking"]["id"])

    started = validate_success(
        api.start_booking(stage["first_booking"]["id"], world.owner_headers), 200
    )
    assert started["trip_status"] == TripStatus.IN_TRIP

    completed = validate_success(
        api.get_delivery_assignment(
            stage["first_assignment"]["id"], PLATFORM_ADMIN_HEADERS
        ),
        200,
    )
    assert completed["status"] == AssignmentStatus.COMPLETED

    promoted = validate_success(
        api.get_delivery_assignment(
            stage["second_assignment"]["id"], PLATFORM_ADMIN_HEADERS
        ),
        200,
    )
    assert promoted["status"] == AssignmentStatus.SCHEDULED
    assert promoted["promoted_from_waitlist"] is True

    site = validate_success(
        api.get_campground(stage["campground"]["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert site["scheduled_assignment_count"] == 1


def test_the_promotion_rebills_the_other_booking_and_debits_the_wallet(api):
    """PRD 3.6: a promoted assignment "then bills: its booking's
    `delivery_fee_cents` is set to the assignment's `delivery_fee_cents` and that
    booking's quote is recomputed through the six steps. If that booking's
    `settlement_status` is already `HELD`, the hold is trued up in the same breath —
    the difference between the newly computed `quoted_total_cents` and the old
    `hold_amount_cents` is debited from that renter's `wallet_credit_cents`, and
    `hold_amount_cents` is reset to the new `quoted_total_cents`." The starting
    booking is not re-quoted, because "Handover does not touch the starting booking's
    own `settlement_status`."

    Design: Difficulty/transitive_cascade/trip_start_promotes_a_waitlisted_dropoff_and_re_debits_the_other_renters_hold
    """
    world = fixtures.seed_marketplace(api)
    stage = _two_confirmed_bookings_one_slot(api, world)
    fixtures.record_pre_trip_evidence(api, world, stage["first_booking"]["id"])

    validate_success(
        api.start_booking(stage["first_booking"]["id"], world.owner_headers), 200
    )

    rebilled = validate_success(
        api.get_booking(stage["second_booking"]["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert rebilled["delivery_fee_cents"] == 19000
    assert rebilled["loyalty_tier"] == LoyaltyTier.TIER_2
    assert rebilled["loyalty_discount_cents"] == 10839
    assert rebilled["service_fee_cents"] == 17281
    assert rebilled["quoted_total_cents"] == 161289
    assert rebilled["hold_amount_cents"] == 161289
    assert rebilled["settlement_status"] == SettlementStatus.HELD

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    # 800000 funded, less two holds, less the 15226 true-up on the promoted booking.
    assert renter["wallet_credit_cents"] == 800000 - 157643 - 146063 - 15226
    assert renter["wallet_credit_cents"] == 481068

    starter = validate_success(
        api.get_booking(stage["first_booking"]["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert starter["quoted_total_cents"] == 157643
    assert starter["hold_amount_cents"] == 157643


def test_the_same_window_cannot_be_voided_twice(api):
    """PRD 3.6: "voiding is available from `SCHEDULED` and from `WAITLISTED`", and a
    voided row is out of reach because "its full status vocabulary is `REQUESTED`,
    `SCHEDULED`, `WAITLISTED`, `COMPLETED` and `VOIDED`, of which `COMPLETED` and
    `VOIDED` are terminal." PRD 2.8 rung 13:
    "**Assignment state** — the delivery assignment's `status` is a legal
    origin for the requested transition, otherwise `ERR_ASSIGNMENT_STATE_INVALID`
    (409). Applies to voiding an assignment, and to handover, which carries the same
    code when a booking whose `delivery_option` is `CAMPGROUND_DROPOFF` has no
    `SCHEDULED` assignment." The refusal must not decrement the counter a second time.

    Design: Corner/state_machines/voiding_the_same_assignment_twice_fails_on_the_second_call
    """
    world = fixtures.seed_marketplace(api)
    campground, booking, assignment = _slot_holder(api, world)
    validate_success(
        api.void_delivery_assignment(
            assignment["id"],
            factories.void_payload("renter switched to self pickup"),
            world.owner_headers,
        ),
        200,
    )

    second_attempt = api.void_delivery_assignment(
        assignment["id"],
        factories.void_payload("duplicate void attempt"),
        world.owner_headers,
    )
    validate_error(second_attempt, ApiErrorId.ASSIGNMENT_STATE_INVALID, 409)

    stored = validate_success(
        api.get_delivery_assignment(assignment["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["status"] == AssignmentStatus.VOIDED

    site = validate_success(
        api.get_campground(campground["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert site["scheduled_assignment_count"] == 0

    unwound = validate_success(
        api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert unwound["delivery_fee_cents"] == 0
    assert unwound["quoted_total_cents"] == 146063
