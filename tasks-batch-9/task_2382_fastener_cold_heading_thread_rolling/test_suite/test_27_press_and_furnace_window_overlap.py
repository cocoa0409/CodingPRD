"""Two bookings competing for one physical resource over time.

The plant contends for two schedulable resources with deliberately different
interval arithmetic. A die set's press window runs from an inclusive start to an
exclusive end, so one lot may begin at the exact instant the previous lot's
window closes. A furnace window, by contrast, counts both endpoints as touching
and is additionally padded by the furnace's cooldown buffer, so a run booked at
the exact instant the cooldown expires still collides. These tests probe the
abutting instant on both sides of each boundary, and check that a refused
booking leaves the contended resource and the material ledgers untouched.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_heat_treat_run_payload, create_production_lot_payload
from test_helpers.test_users import TEST_USERS

ENGINEER = TEST_USERS["engineer_headers"]
HEAT_TREAT = TEST_USERS["heat_treat_headers"]


# ---------------------------------------------------------------------------
# Setup helpers, built only from PRD-declared endpoints
# ---------------------------------------------------------------------------
def _furnace_env():
    """Two lots in ``SECONDARY_DONE`` with 470 available pieces, sharing one furnace.

    The furnace is registered with an explicit 30-minute cooldown and a 400.0 kg
    charge ceiling; both lots hold 470 pieces of a 20.0 g blank, so each charge
    weighs 9.400 kg and capacity never enters the picture.
    """
    env = fixtures.setup_master_data(
        clock="2026-09-01T06:00:00Z",
        unplated=True,
        spec_overrides={
            "part_number": "NP-M8-088",
            "blank_mass_g": 20.0,
            "required_secondary_ops": ["THREAD_ROLL"],
            "thread_timing": "BEFORE_HEAT_TREAT",
        },
        wire_overrides={"gross_mass_kg": 500.0},
        tool_overrides={"tool_code": "DIE-4S-001", "rated_life_pieces": 120000},
        furnace_overrides={
            "furnace_code": "FCE-1",
            "max_charge_mass_kg": 400.0,
            "cooldown_minutes": 30,
        },
        press_code="PRESS-3",
    )
    lots = []
    windows = [
        ("2026-09-01T06:00:00Z", "2026-09-01T08:00:00Z"),
        ("2026-09-01T09:00:00Z", "2026-09-01T11:00:00Z"),
    ]
    for index, (start, end) in enumerate(windows):
        lot = fixtures.open_production_lot(
            env["spec"]["id"],
            env["wire"]["id"],
            env["tool"]["id"],
            press_code=env["press_code"],
            lot_code=f"L-269{index}",
            planned_pieces=500,
            press_window_start_at=start,
            press_window_end_at=end,
        )
        fixtures.report_heading(lot["id"], 480, 20)
        fixtures.run_secondary_op(
            lot["id"], op_type="THREAD_ROLL", sequence_no=1, pieces_out=470
        )
        lots.append(fixtures.read_lot(lot["id"]))
    env["lot_a"], env["lot_b"] = lots
    return env


def _book_run(production_lot_id, furnace_id, window_start_at, window_end_at):
    """Book one furnace window for one lot, returning the raw response."""
    return api_client.create_heat_treat_run(
        create_heat_treat_run_payload(
            production_lot_id,
            furnace_id,
            window_start_at=window_start_at,
            window_end_at=window_end_at,
            austenitize_temp_c=870.0,
            quench_medium="OIL",
            temper_temp_c=420.0,
            temper_time_min=60,
            carbon_potential_pct=0.42,
        ),
        HEAT_TREAT,
    )


def _press_env():
    """Master data plus lot ``L-2700`` occupying the press window 06:00 - 10:00.

    Planned output of 5000 pieces of a 20.0 g blank at the default 0.05 scrap
    allowance reserves 5000 * 20.0 * 1.05 / 1000 = 105.000 kg of the 500.0 kg coil.
    """
    env = fixtures.setup_master_data(
        clock="2026-09-01T06:00:00Z",
        spec_overrides={
            "part_number": "BX-M8-109",
            "blank_mass_g": 20.0,
            "scrap_allowance_pct": 0.05,
            "allowed_steel_grades": ["SAE_10B21"],
        },
        wire_overrides={"gross_mass_kg": 500.0},
        tool_overrides={"tool_code": "DIE-4S-001", "rated_life_pieces": 120000},
        press_code="PRESS-3",
    )
    env["lot_a"] = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-2700",
        planned_pieces=5000,
        press_window_start_at="2026-09-01T06:00:00Z",
        press_window_end_at="2026-09-01T10:00:00Z",
    )
    return env


def _open_lot(env, lot_code, start, end):
    """Attempt to open a second lot on the same die set, returning the raw response."""
    payload = create_production_lot_payload(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        fixtures.wire_lot_version(env["wire"]["id"]),
        lot_code=lot_code,
        press_code=env["press_code"],
        press_window_start_at=start,
        press_window_end_at=end,
        planned_pieces=5000,
    )
    return api_client.create_production_lot(payload, ENGINEER)


def _lots_on_tool(tool_id):
    """``total_count`` of production lots booked on one die set."""
    items, meta = validate_paginated(
        api_client.list_production_lots(ENGINEER, params={"heading_tool_id": tool_id})
    )
    return items, meta["total_count"]


def _runs_on_furnace(furnace_id):
    """``total_count`` of heat treatment runs booked on one furnace."""
    items, meta = validate_paginated(
        api_client.list_heat_treat_runs(HEAT_TREAT, params={"furnace_id": furnace_id})
    )
    return items, meta["total_count"]


# ---------------------------------------------------------------------------
# The furnace: closed bounds plus a cooldown buffer
# ---------------------------------------------------------------------------
class TestFurnaceWindowCooldownBuffer:
    """Furnace contention: both endpoints touch, and the existing window is padded."""

    def test_booking_starting_exactly_at_the_cooldown_expiry_is_refused(self):
        """A run booked at 20:30 collides with an 18:00-20:00 run on a 30-minute-cooldown furnace.

        PRD: "Booking also respects the cooldown: the requested window must not collide with any non-terminal run already booked on the same furnace, where each existing window is treated as extended by that furnace's `cooldown_minutes` and both endpoints count as touching."

        PRD: "Concretely, a conflict exists when the requested start is at or before the other run's end plus the cooldown *and* the requested end is at or after the other run's start; such a booking is refused with `ERR_FURNACE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/furnace_window_conflict_uses_inclusive_bounds_plus_cooldown_buffer
        """
        env = _furnace_env()
        furnace_id = env["furnace"]["id"]
        run_a = validate_success(
            _book_run(
                env["lot_a"]["id"],
                furnace_id,
                "2026-09-01T18:00:00Z",
                "2026-09-01T20:00:00Z",
            ),
            201,
        )

        resp = _book_run(
            env["lot_b"]["id"],
            furnace_id,
            "2026-09-01T20:30:00Z",
            "2026-09-01T22:00:00Z",
        )
        validate_error(resp, ApiErrorId.ERR_FURNACE_WINDOW_CONFLICT.value)

        run_a_after = fixtures.read_heat_treat_run(run_a["id"])
        assert run_a_after["status"] == "PLANNED", (
            f"Expected PLANNED, got {run_a_after['status']} for the run the rejected "
            "booking collided with"
        )
        assert run_a_after["version"] == run_a["version"], (
            f"Expected version {run_a['version']}, got {run_a_after['version']} on the "
            "existing run after a refused booking"
        )
        _, total = _runs_on_furnace(furnace_id)
        assert total == 1, f"Expected 1 run booked on the furnace, got {total}"

    def test_booking_one_minute_after_the_cooldown_expiry_is_accepted(self):
        """A run booked at 20:31 clears the 20:00 end plus 30 minutes of cooldown.

        PRD: "Concretely, a conflict exists when the requested start is at or before the other run's end plus the cooldown *and* the requested end is at or after the other run's start; such a booking is refused with `ERR_FURNACE_WINDOW_CONFLICT`."

        PRD: "The run's `charge_mass_kg` is derived, not supplied: it is the lot's `available_count` multiplied by the part's `blank_mass_g`, divided by 1000, rounded half up to three decimal places, and it may not exceed the furnace's `max_charge_mass_kg` — the comparison is inclusive, so a charge exactly at capacity is accepted, and anything heavier is refused with `ERR_FURNACE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/furnace_window_conflict_uses_inclusive_bounds_plus_cooldown_buffer
        """
        env = _furnace_env()
        furnace_id = env["furnace"]["id"]
        run_a = validate_success(
            _book_run(
                env["lot_a"]["id"],
                furnace_id,
                "2026-09-01T18:00:00Z",
                "2026-09-01T20:00:00Z",
            ),
            201,
        )

        run_b = validate_success(
            _book_run(
                env["lot_b"]["id"],
                furnace_id,
                "2026-09-01T20:31:00Z",
                "2026-09-01T22:00:00Z",
            ),
            201,
        )
        assert run_b["status"] == "PLANNED", (
            f"Expected PLANNED, got {run_b['status']} on a freshly booked run"
        )
        assert run_b["result"] == "PENDING", (
            f"Expected PENDING, got {run_b['result']} on a freshly booked run"
        )
        assert run_b["charge_mass_kg"] == pytest.approx(9.400, abs=0.001), (
            f"Expected 9.400 kg for 470 pieces of a 20.0 g blank, got "
            f"{run_b['charge_mass_kg']}"
        )

        furnace_after = fixtures.read_furnace(furnace_id)
        assert furnace_after["status"] == "IDLE", (
            f"Expected IDLE, got {furnace_after['status']} — booking does not occupy "
            "the furnace"
        )
        run_a_after = fixtures.read_heat_treat_run(run_a["id"])
        assert run_a_after["status"] == "PLANNED", (
            f"Expected PLANNED, got {run_a_after['status']} on the earlier run"
        )
        _, total = _runs_on_furnace(furnace_id)
        assert total == 2, f"Expected 2 runs booked on the furnace, got {total}"

    def test_booking_ending_exactly_at_the_other_windows_start_is_refused(self):
        """A run ending at exactly 18:00 touches the 18:00 start of the run already booked.

        PRD: "Booking also respects the cooldown: the requested window must not collide with any non-terminal run already booked on the same furnace, where each existing window is treated as extended by that furnace's `cooldown_minutes` and both endpoints count as touching."

        PRD: "Concretely, a conflict exists when the requested start is at or before the other run's end plus the cooldown *and* the requested end is at or after the other run's start; such a booking is refused with `ERR_FURNACE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/furnace_window_conflict_uses_inclusive_bounds_plus_cooldown_buffer
        """
        env = _furnace_env()
        furnace_id = env["furnace"]["id"]
        run_a = validate_success(
            _book_run(
                env["lot_a"]["id"],
                furnace_id,
                "2026-09-01T18:00:00Z",
                "2026-09-01T20:00:00Z",
            ),
            201,
        )

        resp = _book_run(
            env["lot_b"]["id"],
            furnace_id,
            "2026-09-01T16:00:00Z",
            "2026-09-01T18:00:00Z",
        )
        validate_error(resp, ApiErrorId.ERR_FURNACE_WINDOW_CONFLICT.value)

        run_a_after = fixtures.read_heat_treat_run(run_a["id"])
        assert run_a_after["version"] == run_a["version"], (
            f"Expected version {run_a['version']}, got {run_a_after['version']} — a "
            "refused booking must not touch the run it collided with"
        )
        _, total = _runs_on_furnace(furnace_id)
        assert total == 1, f"Expected 1 run booked on the furnace, got {total}"

    def test_booking_ending_one_minute_before_the_other_windows_start_is_accepted(self):
        """A run ending at 17:59 stops short of the 18:00 start, so no endpoint touches.

        PRD: "Concretely, a conflict exists when the requested start is at or before the other run's end plus the cooldown *and* the requested end is at or after the other run's start; such a booking is refused with `ERR_FURNACE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/furnace_window_conflict_uses_inclusive_bounds_plus_cooldown_buffer
        """
        env = _furnace_env()
        furnace_id = env["furnace"]["id"]
        validate_success(
            _book_run(
                env["lot_a"]["id"],
                furnace_id,
                "2026-09-01T18:00:00Z",
                "2026-09-01T20:00:00Z",
            ),
            201,
        )

        run_b = validate_success(
            _book_run(
                env["lot_b"]["id"],
                furnace_id,
                "2026-09-01T16:00:00Z",
                "2026-09-01T17:59:00Z",
            ),
            201,
        )
        assert run_b["status"] == "PLANNED", (
            f"Expected PLANNED, got {run_b['status']} on a freshly booked run"
        )
        assert run_b["charge_mass_kg"] == pytest.approx(9.400, abs=0.001), (
            f"Expected 9.400 kg for 470 pieces of a 20.0 g blank, got "
            f"{run_b['charge_mass_kg']}"
        )
        _, total = _runs_on_furnace(furnace_id)
        assert total == 2, f"Expected 2 runs booked on the furnace, got {total}"


# ---------------------------------------------------------------------------
# The die set: half-open press windows, no buffer
# ---------------------------------------------------------------------------
class TestPressWindowHalfOpenIntervals:
    """Die-set contention: the end instant of one lot is a legal start for the next."""

    def test_lot_starting_exactly_when_the_prior_window_ends_is_accepted(self):
        """A lot opened for 10:00-14:00 abuts the 06:00-10:00 lot on the same die set and is admitted.

        PRD: "The requested press window must not overlap the window of any other non-aborted production lot already booked on the same die set; windows are half-open, running from the inclusive start to the exclusive end, so a window beginning at the exact instant another one ends is accepted, while any genuine overlap is refused with `ERR_TOOL_WINDOW_CONFLICT`."

        PRD: "On success, that amount is subtracted from `available_mass_kg`, added to `reserved_mass_kg`, and stored on the lot as `wire_reserved_kg`; the wire lot's `version` increments by 1."

        Design: Difficulty/resource_temporal_overlap/press_window_conflict_treats_tool_intervals_as_half_open
        """
        env = _press_env()
        lot_b = validate_success(
            _open_lot(env, "L-2701", "2026-09-01T10:00:00Z", "2026-09-01T14:00:00Z"),
            201,
        )
        assert lot_b["wire_reserved_kg"] == pytest.approx(105.000, abs=0.001), (
            f"Expected 105.000 kg reserved for 5000 pieces of a 20.0 g blank at a 0.05 "
            f"scrap allowance, got {lot_b['wire_reserved_kg']}"
        )
        assert lot_b["process_state"] == "SETUP", (
            f"Expected SETUP, got {lot_b['process_state']} on a newly opened lot"
        )

        wire_after = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire_after["reserved_mass_kg"] == pytest.approx(210.000, abs=0.001), (
            f"Expected 210.000 kg reserved by the two lots, got "
            f"{wire_after['reserved_mass_kg']}"
        )
        assert wire_after["available_mass_kg"] == pytest.approx(290.000, abs=0.001), (
            f"Expected 290.000 kg still available, got {wire_after['available_mass_kg']}"
        )
        _, total = _lots_on_tool(env["tool"]["id"])
        assert total == 2, f"Expected 2 lots booked on the die set, got {total}"

    def test_lot_starting_one_minute_before_the_prior_window_ends_is_refused(self):
        """A lot opened for 09:59-12:00 genuinely overlaps the 06:00-10:00 window and is refused.

        PRD: "The requested press window must not overlap the window of any other non-aborted production lot already booked on the same die set; windows are half-open, running from the inclusive start to the exclusive end, so a window beginning at the exact instant another one ends is accepted, while any genuine overlap is refused with `ERR_TOOL_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/press_window_conflict_treats_tool_intervals_as_half_open
        """
        env = _press_env()
        wire_before = fixtures.read_wire_lot(env["wire"]["id"])

        resp = _open_lot(env, "L-2702", "2026-09-01T09:59:00Z", "2026-09-01T12:00:00Z")
        validate_error(resp, ApiErrorId.ERR_TOOL_WINDOW_CONFLICT.value)

        wire_after = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire_after["reserved_mass_kg"] == pytest.approx(105.000, abs=0.001), (
            f"Expected 105.000 kg reserved by the one accepted lot, got "
            f"{wire_after['reserved_mass_kg']} — the refused lot must reserve nothing"
        )
        assert wire_after["available_mass_kg"] == pytest.approx(395.000, abs=0.001), (
            f"Expected 395.000 kg still available, got {wire_after['available_mass_kg']}"
        )
        assert wire_after["version"] == wire_before["version"], (
            f"Expected version {wire_before['version']}, got {wire_after['version']} — "
            "a refused lot opening must not mutate the wire lot"
        )
        _, total = _lots_on_tool(env["tool"]["id"])
        assert total == 1, f"Expected 1 lot booked on the die set, got {total}"

    def test_lot_ending_exactly_when_the_prior_window_starts_is_accepted(self):
        """A lot opened for 02:00-06:00 closes at the exclusive instant the 06:00 window opens.

        PRD: "The requested press window must not overlap the window of any other non-aborted production lot already booked on the same die set; windows are half-open, running from the inclusive start to the exclusive end, so a window beginning at the exact instant another one ends is accepted, while any genuine overlap is refused with `ERR_TOOL_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/press_window_conflict_treats_tool_intervals_as_half_open
        """
        env = _press_env()
        lot_b = validate_success(
            _open_lot(env, "L-2699", "2026-09-01T02:00:00Z", "2026-09-01T06:00:00Z"),
            201,
        )
        assert lot_b["wire_reserved_kg"] == pytest.approx(105.000, abs=0.001), (
            f"Expected 105.000 kg reserved, got {lot_b['wire_reserved_kg']}"
        )

        wire_after = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire_after["reserved_mass_kg"] == pytest.approx(210.000, abs=0.001), (
            f"Expected 210.000 kg reserved by the two abutting lots, got "
            f"{wire_after['reserved_mass_kg']}"
        )
        _, total = _lots_on_tool(env["tool"]["id"])
        assert total == 2, f"Expected 2 lots booked on the die set, got {total}"

    def test_lot_ending_one_minute_after_the_prior_window_starts_is_refused(self):
        """A lot opened for 02:00-06:01 straddles the 06:00 inclusive start and is refused.

        PRD: "The requested press window must not overlap the window of any other non-aborted production lot already booked on the same die set; windows are half-open, running from the inclusive start to the exclusive end, so a window beginning at the exact instant another one ends is accepted, while any genuine overlap is refused with `ERR_TOOL_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/press_window_conflict_treats_tool_intervals_as_half_open
        """
        env = _press_env()
        wire_before = fixtures.read_wire_lot(env["wire"]["id"])

        resp = _open_lot(env, "L-2698", "2026-09-01T02:00:00Z", "2026-09-01T06:01:00Z")
        validate_error(resp, ApiErrorId.ERR_TOOL_WINDOW_CONFLICT.value)

        wire_after = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire_after["reserved_mass_kg"] == pytest.approx(105.000, abs=0.001), (
            f"Expected 105.000 kg reserved by the one accepted lot, got "
            f"{wire_after['reserved_mass_kg']}"
        )
        assert wire_after["version"] == wire_before["version"], (
            f"Expected version {wire_before['version']}, got {wire_after['version']} — "
            "a refused lot opening must not mutate the wire lot"
        )
        _, total = _lots_on_tool(env["tool"]["id"])
        assert total == 1, f"Expected 1 lot booked on the die set, got {total}"
