"""Return: the two overage figures computed from one set of meters, the grace
hour on lateness, and the photographic evidence return insists on."""

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
GENEROUS_DECLARATION = {"declared_miles": 520, "declared_generator_hours": 16.0}


def _returned_trip(api, world, **booking_overrides):
    """A trip carried to the brink of return with the canonical three readings."""
    started = fixtures.seed_in_trip_booking(api, world, **booking_overrides)
    fixtures.record_post_trip_evidence(api, world, started["id"])
    return started


def test_segment_wise_overage_bills_a_surplus_that_the_pooled_figure_hides(api):
    """PRD 3.7: "The **billed** figure, `final_overage_cents`, is computed segment by
    segment and includes readings of every type, `MID_TRIP` rows among them." and
    "Because each segment carries its own allowance, **frugality in one segment does
    not offset excess in another**: a renter who drives nothing on Monday and 400
    miles on Tuesday pays for Tuesday." The pooled companion behaves differently:
    "The **reporting** figure, `trip_total_overage_cents`, pools the whole trip's
    allowance and **ignores `MID_TRIP` readings entirely**."

    Design: Difficulty/dual_variant_calc/metered_overage_segment_wise_bills_where_trip_total_reports_zero
    """
    world = fixtures.seed_marketplace(api)
    started = _returned_trip(api, world)

    returned = validate_success(
        api.return_booking(started["id"], world.owner_headers), 200
    )

    # 60 miles over on the first two-night segment plus 4.5 generator hours over.
    assert returned["final_overage_cents"] == 3900 + 1913
    assert returned["final_overage_cents"] == 5813
    assert returned["trip_total_overage_cents"] == 0


def test_the_billed_overage_lands_in_the_final_total_and_the_balance_due(api):
    """PRD 3.7: "`final_total_cents` is the discounted subtotal plus
    `service_fee_cents` plus `final_overage_cents` plus `late_return_fee_cents` plus
    the damage component; every input is already a whole number of cents, so no
    rounding occurs. `balance_due_cents` is `final_total_cents` minus
    `hold_amount_cents` — positive when the renter still owes money, negative when a
    refund is owed." The pooled figure never reaches either number, being "retained
    purely for reconciliation transparency and is **never billed**".

    Design: Difficulty/dual_variant_calc/metered_overage_segment_wise_bills_where_trip_total_reports_zero
    """
    world = fixtures.seed_marketplace(api)
    started = _returned_trip(api, world)

    returned = validate_success(
        api.return_booking(started["id"], world.owner_headers), 200
    )

    assert returned["late_return_fee_cents"] == 0
    assert returned["final_total_cents"] == 151876
    assert returned["balance_due_cents"] == 5813
    assert returned["trip_status"] == TripStatus.RETURNED
    assert returned["settlement_status"] == SettlementStatus.RECONCILING


def test_a_generous_declaration_holds_more_than_the_meters_will_bill(api):
    """PRD 3.7: "The same pooled shape, applied to the renter's declarations rather
    than to readings, produces `estimated_overage_cents` at quote time: the amount by
    which `declared_miles` exceeds `nights` multiplied by `included_miles_per_night`
    — zero if it does not — multiplied by `mileage_overage_rate_cents_per_mile`, plus
    the amount by which `declared_generator_hours` exceeds `nights` multiplied by
    `included_generator_hours_per_night`". That estimate rides into the hold, since
    "`hold_amount_cents` is set to the resulting `quoted_total_cents`".

    Design: Difficulty/dual_variant_calc/variant_switch_from_declared_estimate_to_segment_wise_yields_refund
    """
    world = fixtures.seed_marketplace(api)

    confirmed = fixtures.seed_confirmed_booking(api, world, **GENEROUS_DECLARATION)

    # 120 declared miles and 4.0 declared generator hours beyond the allowances.
    assert confirmed["estimated_overage_cents"] == 7800 + 1700
    assert confirmed["estimated_overage_cents"] == 9500
    assert confirmed["quoted_total_cents"] == 155563
    assert confirmed["hold_amount_cents"] == 155563


def test_the_return_turns_the_overstated_hold_into_a_refund(api):
    """PRD 3.7: "`balance_due_cents` is `final_total_cents` minus
    `hold_amount_cents` — positive when the renter still owes money, negative when a
    refund is owed." At return the declared estimate stops being authoritative,
    because the billed figure is the segment-wise one: "The **billed** figure,
    `final_overage_cents`, is computed segment by segment and includes readings of
    every type, `MID_TRIP` rows among them."

    Design: Difficulty/dual_variant_calc/variant_switch_from_declared_estimate_to_segment_wise_yields_refund
    """
    world = fixtures.seed_marketplace(api)
    started = _returned_trip(api, world, **GENEROUS_DECLARATION)
    assert started["hold_amount_cents"] == 155563

    returned = validate_success(
        api.return_booking(started["id"], world.owner_headers), 200
    )

    assert returned["final_overage_cents"] == 5813
    assert returned["trip_total_overage_cents"] == 0
    assert returned["final_total_cents"] == 151876
    assert returned["balance_due_cents"] == -3687


def test_exactly_sixty_minutes_late_is_not_late(api):
    """PRD 3.7: "Scheduled return is the booking's `end_date` at 11:00:00 UTC." and
    "A rig returned within one full hour of grace — that is, a lateness of 60 minutes
    or fewer, the boundary being inclusive so exactly 60 minutes late is not late —
    carries a `late_return_fee_cents` of 0."

    Design: Difficulty/boundary_precision_check/late_return_grace_admits_exactly_sixty_minutes_and_bills_at_sixty_one
    """
    world = fixtures.seed_marketplace(api)
    started = _returned_trip(api, world)
    fixtures.set_clock(api, "2026-09-02T12:00:00Z")

    returned = validate_success(
        api.return_booking(started["id"], world.owner_headers), 200
    )

    assert returned["late_return_fee_cents"] == 0
    assert returned["final_overage_cents"] == 5813
    assert returned["final_total_cents"] == 151876
    assert returned["balance_due_cents"] == 5813
    assert returned["trip_status"] == TripStatus.RETURNED
    assert returned["settlement_status"] == SettlementStatus.RECONCILING


def test_one_minute_past_the_grace_hour_buys_a_whole_block(api):
    """PRD 3.7: "Beyond the grace hour, the platform counts the minutes past the
    grace window and divides by 60, rounding **up** to a whole number of blocks, so a
    single minute into the second hour buys a whole block. Each block costs 7500
    cents. The total is capped at 20000 basis points of the listing's
    `base_nightly_rate_cents` — twice the nightly rate — that cap being divided by
    10000 and rounded half up, and `late_return_fee_cents` is the smaller of the
    block charge and the cap." One block sits far below the cap, so the cap is not a
    floor.

    Design: Difficulty/boundary_precision_check/late_return_grace_admits_exactly_sixty_minutes_and_bills_at_sixty_one
    """
    world = fixtures.seed_marketplace(api)
    started = _returned_trip(api, world)
    fixtures.set_clock(api, "2026-09-02T12:01:00Z")

    returned = validate_success(
        api.return_booking(started["id"], world.owner_headers), 200
    )

    assert returned["late_return_fee_cents"] == 7500
    assert returned["final_overage_cents"] == 5813
    assert returned["final_total_cents"] == 159376
    assert returned["balance_due_cents"] == 13313
    assert returned["trip_status"] == TripStatus.RETURNED
    assert returned["settlement_status"] == SettlementStatus.RECONCILING


def test_three_post_trip_zones_do_not_satisfy_the_return_photo_gate(api):
    """PRD 3.7: return "requires a meter reading on the booking whose `reading_type`
    is `POST_TRIP`, otherwise `ERR_METER_READINGS_INCOMPLETE`, and `POST_TRIP` trip
    photos covering at least four distinct `zone` values, otherwise
    `ERR_TRIP_PHOTOS_INCOMPLETE`." The reading is in place, so only the zone count can
    fail, and the refusal leaves the trip where it was.

    Design: Corner/errors/return_with_three_post_trip_zones_is_rejected
    """
    world = fixtures.seed_marketplace(api)
    started = fixtures.seed_in_trip_booking(api, world)
    fixtures.record_post_trip_evidence(
        api, world, started["id"], zones=THREE_ZONES
    )

    response = api.return_booking(started["id"], world.renter_headers)
    validate_error(response, ApiErrorId.TRIP_PHOTOS_INCOMPLETE, 422)

    stored = validate_success(api.get_booking(started["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert stored["trip_status"] == TripStatus.IN_TRIP
    assert stored["settlement_status"] == SettlementStatus.HELD
    assert stored["final_total_cents"] == 0

    _rows, meta = validate_paginated(
        api.list_trip_photos(
            factories.page_params(
                booking_id=started["id"], phase=PhotoPhase.POST_TRIP
            ),
            PLATFORM_ADMIN_HEADERS,
        )
    )
    assert meta["total_count"] == 3
