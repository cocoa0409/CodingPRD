"""The machine fleet: session cool-down, the jam loop and the fourth jam.

The fleet's states are re-entered rather than walked once, so each test pins
what has changed on re-entry, and the cool-down window is checked on both sides
of its open upper end.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_machine_state,
    assert_stamped_at,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

JAM_NOTE = "crushed bottle wedged in the intake"


def _machine_world(api):
    """An OPERATIONAL centre with one PET machine, a label and an anonymous visit."""
    world = h.build_world(api, center_overrides={"site_name": "Bend Redemption Center"})
    visit = h.open_center_machine_visit(api, world.center_id, world.machine_id)
    return world, visit


class TestJamLoop:
    """IDLE → COUNTING → JAMMED → IDLE → COUNTING is legal and not a no-op."""

    def test_jam_parks_the_machine_and_the_visit(self, api):
        """The first jam of the day jams the machine and holds the visit.

        PRD: "Reporting a jam while `jam_count_today` for the current logical date is
        strictly below 3 moves the machine `COUNTING → JAMMED`."

        Design: Difficulty/non_linear_state_machine/machine_jam_cycle_counting_jammed_idle_counting
        """
        world, visit = _machine_world(api)
        h.add_lot(api, visit["id"], world.product_id, 40, world.center_headers)

        opened = h.open_session(api, world.machine_id, visit["id"], world.center_headers)
        assert_machine_state(opened, "COUNTING", open_session_count=1)
        assert_stamped_at(opened["session_started_at"], "2026-08-05T09:00:00Z")

        h.set_clock(api, "2026-08-05T09:01:00Z")
        jammed = validate_success(
            api.post_machine_event(
                world.machine_id,
                f.machine_event_payload("JAM_REPORTED", visit["id"], JAM_NOTE),
                world.center_headers,
            )
        )

        assert_machine_state(jammed, "JAMMED", jam_count_today=1)
        assert jammed["jam_day"] == "2026-08-05"

        held = h.read_visit(api, visit["id"], world.center_headers)
        assert held["count_status"] == "JAM_HOLD"
        assert held["requires_manual_recount"] is True
        assert held["jam_events_count"] == 1

    def test_clearing_the_jam_returns_both_to_their_earlier_states(self, api):
        """After the clear the machine counts again but the recount flag latches.

        PRD: "Clearing the jam moves the machine `JAMMED → IDLE`, stamps
        `last_session_closed_at` with the current logical instant, clears
        `session_started_at` to null, returns `open_session_count` to 0, and cascades the
        visit's `count_status` back `JAM_HOLD → COUNTING`."

        Design: Difficulty/non_linear_state_machine/machine_jam_cycle_counting_jammed_idle_counting
        """
        world, visit = _machine_world(api)
        h.add_lot(api, visit["id"], world.product_id, 40, world.center_headers)
        h.open_session(api, world.machine_id, visit["id"], world.center_headers)
        h.set_clock(api, "2026-08-05T09:01:00Z")
        h.report_jam(api, world.machine_id, visit["id"], world.center_headers, JAM_NOTE)

        h.set_clock(api, "2026-08-05T09:02:00Z")
        cleared = validate_success(
            api.post_machine_event(
                world.machine_id,
                f.machine_event_payload("JAM_CLEARED", visit["id"]),
                world.center_headers,
            )
        )

        assert_machine_state(cleared, "IDLE", open_session_count=0)
        assert_stamped_at(cleared["last_session_closed_at"], "2026-08-05T09:02:00Z")

        resumed = h.read_visit(api, visit["id"], world.center_headers)
        assert resumed["count_status"] == "COUNTING"
        assert resumed["requires_manual_recount"] is True

        h.set_clock(api, "2026-08-05T09:07:00Z")
        reopened = h.open_session(
            api, world.machine_id, visit["id"], world.center_headers
        )
        assert reopened["status"] == "COUNTING"
        assert_stamped_at(reopened["session_started_at"], "2026-08-05T09:07:00Z")
        assert reopened["jam_hold_count"] == 1
        assert reopened["jam_count_today"] == 1


class TestFourthJamOfTheDay:
    """The day's fourth jam cascades machine → centre → visit in one request."""

    @staticmethod
    def _three_jams_already_cleared(api):
        world, visit = _machine_world(api)
        h.add_lot(api, visit["id"], world.product_id, 40, world.center_headers)
        cycle_minutes = [(0, 1, 2), (7, 8, 9), (14, 15, 16)]
        for open_at, jam_at, clear_at in cycle_minutes:
            h.set_clock(api, f"2026-08-05T09:{open_at:02d}:00Z")
            h.open_session(api, world.machine_id, visit["id"], world.center_headers)
            h.set_clock(api, f"2026-08-05T09:{jam_at:02d}:00Z")
            h.report_jam(api, world.machine_id, visit["id"], world.center_headers)
            h.set_clock(api, f"2026-08-05T09:{clear_at:02d}:00Z")
            h.clear_jam(api, world.machine_id, visit["id"], world.center_headers)
        h.set_clock(api, "2026-08-05T09:21:00Z")
        h.open_session(api, world.machine_id, visit["id"], world.center_headers)
        h.set_clock(api, "2026-08-05T09:22:00Z")
        return world, visit

    def test_fourth_jam_takes_the_machine_out_of_service(self, api):
        """With three jams on the clock the fourth skips JAMMED entirely.

        PRD: "Reporting a jam while `jam_count_today` for the current date already equals
        3 moves the machine `COUNTING → OUT_OF_SERVICE` instead of to `JAMMED`."

        Design: Difficulty/transitive_cascade/fourth_jam_takes_machine_out_of_service_and_suspends_center
        """
        world, visit = self._three_jams_already_cleared(api)

        out = validate_success(
            api.post_machine_event(
                world.machine_id,
                f.machine_event_payload(
                    "JAM_REPORTED", visit["id"], "fourth jam of the day"
                ),
                world.center_headers,
            )
        )

        assert_machine_state(
            out, "OUT_OF_SERVICE", jam_count_today=4, open_session_count=0
        )
        assert out["jam_hold_count"] == 4
        assert out["jam_day"] == "2026-08-05"
        assert out["session_started_at"] is None

    def test_fourth_jam_suspends_the_whole_centre_and_holds_the_visit(self, api):
        """The only machine leaving service takes the centre down with it.

        PRD: "It additionally recomputes the hosting centre's
        `out_of_service_machine_count`, and when that count has reached `machine_count` it
        cascades the centre `OPERATIONAL → SUSPENDED` with `suspension_reason`
        `MACHINE_FLEET_DOWN`."

        Design: Difficulty/transitive_cascade/fourth_jam_takes_machine_out_of_service_and_suspends_center
        """
        world, visit = self._three_jams_already_cleared(api)
        h.report_jam(
            api,
            world.machine_id,
            visit["id"],
            world.center_headers,
            "fourth jam of the day",
        )

        center = h.read_center(api, world.center_id, world.center_headers)
        assert center["machine_count"] == 1
        assert center["out_of_service_machine_count"] == 1
        assert center["status"] == "SUSPENDED"
        assert center["suspension_reason"] == "MACHINE_FLEET_DOWN"

        held = h.read_visit(api, visit["id"], world.center_headers)
        assert held["count_status"] == "JAM_HOLD"
        assert held["jam_events_count"] == 4
        assert held["requires_manual_recount"] is True


class TestSessionCooldownWindow:
    """The five-minute cool-down window is open at its upper end."""

    @staticmethod
    def _machine_idle_since_nine_ten(api):
        world, visit = _machine_world(api)
        h.open_session(api, world.machine_id, visit["id"], world.center_headers)
        h.set_clock(api, "2026-08-05T09:10:00Z")
        h.machine_event(
            api,
            world.machine_id,
            "SESSION_CLOSE",
            world.center_headers,
            visit_id=visit["id"],
        )
        return world, visit

    def test_session_open_one_second_early_is_refused(self, api):
        """At 09:14:59 the window is still closed and the open is refused.

        PRD: "an attempt at any instant from `last_session_closed_at` up to but not
        including `last_session_closed_at` plus five minutes is refused with
        `ERR_MACHINE_COOLDOWN_ACTIVE`".

        Design: Difficulty/resource_temporal_overlap/machine_session_cooldown_halfopen_window_boundary
        """
        world, visit = self._machine_idle_since_nine_ten(api)
        h.set_clock(api, "2026-08-05T09:14:59Z")

        response = api.post_machine_event(
            world.machine_id,
            f.machine_event_payload("SESSION_OPEN", visit["id"]),
            world.center_headers,
        )
        validate_error(response, ApiErrorId.ERR_MACHINE_COOLDOWN_ACTIVE.value)

        machine = h.read_machine(api, world.machine_id, world.center_headers)
        assert_machine_state(machine, "IDLE")
        assert machine["session_started_at"] is None
        assert_stamped_at(machine["last_session_closed_at"], "2026-08-05T09:10:00Z")
        assert machine["jam_hold_count"] == 0

    def test_session_open_at_exactly_five_minutes_is_accepted(self, api):
        """At 09:15:00 the window has elapsed and counting resumes.

        PRD: "while an attempt at exactly five minutes after closing is accepted. The
        logical clock resolves to the second for this comparison."

        Design: Difficulty/resource_temporal_overlap/machine_session_cooldown_halfopen_window_boundary
        """
        world, visit = self._machine_idle_since_nine_ten(api)
        h.set_clock(api, "2026-08-05T09:14:59Z")
        validate_error(
            api.post_machine_event(
                world.machine_id,
                f.machine_event_payload("SESSION_OPEN", visit["id"]),
                world.center_headers,
            ),
            ApiErrorId.ERR_MACHINE_COOLDOWN_ACTIVE.value,
        )

        h.set_clock(api, "2026-08-05T09:15:00Z")
        reopened = validate_success(
            api.post_machine_event(
                world.machine_id,
                f.machine_event_payload("SESSION_OPEN", visit["id"]),
                world.center_headers,
            )
        )

        assert_machine_state(reopened, "COUNTING", open_session_count=1)
        assert_stamped_at(reopened["session_started_at"], "2026-08-05T09:15:00Z")

        assert h.read_visit(api, visit["id"], world.center_headers)["count_status"] == "OPEN"
