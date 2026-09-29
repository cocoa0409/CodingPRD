"""Two-variant calculations: element retirement forecasting and cancellation settlement."""

from test_helpers import (
    assert_element_forecast,
    assert_ledger,
    assert_money,
    assert_settlement,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_TEST_UTC,
    DESIGN_CYCLE_LIMIT,
    DESIGN_LIFE_YEARS,
    ELEMENT_INSTALLED_ON,
)
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    confirm_booking,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    quote_booking,
    set_clock,
    staffed_course,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_group_coordinator_headers


class TestElementRetirementForecastVariants:
    """The calendar and usage variants of the element retirement forecast."""

    def test_usage_variant_wins_for_a_worn_high_element(self, api, clock):
        """A high element two years old with 14,600 cycles retires on USAGE basis.

        PRD 3.1: "The difference between the variants is not academic: a high element
        installed two years ago that has already absorbed 14,600 participant cycles is
        averaging twenty cycles a day, has 7,300 cycles left, and projects out exactly
        365 days — a retirement date one year away on `USAGE` basis where the calendar
        variant alone would have said ten years."

        Design: Difficulty/dual_variant_calc/element_retirement_forecast_switches_to_usage_basis
        """
        course_id = create_course(api)
        h_id = create_element(
            api,
            course_id,
            "HIGH_ELEMENT",
            installed_on=ELEMENT_INSTALLED_ON,
            initial_cycle_count=14600,
        )

        element = validate_success(api.get_element(h_id, PROGRAM_DIRECTOR))

        assert element["cumulative_cycle_count"] == 14600
        assert element["design_life_years"] == DESIGN_LIFE_YEARS["HIGH_ELEMENT"] == 12
        assert element["cycle_life_limit"] == DESIGN_CYCLE_LIMIT["HIGH_ELEMENT"] == 21900
        assert_element_forecast(
            element,
            calendar="2036-08-10",
            usage="2027-08-10",
            forecast="2027-08-10",
            basis="USAGE",
        )
        assert element["required_belay_set_count"] == 2
        assert element["belay_ready"] is False

    def test_calendar_variant_stands_alone_without_cycle_history(self, api, clock):
        """With no seeded cycles the usage projection has nothing to project from.

        PRD 3.1: "If the average daily rate is zero there is no history to project from,
        so `usage_life_forecast_date` is null and the calendar date stands alone."

        Design: Difficulty/dual_variant_calc/element_retirement_forecast_switches_to_usage_basis
        """
        world = staffed_course(api)
        h_id = create_element(
            api, world["course_id"], "HIGH_ELEMENT", installed_on=ELEMENT_INSTALLED_ON
        )

        element = validate_success(api.get_element(h_id, PROGRAM_DIRECTOR))

        assert element["cumulative_cycle_count"] == 0
        assert element["usage_life_forecast_date"] is None
        assert element["calendar_life_forecast_date"] == "2036-08-10"
        assert element["retirement_forecast_date"] == "2036-08-10"
        assert element["retirement_basis"] == "CALENDAR"


def _two_confirmed_bookings(api):
    """Two identically priced confirmed bookings for one PARTNER client.

    Each booking holds a 341-cent deposit taken from the same 20,000-cent credit
    balance, and each runs an icebreaker followed by a debrief.
    """
    set_clock(api, CLOCK_TEST_UTC)
    world = staffed_course(api)
    gc_id = create_funded_client(api)

    ba_id, _ = create_booking(api, world["course_id"], gc_id, 1)
    add_participant(api, gc_id, ba_id, "ADULT")
    ba_blocks = add_blocks(
        api,
        ba_id,
        [
            (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z"),
            (2, "DEBRIEF", "2026-09-15T09:45:00Z", "2026-09-15T10:15:00Z"),
        ],
    )
    quote_booking(api, ba_id)
    confirm_booking(api, gc_id, ba_id)

    bb_id, _ = create_booking(api, world["course_id"], gc_id, 1)
    add_participant(
        api,
        gc_id,
        bb_id,
        "ADULT",
        full_name="Robin Vale",
        birth_date="1988-11-30",
        weight_kg=71.0,
    )
    add_blocks(
        api,
        bb_id,
        [
            (1, "ICEBREAKER", "2026-09-15T11:00:00Z", "2026-09-15T11:45:00Z"),
            (2, "DEBRIEF", "2026-09-15T11:45:00Z", "2026-09-15T12:15:00Z"),
        ],
    )
    quote_booking(api, bb_id)
    confirm_booking(api, gc_id, bb_id)

    world.update(
        {
            "gc_id": gc_id,
            "gc_headers": make_group_coordinator_headers(gc_id),
            "ba_id": ba_id,
            "ba_b1_id": ba_blocks[0],
            "bb_id": bb_id,
        }
    )
    return world


def _drive_booking_a_to_weather_hold(api, world):
    """Ten days out, a close lightning strike closes the site mid-icebreaker."""
    set_clock(api, "2026-09-05T07:00:00Z")
    api.create_block_assignment(
        world["ba_b1_id"], {"facilitator_id": world["f1_id"]}, PROGRAM_DIRECTOR
    )
    validate_success(api.start_program_block(world["ba_b1_id"], world["f1_headers"]))
    validate_success(
        api.create_weather_observation(
            {
                "course_id": world["course_id"],
                "observed_at": "2026-09-05T07:00:00Z",
                "lightning_distance_km": 6.5,
                "wind_speed_kph": 12.0,
                "air_temp_c": 19.0,
            },
            world["f1_headers"],
        ),
        201,
    )


class TestCancellationSettlementVariants:
    """The weather variant and the client variant of the same cancellation."""

    def test_weather_variant_retains_the_flat_fee_capped_at_the_deposit(self, api):
        """A booking stopped by the operator settles at the flat fee, capped by the deposit.

        PRD 3.9: "Under `OPERATOR_WEATHER_INITIATED` the notice tier is ignored entirely
        and a flat administrative fee of 2,500 cents is retained."

        PRD 3.9: "In both variants the gross figure is then capped:
        `cancellation_fee_cents` is the smaller of the gross fee and
        `deposit_allocated_cents`, so the fee can never exceed money actually held."

        Design: Difficulty/dual_variant_calc/cancellation_settlement_weather_variant_diverges_from_client_variant
        """
        world = _two_confirmed_bookings(api)
        _drive_booking_a_to_weather_hold(api, world)

        booking = validate_success(api.get_booking(world["ba_id"], PROGRAM_DIRECTOR))
        assert booking["status"] == "WEATHER_HOLD"
        assert_money(booking["deposit_required_cents"], 341, "deposit_required_cents")

        cancelled = validate_success(
            api.cancel_booking(
                world["ba_id"], {"reason": "Storm cell over the site"}, world["gc_headers"]
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert_settlement(
            cancelled,
            variant="OPERATOR_WEATHER_INITIATED",
            fee=341,
            refund=0,
            retained=341,
            notice_days=10,
        )
        assert cancelled["deposit_allocated_cents"] == 0
        block = validate_success(api.get_program_block(world["ba_b1_id"], PROGRAM_DIRECTOR))
        assert block["status"] == "ABANDONED"

    def test_client_variant_at_ten_days_notice_forfeits_half_the_deposit(self, api):
        """The identical deposit cancelled on the identical day forfeits 50 percent.

        PRD 3.9: "Under `CLIENT_INITIATED`, a notice of 30 days or more forfeits nothing;
        a notice from 14 through 29 days forfeits 25 percent; a notice from 7 through 13
        days forfeits 50 percent; and a notice of 6 days or fewer, including a negative
        notice, forfeits the whole deposit."

        Design: Difficulty/dual_variant_calc/cancellation_settlement_weather_variant_diverges_from_client_variant
        """
        world = _two_confirmed_bookings(api)
        _drive_booking_a_to_weather_hold(api, world)

        booking = validate_success(api.get_booking(world["bb_id"], PROGRAM_DIRECTOR))
        assert booking["status"] == "CONFIRMED"
        assert_money(booking["deposit_required_cents"], 341, "deposit_required_cents")

        cancelled = validate_success(
            api.cancel_booking(
                world["bb_id"], {"reason": "Group withdrew"}, world["gc_headers"]
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert_settlement(
            cancelled,
            variant="CLIENT_INITIATED",
            fee=171,
            refund=170,
            retained=171,
            notice_days=10,
        )
        assert cancelled["deposit_allocated_cents"] == 0

    def test_client_ledger_absorbs_both_divergent_settlements(self, api):
        """Only the refunded half of the client cancellation returns to credit.

        PRD 3.9: "The ledger then moves in one settled step: `retained_cents` takes the
        `cancellation_fee_cents`, `deposit_allocated_cents` returns to zero, and
        `refund_cents` is added back to the group client's `credit_balance_cents` — the
        compensating half of the client-funds identity."

        Design: Difficulty/dual_variant_calc/cancellation_settlement_weather_variant_diverges_from_client_variant
        """
        world = _two_confirmed_bookings(api)
        _drive_booking_a_to_weather_hold(api, world)

        validate_success(
            api.cancel_booking(
                world["ba_id"], {"reason": "Storm cell over the site"}, world["gc_headers"]
            )
        )
        validate_success(
            api.cancel_booking(
                world["bb_id"], {"reason": "Group withdrew"}, world["gc_headers"]
            )
        )

        client = validate_success(api.get_group_client(world["gc_id"], PROGRAM_DIRECTOR))
        assert_ledger(client, credit=19488, payments=20000)
