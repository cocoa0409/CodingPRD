"""Voluntary cancellation refunds (48-hour boundary) and the booking's divergent
terminal branches (PRD §3.6)."""
import pytest

from test_helpers import (
    cancel_excursion,
    create_confirmed_booking,
    get_booking,
    list_rain_checks_for_booking,
    set_clock,
    setup_published_excursion,
    validate_success,
)
from test_helpers.fixtures import FIRST_CLASS_SPEC, LOCO_SPEC


class TestRefundBoundary48Hours:
    """Slot 2026-10-15 start_minute 600 -> slot start = 2026-10-15T10:00:00Z.
    Cancelling at 2026-10-13T10:00:00Z is exactly 48h00m00s before departure."""

    def _setup_confirmed_coach(self):
        scenario = setup_published_excursion()
        booking = create_confirmed_booking(scenario["excursion"]["id"], "r1@x.com", "COACH", 1)
        assert booking["paid_cents"] == 6000, "COACH base fare at REGULAR surge 10000"
        return booking

    def test_refund_full_at_exactly_48h(self, api, station_agent_headers):
        """PRD §3.6: "Cancel at least 48 hours before slot start and `refund_cents` is
        the full `paid_cents`; the boundary is inclusive, so a cancellation exactly 48
        hours and zero seconds before departure still refunds in full."
        PRD §2.7: "For refund purposes, a slot's start instant is the service date's
        midnight UTC plus `start_minute` minutes."

        Design: Difficulty/boundary_precision_check/refund_full_at_exactly_48h
        """
        booking = self._setup_confirmed_coach()
        set_clock("2026-10-13T10:00:00Z")  # exactly 48h00m00s before slot start

        cancelled = validate_success(
            api.booking_event(booking["id"], {"event_type": "CANCEL"}, station_agent_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_cents"] == 6000, "inclusive boundary pays the full refund"

    def test_refund_half_at_one_minute_inside_the_window(self, api, station_agent_headers):
        """PRD §3.6: "Cancel inside that window and `refund_cents` is half of
        `paid_cents`, rounded half-up to a whole cent."
        PRD §2.6: "The same round-half-up convention applies wherever a fractional cent
        could arise, including the half-refund calculation described in §3.6."

        Design: Difficulty/boundary_precision_check/refund_full_at_exactly_48h
        """
        booking = self._setup_confirmed_coach()
        set_clock("2026-10-13T10:01:00Z")  # 47h59m00s before slot start: inside the window

        cancelled = validate_success(
            api.booking_event(booking["id"], {"event_type": "CANCEL"}, station_agent_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_cents"] == 3000, "round_half_up(6000 * 0.5)"


def test_refund_half_inside_48h_window(api, station_agent_headers):
    """PRD §3.6: "Cancel inside that window and `refund_cents` is half of `paid_cents`,
    rounded half-up to a whole cent."
    PRD §2.6: "Base fares per passenger are fixed by class: 6000 cents for `COACH`,
    11000 cents for `FIRST_CLASS`, and 15000 cents for `DINING`."

    Design: Corner/calculations/refund_half_inside_48h_window
    """
    scenario = setup_published_excursion(car_specs=[LOCO_SPEC, FIRST_CLASS_SPEC])
    booking = create_confirmed_booking(scenario["excursion"]["id"], "fc@x.com", "FIRST_CLASS", 1)
    assert booking["paid_cents"] == 11000, "FIRST_CLASS base fare at REGULAR surge 10000"

    set_clock("2026-10-13T11:00:00Z")  # 47h before the 2026-10-15T10:00:00Z slot start
    cancelled = validate_success(
        api.booking_event(booking["id"], {"event_type": "CANCEL"}, station_agent_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refund_cents"] == 5500, "round_half_up(11000 * 0.5)"


class TestBookingBranchingTerminalPaths:
    """Two CONFIRMED bookings fork into divergent terminal states: voluntary CANCELLED
    (full refund, no rain-check) vs weather-cascade RAIN_CHECKED (refund 0, rain-check
    minted for the full paid amount)."""

    def _setup_two_confirmed(self):
        scenario = setup_published_excursion()
        ex_id = scenario["excursion"]["id"]
        b1 = create_confirmed_booking(ex_id, "b1@x.com", "COACH", 1)
        b2 = create_confirmed_booking(ex_id, "b2@x.com", "COACH", 1)
        assert b1["paid_cents"] == 6000 and b2["paid_cents"] == 6000
        return scenario, b1, b2

    def test_voluntary_cancel_branch_full_refund_no_raincheck(self, api, station_agent_headers):
        """PRD §3.6: "Cancel at least 48 hours before slot start and `refund_cents` is
        the full `paid_cents`; the boundary is inclusive, so a cancellation exactly 48
        hours and zero seconds before departure still refunds in full."
        PRD §3.6: "Rain-checks exist only because excursions die."

        Design: Difficulty/non_linear_state_machine/booking_branching_divergent_terminal_paths
        """
        # Clock stays at the 2026-08-01 default, far beyond the 48-hour refund line.
        scenario, b1, _ = self._setup_two_confirmed()

        cancelled = validate_success(
            api.booking_event(b1["id"], {"event_type": "CANCEL"}, station_agent_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_cents"] == 6000, "full refund this far before departure"

        rain_checks = list_rain_checks_for_booking(b1["id"])
        assert rain_checks == [], "a voluntary cancellation mints no rain-check"

    def test_weather_cancel_branch_rainchecked_with_zero_refund(self, api, station_agent_headers,
                                                                operations_manager_headers):
        """PRD §3.6: "When an excursion is cancelled from `PUBLISHED` or `BOARDING`,
        every `CONFIRMED` or `CHECKED_IN` booking becomes `RAIN_CHECKED`, and the system
        issues one rain-check per such booking: its `booking_id` points at the source
        booking, its `customer_email` is copied across, its `value_cents` equals the
        source booking's `paid_cents`, its `reason` — one of `WEATHER`, `EVENT`, or
        `TRACK_RIGHTS_LOST` — is copied from the excursion's `cancel_reason`, its
        `issued_on` is the logical clock's date, and its `expires_on` is 365 days later,
        redeemable through that date inclusive as §2.5 states."
        PRD §3.6: "Bookings cancelled from any other path — swept holds, no-shows,
        rain-checked passengers — carry `refund_cents` of 0."

        Design: Difficulty/non_linear_state_machine/booking_branching_divergent_terminal_paths
        """
        scenario, _, b2 = self._setup_two_confirmed()

        cancel_excursion(scenario["excursion"]["id"], "WEATHER")

        booking = get_booking(b2["id"])
        assert booking["status"] == "RAIN_CHECKED", "weather cascade rain-checks the booking"
        assert booking["refund_cents"] == 0, "rain-checked passengers carry refund_cents 0"

        rain_checks = list_rain_checks_for_booking(b2["id"])
        assert len(rain_checks) == 1, "one rain-check per rain-checked booking"
        rc = rain_checks[0]
        assert rc["value_cents"] == 6000, "value equals the source booking's paid_cents"
        assert rc["status"] == "ISSUED"
        assert rc["reason"] == "WEATHER", "reason copied from the excursion's cancel_reason"
