"""Production waves: windows, lifecycle, utilization posture, and the tiered
release surcharge with its rush multiplier."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    commit_wave,
    create_active_program,
    create_approved_prototype,
    create_committed_wave,
    create_frozen_kit,
    create_reservation,
    create_wave,
    make_config_coordinator_headers,
    make_platform_admin_headers,
    make_production_planner_headers,
    make_program_manager_headers,
    release_kit,
    set_clock,
    validate_error,
    validate_success,
)

PM = make_program_manager_headers("pm-suite-3")
CC = make_config_coordinator_headers("cc-suite-3")
PP = make_production_planner_headers("pp-suite-3")
PA = make_platform_admin_headers("pa-suite-3")

# BOM for the standard "WALL-BAY" prototype used across wave scenarios.
WALL_BAY_BOM = [
    {"part_number": "PN-400", "quantity": 2, "list_unit_cost_cents": 1000},
]


def _active_program_with_prototype(name, budget=2_000_000, contingency=100_000):
    program = create_active_program(name, budget, contingency)
    prototype = create_approved_prototype(
        program["id"], fixture_code="WALL-BAY", bom_lines=WALL_BAY_BOM)
    return program, prototype


class TestWaveValidation:

    def test_wave_end_before_start_rejected(self):
        """PRD §3.4: "The end date must be strictly after the start date — a
        non-forward window fails with `ERR_INVALID_WINDOW` — and the capacity
        must be at least 1."

        Design: Corner/validations/wave_end_before_start_rejected
        """
        program = create_active_program("P-VAL6", 1_000_000, 100_000)
        resp = api_client.create_production_wave(
            {"program_id": program["id"], "wave_label": "WAVE-BAD",
             "start_date": "2026-09-10", "end_date": "2026-09-10",
             "capacity_units": 100},
            PP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_wave_cancel_committed_returns_409(self):
        """PRD §3.4: "Cancellation is deliberately narrow: only a `PLANNED`
        wave may be cancelled to `CANCELLED`, because a committed wave may
        already hold released kits; cancelling from any other state fails with
        `ERR_WAVE_INVALID_STATE`."

        Design: Corner/state_machines/wave_cancel_committed_returns_409
        """
        program = create_active_program("P-SM9", 1_000_000, 100_000)
        wave1 = create_wave(program["id"], "WAVE-S9A", "2026-09-01",
                            "2026-09-10", 100)
        commit_wave(wave1["id"])
        wave2 = create_wave(program["id"], "WAVE-S9B", "2026-09-11",
                            "2026-09-20", 100)
        resp = api_client.cancel_wave(wave1["id"], PP)
        validate_error(resp, ApiErrorId.ERR_WAVE_INVALID_STATE)
        wave1_after = validate_success(api_client.get_production_wave(
            wave1["id"], PM))
        assert wave1_after["status"] == "COMMITTED"
        wave2_after = validate_success(api_client.cancel_wave(wave2["id"], PP))
        assert wave2_after["status"] == "CANCELLED"


class TestLogicalClock:

    def test_clock_endpoint_echoes_new_current_utc(self):
        """PRD §2.8: "A `PlatformAdmin` may advance it through a test-driving
        capability that accepts a `to_iso8601` instant and sets the server's
        current time to that value; the response reports the resulting
        `current_utc`."

        Design: Corner/endpoints/clock_endpoint_default_and_shape
        """
        resp = api_client.set_current_utc(
            {"to_iso8601": "2026-08-15T00:00:00Z"}, PA)
        data = validate_success(resp, expected_status=200)
        assert data["current_utc"] == "2026-08-15T00:00:00Z"

    def test_clock_advance_auto_starts_wave_and_expires_reservation(self):
        """PRD §2.8: "Advancing the logical clock fires two automatic
        transitions. Any production wave in `COMMITTED` status whose
        `start_date` has been reached — the new current time falls on or after
        the wave's start date — moves to `IN_PRODUCTION` without any client
        action on the wave. Any staging reservation still in `HELD` status
        whose `end_ts` has been reached or passed moves to `EXPIRED`."

        Design: Corner/state_machines/clock_advance_auto_starts_wave_and_expires_reservation
        """
        program, prototype = _active_program_with_prototype("P-SM5", 1_000_000)
        kit = create_frozen_kit(
            program["id"], prototype["id"], "STORE-S5",
            [{"part_number": "PN-600", "quantity": 10,
              "unit_cost_cents": 1000}])
        wave = create_committed_wave(program["id"], "WAVE-S5", "2026-08-10",
                                     "2026-08-20", 100)
        release_kit(kit["id"], wave["id"])
        reservation = create_reservation(
            kit["id"], staging_bay_code="BAY-9",
            start_ts="2026-08-05T10:00:00Z", end_ts="2026-08-06T10:00:00Z")
        assert reservation["status"] == "HELD"

        set_clock("2026-08-10T00:00:00Z")

        wave_after = validate_success(api_client.get_production_wave(
            wave["id"], PM))
        assert wave_after["status"] == "IN_PRODUCTION", (
            f"wave with start_date 2026-08-10 must auto-start at the new "
            f"clock; got {wave_after['status']}"
        )
        reservation_after = validate_success(
            api_client.get_staging_reservation(reservation["id"], PM))
        assert reservation_after["status"] == "EXPIRED", (
            f"HELD reservation whose end_ts passed must expire; got "
            f"{reservation_after['status']}"
        )


class TestReleaseCharging:

    def _tiered_rush_setup(self):
        """One capacity-100 wave (start 2026-08-10, COMMITTED) plus three
        frozen kits of 60/20/10 components on a 2,000,000-cent program."""
        program, prototype = _active_program_with_prototype("P-TIER")
        wave = create_committed_wave(program["id"], "WAVE-T", "2026-08-10",
                                     "2026-08-20", 100)
        kits = []
        for i, qty in enumerate((60, 20, 10), start=1):
            kits.append(create_frozen_kit(
                program["id"], prototype["id"], f"STORE-T{i}",
                [{"part_number": "PN-400", "quantity": qty,
                  "unit_cost_cents": 1000}]))
        return program, wave, kits

    def test_wave_release_charge_tiered_rush_amounts(self):
        """PRD §3.4: "Below seventy percent the tier multiplier is 1.0; at
        seventy percent or above but below ninety percent it is 1.15; at ninety
        percent or above it is 1.35. Independently, if the wave is already
        `IN_PRODUCTION` at release time a rush multiplier of 1.25 applies, and
        1.0 otherwise. The charge is then the kit's `total_components`
        multiplied by a base rate of 150 cents per component, multiplied by the
        tier multiplier, multiplied by the rush multiplier, rounded half up to
        a whole cent."

        Design: Difficulty/combinatorial_formula/wave_release_charge_tiered_rush
        """
        program, wave, kits = self._tiered_rush_setup()
        kit1 = release_kit(kits[0]["id"], wave["id"])  # 60% -> tier 1.0
        kit2 = release_kit(kits[1]["id"], wave["id"])  # 80% -> tier 1.15
        set_clock("2026-08-10T00:00:00Z")  # wave -> IN_PRODUCTION
        kit3 = release_kit(kits[2]["id"], wave["id"])  # 90% -> 1.35, rush 1.25

        # 60*150*1.0 = 9000; 20*150*1.15 = 3450; round_half_up(10*150*1.35*1.25)
        # = round_half_up(2531.25) = 2531.
        assert kit1["wave_release_charge_cents"] == 9_000
        assert kit2["wave_release_charge_cents"] == 3_450
        assert kit3["wave_release_charge_cents"] == 2_531
        assert kit1["wave_id"] == wave["id"]
        assert kit3["status"] == "RELEASED"

        wave_after = validate_success(api_client.get_production_wave(
            wave["id"], PM))
        assert wave_after["status"] == "IN_PRODUCTION"
        assert wave_after["committed_units"] == 90
        assert wave_after["utilization_pct"] == pytest.approx(90.0, abs=0.001)
        assert wave_after["utilization_posture"] == "AT_RISK"

    def test_wave_release_charge_debits_budget_and_recomputes_posture(self):
        """PRD §3.4: "On a successful release the charge is debited from the
        program's `remaining_budget_cents`, the kit's `wave_id` is set to the
        wave it joined, the wave's `committed_units` grows by the kit's
        `total_components`, the wave's utilization and posture are recomputed —
        the posture may flip `NORMAL → AT_RISK` as a consequence — and the kit
        moves `FROZEN → RELEASED`."
        PRD §3.4: "When that percentage reaches 90.0 — the boundary is
        inclusive, so exactly 90.0 counts — the `utilization_posture` becomes
        `AT_RISK`; below it the posture is `NORMAL`."

        Design: Difficulty/combinatorial_formula/wave_release_charge_tiered_rush
        """
        program, wave, kits = self._tiered_rush_setup()
        release_kit(kits[0]["id"], wave["id"])
        mid = validate_success(api_client.get_production_wave(wave["id"], PM))
        assert mid["committed_units"] == 60
        assert mid["utilization_pct"] == pytest.approx(60.0, abs=0.001)
        assert mid["utilization_posture"] == "NORMAL"
        assert mid["status"] == "COMMITTED"

        release_kit(kits[1]["id"], wave["id"])
        mid = validate_success(api_client.get_production_wave(wave["id"], PM))
        assert mid["committed_units"] == 80
        assert mid["utilization_pct"] == pytest.approx(80.0, abs=0.001)
        assert mid["utilization_posture"] == "NORMAL"

        set_clock("2026-08-10T00:00:00Z")
        release_kit(kits[2]["id"], wave["id"])
        final_wave = validate_success(api_client.get_production_wave(
            wave["id"], PM))
        assert final_wave["committed_units"] == 90
        assert final_wave["utilization_posture"] == "AT_RISK", \
            "exactly 90.0 must flip the posture to AT_RISK (inclusive)"

        # Budget conservation: kit totals 63600 + 21200 + 10600 = 95400,
        # charges 9000 + 3450 + 2531 = 14981.
        program_after = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert program_after["remaining_budget_cents"] == 1_889_619

    def test_wave_capacity_exact_fit_allowed(self):
        """PRD §3.4: "The wave must have room: `committed_units` plus the
        kit's `total_components` must not exceed `capacity_units`, with a
        release that lands exactly at full capacity allowed; overshoot fails
        with `ERR_WAVE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/wave_capacity_exact_fit_allowed
        """
        program, prototype = _active_program_with_prototype("P-BND1")
        wave = create_committed_wave(program["id"], "WAVE-B1", "2026-09-01",
                                     "2026-09-10", 50)
        kit1 = create_frozen_kit(
            program["id"], prototype["id"], "STORE-B1",
            [{"part_number": "PN-400", "quantity": 50,
              "unit_cost_cents": 1000}])
        create_frozen_kit(
            program["id"], prototype["id"], "STORE-B2",
            [{"part_number": "PN-400", "quantity": 1,
              "unit_cost_cents": 1000}])

        released = release_kit(kit1["id"], wave["id"])  # 50 == 50: allowed
        assert released["status"] == "RELEASED"
        wave_after = validate_success(api_client.get_production_wave(
            wave["id"], PM))
        assert wave_after["committed_units"] == 50
        assert wave_after["utilization_pct"] == pytest.approx(100.0, abs=0.001)
        assert wave_after["utilization_posture"] == "AT_RISK"

    def test_wave_capacity_overshoot_rejected(self):
        """PRD §3.4: "The wave must have room: `committed_units` plus the
        kit's `total_components` must not exceed `capacity_units`, with a
        release that lands exactly at full capacity allowed; overshoot fails
        with `ERR_WAVE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/wave_capacity_exact_fit_allowed
        """
        program, prototype = _active_program_with_prototype("P-BND1X")
        wave = create_committed_wave(program["id"], "WAVE-B1X", "2026-09-01",
                                     "2026-09-10", 50)
        kit1 = create_frozen_kit(
            program["id"], prototype["id"], "STORE-B1X",
            [{"part_number": "PN-400", "quantity": 50,
              "unit_cost_cents": 1000}])
        kit2 = create_frozen_kit(
            program["id"], prototype["id"], "STORE-B2X",
            [{"part_number": "PN-400", "quantity": 1,
              "unit_cost_cents": 1000}])
        release_kit(kit1["id"], wave["id"])

        resp = api_client.release_kit(kit2["id"], {"wave_id": wave["id"]}, CC)
        validate_error(resp, ApiErrorId.ERR_WAVE_CAPACITY_EXCEEDED)
        kit2_after = validate_success(api_client.get_store_kit_config(
            kit2["id"], PM))
        assert kit2_after["status"] == "FROZEN"
        wave_after = validate_success(api_client.get_production_wave(
            wave["id"], PM))
        assert wave_after["committed_units"] == 50


class TestUtilizationAndBudgetReads:

    def test_utilization_below_threshold_stays_normal(self):
        """PRD §3.4: "When that percentage reaches 90.0 — the boundary is
        inclusive, so exactly 90.0 counts — the `utilization_posture` becomes
        `AT_RISK`; below it the posture is `NORMAL`."
        PRD §3.4: "`utilization_pct` divides `committed_units` by
        `capacity_units`, expresses the result as a percentage, and rounds half
        up to one decimal place."

        Design: Corner/calculations/utilization_below_threshold_stays_normal
        """
        program, prototype = _active_program_with_prototype("P-CALC1")
        wave = create_committed_wave(program["id"], "WAVE-C1", "2026-09-01",
                                     "2026-09-10", 100)
        kit = create_frozen_kit(
            program["id"], prototype["id"], "STORE-C1",
            [{"part_number": "PN-400", "quantity": 89,
              "unit_cost_cents": 1000}])
        release_kit(kit["id"], wave["id"])
        wave_after = validate_success(api_client.get_production_wave(
            wave["id"], PM))
        assert wave_after["committed_units"] == 89
        assert wave_after["utilization_pct"] == pytest.approx(89.0, abs=0.001)
        assert wave_after["utilization_posture"] == "NORMAL"

    def test_release_with_cross_program_wave_returns_404(self):
        """PRD §3.4: "The request names a `wave_id`, which must exist and must
        belong to the same program as the kit — either failure reports
        `ERR_WAVE_NOT_FOUND`."
        PRD §2.7: "A wave reference that exists but belongs to a different
        program than the releasing kit is reported as `ERR_WAVE_NOT_FOUND`, not
        as a permission or state failure."

        Design: Corner/validations/release_with_cross_program_wave_returns_404
        """
        prog1, proto1 = _active_program_with_prototype("P-VAL4A", 1_000_000)
        kit = create_frozen_kit(
            prog1["id"], proto1["id"], "STORE-V4",
            [{"part_number": "PN-600", "quantity": 5,
              "unit_cost_cents": 1000}])
        prog2 = create_active_program("P-VAL4B", 1_000_000, 100_000)
        wave2 = create_committed_wave(prog2["id"], "WAVE-V4", "2026-09-01",
                                      "2026-09-10", 100)
        resp = api_client.release_kit(kit["id"], {"wave_id": wave2["id"]}, CC)
        validate_error(resp, ApiErrorId.ERR_WAVE_NOT_FOUND)
        kit_after = validate_success(api_client.get_store_kit_config(
            kit["id"], PM))
        assert kit_after["status"] == "FROZEN"

    def test_derived_budget_reconciles_across_freeze_release(self):
        """PRD §2.9: "`remaining_budget_cents` starts equal to
        `budget_total_cents` at creation and thereafter equals the total budget
        minus the `kit_total_cost_cents` of every kit in `FROZEN`, `RELEASED`,
        or `FULFILLED` status, minus the `wave_release_charge_cents` of every
        released kit; kits still in `DRAFT` and kits that were `CANCELLED`
        contribute nothing to the deduction."

        Design: Corner/complexity_layers/derived_budget_reconciles_across_freeze_release
        """
        program, prototype = _active_program_with_prototype("P-DER1")
        wave = create_committed_wave(program["id"], "WAVE-D1", "2026-09-01",
                                     "2026-09-10", 100)
        kit = create_frozen_kit(
            program["id"], prototype["id"], "STORE-D1",
            [{"part_number": "PN-400", "quantity": 60,
              "unit_cost_cents": 1000}])
        released = release_kit(kit["id"], wave["id"])
        # kit total: round_half_up(60*1000*1.06) = 63600;
        # charge: 60% utilization after -> tier 1.0, COMMITTED -> rush 1.0
        # -> 60*150 = 9000.
        assert released["kit_total_cost_cents"] == 63_600
        assert released["wave_release_charge_cents"] == 9_000
        program_after = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert program_after["remaining_budget_cents"] == \
            2_000_000 - 63_600 - 9_000
