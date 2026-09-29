"""Two formulas whose internal ordering is part of the contract: the taxed
nightly amount on a reservation, and the six-step attrition penalty that closes
a block."""

from test_helpers import (
    COORDINATOR,
    advance_to_cutoff_and_sweep,
    advance_to_event_end_and_close,
    read_block,
    report_no_show,
    set_clock,
    setup_open_block_with_reservations,
    validate_success,
)

FOUR_NIGHT_STAY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 2},
]

# One stay per length, each for a different delegate: 4, 2 and 1 nights.
THREE_STAY_LENGTHS = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 2},
    {"check_in_date": "2026-09-16", "check_out_date": "2026-09-18", "occupants": 1},
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-15", "occupants": 1},
]

# Two overlapping stays inside a two-room block: 4 nights and 2 nights.
TWO_ROOM_STAYS = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-16", "occupants": 1},
]

SMALL_BLOCK = {"reduction_rights_pct": 0.50}


class TestReservationChargeRoundingOrder:
    """The taxed nightly amount is rounded before it is multiplied out."""

    def test_four_night_charge_rounds_each_night_before_multiplying(self, api):
        """PRD §3.4: "`total_room_charge_cents` is then computed with the
        rounding order pinned: the taxed nightly amount is the
        `quoted_nightly_rate_cents` multiplied by one plus
        `room_tax_pct_snapshot`, **rounded half up to whole cents at that point**,
        and the stay total is that whole-cent nightly amount multiplied by
        `room_nights`."
        PRD §2.6: "Summing untaxed nights and taxing the sum is a different and
        incorrect computation that produces a different total."

        Design: Difficulty/combinatorial_formula/reservation_charge_rounds_per_night_before_multiplying
        """
        ctx = setup_open_block_with_reservations(FOUR_NIGHT_STAY, general_rooms=6)
        reservation = ctx["reservations"][0]

        assert reservation["room_nights"] == 4
        assert reservation["quoted_nightly_rate_cents"] == 21900
        assert reservation["room_tax_pct_snapshot"] == 0.1475
        assert reservation["total_room_charge_cents"] == 100520, (
            "25130 taxed cents per night times 4 nights is 100520, got "
            f"{reservation['total_room_charge_cents']}"
        )
        # Taxing the four-night untaxed subtotal instead would produce 100521.
        assert reservation["total_room_charge_cents"] != 100521

    def test_every_stay_length_is_a_multiple_of_the_pinned_nightly_amount(self, api):
        """PRD §2.6: "The single most consequential instance is the taxed nightly
        amount on a reservation: the nightly rate is taxed and rounded to whole
        cents *first*, and only then multiplied by the number of nights."
        PRD §3.4: "`room_nights` is the number of whole days between
        `check_in_date` and `check_out_date`."

        Design: Difficulty/combinatorial_formula/reservation_charge_rounds_per_night_before_multiplying
        """
        ctx = setup_open_block_with_reservations(THREE_STAY_LENGTHS, general_rooms=6)
        four_night, two_night, one_night = ctx["reservations"]

        assert one_night["room_nights"] == 1
        assert one_night["total_room_charge_cents"] == 25130
        assert two_night["room_nights"] == 2
        assert two_night["total_room_charge_cents"] == 50260, (
            "two nights at the pinned 25130 cents is 50260, got "
            f"{two_night['total_room_charge_cents']}"
        )
        # Taxing the two-night untaxed subtotal 43800 would round up to 50261.
        assert two_night["total_room_charge_cents"] != 50261
        assert four_night["total_room_charge_cents"] == 100520
        for reservation in ctx["reservations"]:
            assert (
                reservation["total_room_charge_cents"]
                == 25130 * reservation["room_nights"]
            )


class TestAttritionPenaltyWithNoShowNights:
    """Closure prices the shortfall over three interacting room-night inputs."""

    def test_close_prices_the_shortfall_after_a_no_show_is_billed(self, api):
        """PRD §3.7: "The **actual room nights** are read after the cascade has
        fully settled: the sum of `room_nights` over every reservation of every
        sub-block of the block whose `reservation_status` is `CONFIRMED`, plus
        one night for each reservation whose `reservation_status` is `NO_SHOW`."
        PRD §3.7: "The **penalty rate** is selected by tier from the shortfall
        ratio: 50 percent when the ratio is less than or equal to 0.10;
        otherwise 70 percent when the ratio is less than or equal to 0.25;
        otherwise 90 percent."
        PRD §3.5: "On success the guest is billed for exactly one night:
        `no_show_billed_cents` is the taxed nightly amount —
        `quoted_nightly_rate_cents` multiplied by one plus
        `room_tax_pct_snapshot`, rounded half up to whole cents — multiplied by
        the single billed no-show night."

        Design: Difficulty/combinatorial_formula/attrition_penalty_combines_no_show_nights_with_nested_max_and_tier
        """
        ctx = setup_open_block_with_reservations(
            TWO_ROOM_STAYS,
            general_rooms=2,
            contracted_rooms_per_night=2,
            block_overrides=SMALL_BLOCK,
            confirmation_number="CN-SUM26-002",
        )
        short_stay = ctx["reservations"][1]
        ctx = advance_to_cutoff_and_sweep(ctx)

        set_clock("2026-09-15T00:00:00Z")
        report_no_show(short_stay["id"], ctx["hotel"]["id"])
        ctx = advance_to_event_end_and_close(ctx)

        assert ctx["block"]["status"] == "CLOSED"
        # Adjusted 8 room nights, actual 4 confirmed + 1 no-show night, protected
        # 6, shortfall 1, ratio 0.125 selects the 70 percent tier.
        assert ctx["block"]["attrition_liability_cents"] == 15330, (
            "1 shortfall night at 21900 cents and 70 percent is 15330, got "
            f"{ctx['block']['attrition_liability_cents']}"
        )

        no_show = validate_success(api.get_reservation(short_stay["id"], COORDINATOR))
        assert no_show["reservation_status"] == "NO_SHOW"
        assert no_show["no_show_billed_cents"] == 25130

        guest = validate_success(
            api.get_attendee(ctx["attendees"][1]["id"], COORDINATOR)
        )
        assert guest["no_show_strikes"] == 1

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 4

    def test_without_the_no_show_the_same_block_closes_at_zero_exposure(self, api):
        """PRD §3.7: "The **shortfall** is the protected room nights minus the actual
        room nights, floored at zero — it is never negative."
        PRD §3.7: "The **protected room nights** are the adjusted contracted room
        nights multiplied by the allowed pickup ratio of 80 percent, rounded
        half up to a whole number of room nights."
        PRD §3.9: "Closure freezes the attrition exposure:
        `attrition_liability_cents` is set to the post-reduction attrition
        penalty exposure defined in §3.7, computed against the block as it
        finally stands."

        Design: Difficulty/combinatorial_formula/attrition_penalty_combines_no_show_nights_with_nested_max_and_tier
        """
        ctx = setup_open_block_with_reservations(
            TWO_ROOM_STAYS,
            general_rooms=2,
            contracted_rooms_per_night=2,
            block_overrides=SMALL_BLOCK,
            confirmation_number="CN-SUM26-002",
        )
        ctx = advance_to_cutoff_and_sweep(ctx)
        ctx = advance_to_event_end_and_close(ctx)

        # Both stays remain CONFIRMED, so actual is 4 + 2 == 6 room nights and
        # the protected figure of 6 leaves no shortfall to price.
        assert ctx["block"]["status"] == "CLOSED"
        assert ctx["block"]["attrition_liability_cents"] == 0

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 6
        assert read_block(ctx["block"]["id"])["contracted_rooms_per_night"] == 2
