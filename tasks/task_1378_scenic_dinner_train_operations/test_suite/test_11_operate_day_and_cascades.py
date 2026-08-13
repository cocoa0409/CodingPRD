"""Operate-day happy path, the clock sweep, the weather-cancel chain, and the
depth-4 agreement-termination cascade (PRD §2.5, §3.4, §3.6, §3.8)."""
import pytest

from test_helpers import (
    AGENT,
    CREW,
    OPS,
    SCHED,
    cancel_excursion,
    create_confirmed_booking,
    create_held_booking,
    get_booking,
    get_excursion,
    get_slot,
    list_rain_checks_for_booking,
    set_clock,
    setup_published_excursion,
    validate_paginated,
    validate_success,
)


def test_operate_day_happy_path_board_checkin_operate(api, scheduler_headers, station_agent_headers):
    """PRD §3.4: "Marking the train operated — `BOARDING → OPERATED`, the excursion's
    terminal success state — writes the day's outcomes in one sweep: the holding slot
    moves `RESERVED → CONSUMED`; bookings in `CHECKED_IN` become `COMPLETED`; bookings
    still merely `CONFIRMED`, their holders never having checked in, become `NO_SHOW`
    with no refund; and crew assignments still `ASSIGNED` become `COMPLETED`."
    PRD §3.6: "Check-in is the `StationAgent`'s day-of action: `CONFIRMED → CHECKED_IN`,
    permitted only while the excursion is `BOARDING` — attempting it against any other
    excursion state is `ERR_INVALID_STATE`."

    Design: Corner/state_machines_operate_day/operate_day_happy_path_board_checkin_operate
    """
    scenario = setup_published_excursion()
    excursion = scenario["excursion"]
    slot = scenario["slot"]
    b1 = create_confirmed_booking(excursion["id"], "go1@x.com", "COACH", 1)
    b2 = create_confirmed_booking(excursion["id"], "go2@x.com", "COACH", 1)

    set_clock("2026-10-15T08:30:00Z")  # the service date itself

    boarding = validate_success(
        api.excursion_event(excursion["id"], {"event_type": "BEGIN_BOARDING"}, scheduler_headers), 200)
    assert boarding["status"] == "BOARDING"

    checked_in = validate_success(
        api.booking_event(b1["id"], {"event_type": "CHECK_IN"}, station_agent_headers), 200)
    assert checked_in["status"] == "CHECKED_IN"

    operated = validate_success(
        api.excursion_event(excursion["id"], {"event_type": "MARK_OPERATED"}, scheduler_headers), 200)
    assert operated["status"] == "OPERATED"

    slot_after = get_slot(slot["id"])
    assert slot_after["status"] == "CONSUMED", "the holding slot is consumed"

    b1_after = get_booking(b1["id"])
    assert b1_after["status"] == "COMPLETED", "checked-in guests complete"
    b2_after = get_booking(b2["id"])
    assert b2_after["status"] == "NO_SHOW", "confirmed-but-absent guests become no-shows"
    assert b2_after["refund_cents"] == 0, "no-shows carry no refund"

    crew_data, _ = validate_paginated(
        api.list_crew_assignments(CREW, params={"excursion_id": excursion["id"]}))
    assert len(crew_data) == 3
    assert all(ca["status"] == "COMPLETED" for ca in crew_data), (
        "every still-ASSIGNED assignment completes")


def test_clock_sweep_expires_held_booking(api, station_agent_headers, operations_manager_headers):
    """PRD §2.5: "A freshly created booking's hold lasts 45 minutes: its `expires_at` is
    its `created_at` plus 45 minutes."
    PRD §2.5: "First, bookings still in `HELD` whose `expires_at` is at or before the new
    clock instant are swept to `CANCELLED` with no refund, processed earliest
    `expires_at` first."
    PRD §3.6: "Bookings cancelled from any other path — swept holds, no-shows,
    rain-checked passengers — carry `refund_cents` of 0."

    Design: Corner/state_machines/clock_sweep_expires_held_booking
    """
    scenario = setup_published_excursion()
    held = create_held_booking(scenario["excursion"]["id"], "held@x.com", "COACH", 2)
    # Created while the clock reads 2026-08-01T00:00:00Z -> expires_at 00:45:00Z.
    assert held["status"] == "HELD"

    set_clock("2026-08-01T00:46:00Z")

    after = get_booking(held["id"])
    assert after["status"] == "CANCELLED", "swept once expires_at <= the clock instant"
    assert after["refund_cents"] == 0, "a swept hold was never paid"


class TestWeatherCancelDepth2Chain:
    """Excursion CANCEL -> booking RAIN_CHECKED -> RainCheck minted; the slot returns
    to OPEN (contrast with RELEASED under agreement termination)."""

    def _setup(self):
        scenario = setup_published_excursion()
        booking = create_confirmed_booking(scenario["excursion"]["id"], "b1@x.com", "COACH", 1)
        assert booking["paid_cents"] == 6000
        return scenario, booking

    def test_weather_cancel_mints_raincheck_for_confirmed_booking(self, api, station_agent_headers):
        """PRD §3.6: "When an excursion is cancelled from `PUBLISHED` or `BOARDING`,
        every `CONFIRMED` or `CHECKED_IN` booking becomes `RAIN_CHECKED`, and the system
        issues one rain-check per such booking: its `booking_id` points at the source
        booking, its `customer_email` is copied across, its `value_cents` equals the
        source booking's `paid_cents`, its `reason` — one of `WEATHER`, `EVENT`, or
        `TRACK_RIGHTS_LOST` — is copied from the excursion's `cancel_reason`, its
        `issued_on` is the logical clock's date, and its `expires_on` is 365 days later,
        redeemable through that date inclusive as §2.5 states."

        Design: Difficulty/transitive_cascade/weather_cancel_depth2_chain
        """
        scenario, booking = self._setup()
        cancel_excursion(scenario["excursion"]["id"], "WEATHER")

        after = get_booking(booking["id"])
        assert after["status"] == "RAIN_CHECKED", "link 1: booking rain-checked by the cascade"

        rain_checks = list_rain_checks_for_booking(booking["id"])
        assert len(rain_checks) == 1, "link 2: the rain-checked booking mints one rain-check"
        rc = rain_checks[0]
        assert rc["value_cents"] == 6000
        assert rc["reason"] == "WEATHER"
        assert rc["status"] == "ISSUED"
        assert rc["booking_id"] == booking["id"]

    def test_weather_cancel_returns_slot_to_open_pool(self, api, scheduler_headers):
        """PRD §3.6: "From `DRAFT`, the cancellation releases the slot back to `OPEN`,
        sweeps `HELD` bookings to `CANCELLED` without refunds, releases `ASSIGNED` crew
        to `RELEASED`, and lets a still-`DRAFT` manifest recompute its now-shrinking
        counts while a `LOCKED` manifest stands untouched. From `PUBLISHED` or `BOARDING`,
        all of that happens plus the rain-check issuance above — and yes, a weather stop
        called mid-boarding still issues rain-checks to guests already checked in."

        Design: Difficulty/transitive_cascade/weather_cancel_depth2_chain
        """
        scenario, booking = self._setup()
        cancel_excursion(scenario["excursion"]["id"], "WEATHER")

        slot_after = get_slot(scenario["slot"]["id"])
        assert slot_after["status"] == "OPEN", (
            "a manual cancel returns the slot to the pool for the same agreement and date")


class TestAgreementTerminateDepth4Chain:
    """Agreement TERMINATE -> slot RELEASED -> excursion CANCELLED (TRACK_RIGHTS_LOST)
    -> booking RAIN_CHECKED -> RainCheck minted; crew released along the way."""

    def _setup(self):
        scenario = setup_published_excursion()
        booking = create_confirmed_booking(scenario["excursion"]["id"], "b1@x.com", "COACH", 1)
        assert booking["paid_cents"] == 6000
        return scenario, booking

    def test_terminate_releases_slot_and_cancels_excursion(self, api, operations_manager_headers,
                                                           scheduler_headers):
        """PRD §3.8: "Every `OPEN` slot under the agreement goes straight to `RELEASED`.
        Every `RESERVED` slot also goes to `RELEASED`, and the excursion holding it —
        whether still `DRAFT`, already `PUBLISHED`, or mid-`BOARDING` — is cancelled with
        `cancel_reason` `TRACK_RIGHTS_LOST`."

        Design: Difficulty/transitive_cascade/agreement_terminate_depth4_chain
        """
        scenario, booking = self._setup()

        terminated = validate_success(
            api.agreement_event(scenario["agreement"]["id"], {"event_type": "TERMINATE"},
                                operations_manager_headers), 200)
        assert terminated["status"] == "TERMINATED"

        slot_after = get_slot(scenario["slot"]["id"])
        assert slot_after["status"] == "RELEASED", "hop 1: RESERVED slot released"

        ex_after = get_excursion(scenario["excursion"]["id"])
        assert ex_after["status"] == "CANCELLED", "hop 2: holding excursion cancelled"
        assert ex_after["cancel_reason"] == "TRACK_RIGHTS_LOST"

    def test_terminate_rainchecks_booking_and_releases_crew(self, api, operations_manager_headers,
                                                            crew_manager_headers):
        """PRD §3.8: "That cancellation is the full §3.6 cascade with the reason pinned:
        `HELD` bookings cancel without refund, `CONFIRMED` and `CHECKED_IN` bookings
        become `RAIN_CHECKED` with a rain-check of reason `TRACK_RIGHTS_LOST` issued for
        each, `ASSIGNED` crew are released, and a `DRAFT` manifest recomputes while a
        `LOCKED` one is left alone."

        Design: Difficulty/transitive_cascade/agreement_terminate_depth4_chain
        """
        scenario, booking = self._setup()
        validate_success(
            api.agreement_event(scenario["agreement"]["id"], {"event_type": "TERMINATE"},
                                operations_manager_headers), 200)

        booking_after = get_booking(booking["id"])
        assert booking_after["status"] == "RAIN_CHECKED", "hop 3: booking rain-checked"

        rain_checks = list_rain_checks_for_booking(booking["id"])
        assert len(rain_checks) == 1, "hop 4: one rain-check minted per rain-checked booking"
        rc = rain_checks[0]
        assert rc["value_cents"] == 6000
        assert rc["reason"] == "TRACK_RIGHTS_LOST"
        assert rc["status"] == "ISSUED"

        crew_data, _ = validate_paginated(
            api.list_crew_assignments(crew_manager_headers,
                                      params={"excursion_id": scenario["excursion"]["id"]}))
        assert len(crew_data) == 3
        assert all(ca["status"] == "RELEASED" for ca in crew_data), (
            "ASSIGNED crew on the cancelled excursion are released")
