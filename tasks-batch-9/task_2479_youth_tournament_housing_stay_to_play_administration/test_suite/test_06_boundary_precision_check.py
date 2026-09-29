"""Values sitting exactly on a threshold, and the value one step away.

The cancellation tier table and the invoice's billable-scope test are both
inclusive at their lower edge, so each is exercised at the edge and immediately
outside it.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    ApiErrorId,
    assertions,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS

_AUTUMN_CUP = {
    "name": "Autumn Cup 2026",
    "start_date": "2026-09-15",
    "end_date": "2026-09-18",
    "booking_deadline": "2026-09-10T00:00:00Z",
}


def _two_cancellable_bookings_env(api) -> fx.Env:
    """Two four-room bookings arriving 2026-09-15, which the startup clock of
    2026-08-01 puts exactly forty-five days out."""
    env = fx.executed_contract_env(
        api,
        tournament_overrides=dict(_AUTUMN_CUP),
        contract_overrides={"cutoff_date": "2026-08-25"},
        block_overrides={
            "block_size_rooms": 8,
            "arrival_date": "2026-09-15",
            "departure_date": "2026-09-18",
            "release_deadline": "2026-08-30",
        },
    )
    fx.add_team(env)
    fx.add_registration(env)
    booking_a = fx.add_booking(
        env,
        rooms_requested=4,
        check_in_date="2026-09-15",
        check_out_date="2026-09-18",
    )

    team_b = fx.create_team(
        api, name="Alpha SC 16U", org_contact_email="alpha16@example.com"
    )
    registration_b = fx.add_registration(env, team=team_b)
    booking_b = fx.add_booking(
        env,
        registration=registration_b,
        rooms_requested=4,
        check_in_date="2026-09-15",
        check_out_date="2026-09-18",
    )
    env.bookings = [booking_a, booking_b]
    return env


def _zero_night_actualization_env(api) -> fx.Env:
    """A checked-out booking whose hotel reported zero room nights, so nothing on
    the contract has accrued a rebate."""
    env = fx.executed_contract_env(
        api,
        block_overrides={"block_size_rooms": 4},
        contract_overrides={"attrition_threshold_pct": 0.05},
    )
    fx.add_team(env)
    fx.add_registration(env)
    fx.add_booking(env, rooms_requested=4)
    env.booking = fx.submit_rooming_list(env)
    env.booking = fx.confirm_booking(env)
    fx.close_booking_window(env)
    fx.actualize(env, 0)
    return env


class TestCancellationFreeTierBoundary:
    """Forty-five days out is free; forty-four days out is not."""

    def test_cancelling_at_exactly_forty_five_days_out_costs_nothing(self, api):
        """The clock at 2026-08-01 is exactly forty-five whole days from a
        2026-09-15 arrival, and the tier is inclusive at that lower bound.

        PRD §3.5: "The system first computes the **days out**: take the instant of
        `check_in_date` at midnight UTC, subtract the current logical instant, and
        take the whole number of 86,400-second days in that difference, rounding
        **down**."

        PRD §3.5: "At forty-five days out or more, `penalty_room_nights` is 0 —
        cancellation is free."

        PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`."

        Design: Difficulty/boundary_precision_check/cancellation_free_tier_boundary_exact_45_days
        """
        env = _two_cancellable_bookings_env(api)
        booking_a = env.bookings[0]
        assert booking_a["projected_room_nights"] == 12

        cancelled = validate_success(
            api.cancel_booking(booking_a["id"], f.cancel_payload(), HM)
        )

        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["penalty_room_nights"] == 0
        assert cancelled["penalty_cents"] == 0

    def test_cancelling_one_day_later_falls_into_the_quarter_tier(self, api):
        """Moving the clock a single day to 2026-08-02 makes it forty-four days
        out, which charges a quarter of the twelve projected room nights.

        PRD §3.5: "From twenty-one days out up to forty-four,
        `penalty_room_nights` is one quarter of `projected_room_nights`, rounded
        **up** to a whole room night."

        PRD §3.5: "Because the boundaries are inclusive, a cancellation at
        exactly forty-five days out is free while one at forty-four days out falls
        into the quarter tier."

        PRD §3.5: "`penalty_cents` is then `penalty_room_nights` multiplied by the
        `negotiated_nightly_rate_cents` of the contract that owns the booking's
        room block — reached from the booking through its block, since the rate
        lives on the contract rather than on the block."

        Design: Difficulty/boundary_precision_check/cancellation_free_tier_boundary_exact_45_days
        """
        env = _two_cancellable_bookings_env(api)
        booking_b = env.bookings[1]
        assert booking_b["projected_room_nights"] == 12
        fx.set_clock(api, "2026-08-02T00:00:00Z")

        cancelled = validate_success(
            api.cancel_booking(booking_b["id"], f.cancel_payload(), HM)
        )

        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["penalty_room_nights"] == 3
        assert cancelled["penalty_cents"] == 44700


class TestEmptyInvoiceScopeZeroRoomNights:
    """Zero billable room nights blocks an invoice; one room night does not."""

    def test_an_invoice_over_zero_reported_room_nights_is_refused(self, api):
        """A report of zero checks the team out without accruing anything, so the
        contract has no billable scope to invoice.

        PRD §3.7: "The first report with `reported_room_nights` greater than 0
        moves the money axis `NOT_DUE → ACCRUED`, provided `booking_status` is
        `CONFIRMED` or `CHECKED_OUT`, and computes `rebate_accrued_cents`."

        PRD §3.8: "The invoice **scope** is the set of bookings whose
        `room_block_id` belongs to a block of this contract, whose
        `booking_status` is `CHECKED_OUT`, and whose `rebate_status` is
        `ACCRUED`, taken in ascending `created_at` order so that line emission is
        reproducible."

        PRD §3.8: "If the scope contains no booking at all, or if the resulting
        `invoiced_room_nights` is 0, the request is rejected with
        `ERR_NO_BILLABLE_ROOM_NIGHTS`."

        Design: Difficulty/boundary_precision_check/empty_invoice_scope_zero_room_nights
        """
        env = _zero_night_actualization_env(api)
        booking = env.refresh_booking()
        assert booking["booking_status"] == "CHECKED_OUT"
        assert booking["rebate_status"] == "NOT_DUE"
        assert booking["actualized_room_nights"] == 0

        response = api.create_rebate_invoice(
            f.rebate_invoice_payload(env.contract_id), HM
        )

        validate_error(
            response, ApiErrorId.ERR_NO_BILLABLE_ROOM_NIGHTS.value, expected_status=422
        )

    def test_a_single_reported_room_night_makes_the_invoice_billable(self, api):
        """Restating the figure to one room night accrues 900 cents, which is
        enough scope for the invoice and leaves the attrition threshold met.

        PRD §3.7: "A later report therefore *restates* the figure rather than
        adding to it."

        PRD §3.8: "`invoiced_room_nights` is the sum of `actualized_room_nights`
        across the scope."

        PRD §3.8: "Raising the invoice also moves every in-scope booking's
        `rebate_status` from `ACCRUED` to `INVOICED`, leaving each booking's
        `booking_status` at `CHECKED_OUT`."

        Design: Difficulty/boundary_precision_check/empty_invoice_scope_zero_room_nights
        """
        env = _zero_night_actualization_env(api)
        fx.actualize(env, 1)
        booking = env.refresh_booking()
        assert booking["booking_status"] == "CHECKED_OUT"
        assert booking["actualized_room_nights"] == 1
        assert booking["rebate_accrued_cents"] == 900

        invoice = validate_success(
            api.create_rebate_invoice(f.rebate_invoice_payload(env.contract_id), HM),
            expected_status=201,
        )

        assert invoice["invoiced_room_nights"] == 1
        assert invoice["invoiced_rebate_cents"] == 900
        assert invoice["attrition_shortfall_room_nights_per_block"] == 0
        assert invoice["attrition_penalty_cents"] == 0
        assert invoice["total_due_cents"] == 900
        assertions.assert_rebate_ledger_conserved(invoice)
        assert env.refresh_booking()["rebate_status"] == "INVOICED"
