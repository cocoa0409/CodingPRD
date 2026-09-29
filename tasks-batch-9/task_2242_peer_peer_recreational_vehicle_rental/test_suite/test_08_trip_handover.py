"""Confirmation, metering evidence and handover: two independent booking
dimensions, the money that moves at confirmation, and the two preconditions
that guard the start of a trip."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN_HEADERS,
    PhotoPhase,
    SettlementStatus,
    TripStatus,
    Zone,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

THREE_ZONES = (Zone.EXTERIOR_FRONT, Zone.EXTERIOR_REAR, Zone.INTERIOR)
PRE_TRIP_READING = (42000, 120.0, "2026-08-29T15:00:00Z")


def _ledger_count(api, booking_id):
    _rows, meta = validate_paginated(
        api.list_ledger_entries(
            factories.page_params(booking_id=booking_id), PLATFORM_ADMIN_HEADERS
        )
    )
    return meta["total_count"]


def _reading_count(api, booking_id):
    _rows, meta = validate_paginated(
        api.list_meter_readings(
            factories.page_params(booking_id=booking_id), PLATFORM_ADMIN_HEADERS
        )
    )
    return meta["total_count"]


def test_handover_moves_the_trip_dimension_and_leaves_the_hold_alone(api):
    """PRD 3.7: "**The two dimensions advance on different triggers and neither
    implies the other.** Handover moves `trip_status` and leaves `settlement_status`
    completely untouched; reversing a settlement moves `settlement_status` back to
    `RECONCILING` while `trip_status` stays `CLOSED`." The same section confirms the
    handover chain stops short of the money: "Handover does not touch the starting
    booking's own `settlement_status`."

    Design: Difficulty/non_linear_state_machine/booking_two_dimensions_advance_on_different_triggers
    """
    world = fixtures.seed_marketplace(api)
    started = fixtures.seed_in_trip_booking(api, world)

    observed = validate_success(
        api.get_booking(started["id"], PLATFORM_ADMIN_HEADERS), 200
    )

    assert observed["trip_status"] == TripStatus.IN_TRIP
    assert observed["settlement_status"] == SettlementStatus.HELD
    assert observed["hold_amount_cents"] == 146063


def test_reversing_a_settlement_moves_only_the_settlement_dimension(api):
    """PRD 3.7: "reversing a settlement moves `settlement_status` back to
    `RECONCILING` while `trip_status` stays `CLOSED`." That is legal even though
    the same section calls the trip state final: the trip dimension runs "`REQUESTED`
    → `OWNER_APPROVED` → `CONFIRMED` → `IN_TRIP` → `RETURNED` → `CLOSED`", while
    "the settlement dimension runs `NONE` → `HELD` → `RECONCILING` → `SETTLED`, with
    a `DISPUTED` detour off `RECONCILING`, a `RECONCILING` return from `SETTLED`".

    Design: Difficulty/non_linear_state_machine/booking_two_dimensions_advance_on_different_triggers
    """
    world = fixtures.seed_marketplace(api)
    settled = fixtures.seed_settled_booking(api, world)
    assert settled["trip_status"] == TripStatus.CLOSED
    assert settled["settlement_status"] == SettlementStatus.SETTLED

    reversed_row = validate_success(
        api.reverse_settlement(
            settled["id"],
            factories.reversal_payload("duplicate payout run detected by finance"),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )

    assert reversed_row["trip_status"] == TripStatus.CLOSED
    assert reversed_row["settlement_status"] == SettlementStatus.RECONCILING


def test_a_fresh_booking_holds_nothing_and_posts_nothing(api):
    """PRD 3.7 keeps quoting and holding apart: confirmation is "where money first
    moves", and only there is "`hold_amount_cents` ... set to the resulting
    `quoted_total_cents`". A booking is therefore born with both dimensions at
    their opening values — the trip dimension at `REQUESTED` and the settlement
    dimension at `NONE` — and PRD 3.10 names the transition that first posts money:
    "Settlement posts exactly four ledger rows, in a pinned order."

    Design: Corner/state_machines/new_booking_starts_in_requested_with_no_settlement_and_no_ledger
    """
    world = fixtures.seed_marketplace(api)
    booking = fixtures.seed_requested_booking(api, world)

    rows, meta = validate_paginated(
        api.list_ledger_entries(
            factories.page_params(booking_id=booking["id"]), PLATFORM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    stored = validate_success(api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert stored["trip_status"] == TripStatus.REQUESTED
    assert stored["settlement_status"] == SettlementStatus.NONE
    assert stored["hold_amount_cents"] == 0

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert renter["wallet_credit_cents"] == 800000


def test_confirming_a_booking_that_was_never_approved_is_refused(api):
    """PRD 3.7: the trip dimension moves "`OWNER_APPROVED → CONFIRMED`", so a
    `REQUESTED` booking is not a legal origin. PRD 2.8 rung 9: "**Booking trip
    state** — the booking's `trip_status` is a legal origin for the requested trip
    transition, otherwise `ERR_BOOKING_STATE_INVALID` (409). Applies to owner
    approval, renter confirmation, handover, return, settlement and cancellation."

    Design: Corner/state_machines/confirm_from_requested_is_an_invalid_transition
    """
    world = fixtures.seed_marketplace(api)
    booking = fixtures.seed_requested_booking(api, world)

    response = api.confirm_booking(booking["id"], world.renter_headers)
    validate_error(response, ApiErrorId.BOOKING_STATE_INVALID, 409)

    stored = validate_success(api.get_booking(booking["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert stored["trip_status"] == TripStatus.REQUESTED
    assert stored["settlement_status"] == SettlementStatus.NONE
    assert stored["hold_amount_cents"] == 0

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert renter["wallet_credit_cents"] == 800000


def test_an_unfunded_wallet_refuses_confirmation_with_payment_required(api):
    """PRD 3.7: "Confirmation requires that the acting renter be the booking's
    renter, that the listing still be `LISTED`, and that the renter's
    `wallet_credit_cents` be at least the booking's `quoted_total_cents`; an
    underfunded wallet is refused with `ERR_INSUFFICIENT_RENTER_FUNDS` (402)." PRD
    2.8 puts it last in the ladder: "**Renter solvent** —
    `ERR_INSUFFICIENT_RENTER_FUNDS` (402). Applies to three operations: renter
    confirmation, settlement and wallet adjustment."

    Design: Corner/errors/confirm_without_wallet_funds_is_rejected_with_payment_required
    """
    world = fixtures.seed_marketplace(api, fund_cents=0)
    approved = fixtures.seed_approved_booking(api, world)

    response = api.confirm_booking(approved["id"], world.renter_headers)
    validate_error(response, ApiErrorId.INSUFFICIENT_RENTER_FUNDS, 402)

    stored = validate_success(
        api.get_booking(approved["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["trip_status"] == TripStatus.OWNER_APPROVED
    assert stored["settlement_status"] == SettlementStatus.NONE
    assert stored["hold_amount_cents"] == 0

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert renter["wallet_credit_cents"] == 0
    assert _ledger_count(api, approved["id"]) == 0


def test_confirmation_reports_the_hold_and_the_debit_in_its_own_response(api):
    """PRD 3.7: "On success the quote is recomputed from scratch ... and
    `hold_amount_cents` is set to the resulting `quoted_total_cents`. That amount is
    subtracted from the renter's `wallet_credit_cents` and the renter's `version`
    increments. The trip dimension moves `OWNER_APPROVED → CONFIRMED`, the
    settlement dimension moves `NONE → HELD` on the strength of `quoted_total_cents`
    having been computed". The hold is a wallet debit and nothing more, because PRD
    3.10 makes settlement the poster of rows: "Settlement posts exactly four ledger
    rows, in a pinned order."

    Design: Corner/consistency model/confirm_reports_the_hold_and_the_debited_wallet_in_its_own_response
    """
    world = fixtures.seed_marketplace(api)
    approved = fixtures.seed_approved_booking(api, world)

    confirmed = validate_success(
        api.confirm_booking(approved["id"], world.renter_headers), 200
    )

    assert confirmed["trip_status"] == TripStatus.CONFIRMED
    assert confirmed["settlement_status"] == SettlementStatus.HELD
    assert confirmed["hold_amount_cents"] == 146063
    assert confirmed["quoted_total_cents"] == 146063

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert renter["wallet_credit_cents"] == 800000 - 146063
    assert renter["wallet_credit_cents"] == 653937
    assert _ledger_count(api, approved["id"]) == 0


def test_handover_asks_for_the_meter_reading_before_the_photographs(api):
    """PRD 3.7: "There must be at least one meter reading on the booking whose
    `reading_type` is `PRE_TRIP`, otherwise `ERR_METER_READINGS_INCOMPLETE`. The
    booking's `PRE_TRIP` trip photos must cover at least four **distinct** `zone`
    values, otherwise `ERR_TRIP_PHOTOS_INCOMPLETE`". PRD 2.8 orders the pair:
    "**Meter readings complete** — `ERR_METER_READINGS_INCOMPLETE` (422). Applies to
    handover and return." precedes "**Trip photos complete** —
    `ERR_TRIP_PHOTOS_INCOMPLETE` (422). Applies to handover and return."

    Design: Corner/state_machines/trip_start_preconditions_fire_in_priority_order_readings_then_photos
    """
    world = fixtures.seed_marketplace(api)
    confirmed = fixtures.seed_confirmed_booking(api, world)

    bare = api.start_booking(confirmed["id"], world.owner_headers)
    validate_error(bare, ApiErrorId.METER_READINGS_INCOMPLETE, 422)

    fixtures.record_meter_reading(
        api,
        world,
        confirmed["id"],
        "PRE_TRIP",
        PRE_TRIP_READING[0],
        PRE_TRIP_READING[1],
        PRE_TRIP_READING[2],
        as_owner=True,
    )
    for zone in THREE_ZONES:
        fixtures.record_trip_photo(
            api,
            world,
            confirmed["id"],
            PhotoPhase.PRE_TRIP,
            zone,
            as_owner=True,
            image_ref=f"s3://trip/pre-{zone.lower()}.jpg",
        )

    three_zones = api.start_booking(confirmed["id"], world.owner_headers)
    validate_error(three_zones, ApiErrorId.TRIP_PHOTOS_INCOMPLETE, 422)

    stored = validate_success(
        api.get_booking(confirmed["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["trip_status"] == TripStatus.CONFIRMED
    assert stored["settlement_status"] == SettlementStatus.HELD
    assert stored["hold_amount_cents"] == 146063


def test_an_odometer_that_goes_backwards_is_refused(api):
    """PRD 3.7: "Both meters must be non-decreasing: a new reading must not carry an
    `odometer_miles` or a `generator_hours` value below that of the reading
    immediately preceding it when the booking's readings are ordered by ascending
    `recorded_at`, and its `recorded_at` must not equal that of an existing reading
    on the same booking. Either violation is refused with
    `ERR_METER_READING_REGRESSION`." One component is enough, so rising generator
    hours do not rescue a falling odometer.

    Design: Corner/validations/decreasing_odometer_reading_violates_the_regression_rule
    """
    world = fixtures.seed_marketplace(api)
    confirmed = fixtures.seed_confirmed_booking(api, world)
    fixtures.record_meter_reading(
        api,
        world,
        confirmed["id"],
        "PRE_TRIP",
        PRE_TRIP_READING[0],
        PRE_TRIP_READING[1],
        PRE_TRIP_READING[2],
        as_owner=True,
    )

    response = api.create_meter_reading(
        factories.meter_reading_payload(
            confirmed["id"], "MID_TRIP", 41900, 125.0, "2026-08-30T12:00:00Z"
        ),
        world.renter_headers,
    )
    validate_error(response, ApiErrorId.METER_READING_REGRESSION, 422)

    assert _reading_count(api, confirmed["id"]) == 1


def test_repeating_the_previous_meter_values_is_accepted(api):
    """PRD 3.7: "Both meters must be non-decreasing", and the only extra condition
    on the instant is that "its `recorded_at` must not equal that of an existing
    reading on the same booking". A parked night therefore records legally, and PRD
    3.7 confirms nothing else moves: "Recording a reading changes no money field on
    the booking; the numbers are consumed at return."

    Design: Corner/validations/equal_meter_values_satisfy_the_non_decreasing_rule
    """
    world = fixtures.seed_marketplace(api)
    confirmed = fixtures.seed_confirmed_booking(api, world)
    fixtures.record_meter_reading(
        api,
        world,
        confirmed["id"],
        "PRE_TRIP",
        PRE_TRIP_READING[0],
        PRE_TRIP_READING[1],
        PRE_TRIP_READING[2],
        as_owner=True,
    )

    flat = validate_success(
        api.create_meter_reading(
            factories.meter_reading_payload(
                confirmed["id"], "MID_TRIP", 42000, 120.0, "2026-08-30T12:00:00Z"
            ),
            world.renter_headers,
        ),
        201,
    )

    assert flat["odometer_miles"] == 42000
    assert flat["generator_hours"] == 120.0
    assert flat["reading_type"] == "MID_TRIP"
    assert _reading_count(api, confirmed["id"]) == 2
