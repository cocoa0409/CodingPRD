"""Sweep-driven posture gating and EMR forecasting: the overdue-control
posture cascade, provisional vs final valuation bases, snapshot immutability,
and OCC on forecast creation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_control,
    assert_emr_forecast,
    assess_hazard,
    create_active_program,
    create_contractor_record,
    create_emr_forecast_payload,
    create_hazard_record,
    get_program,
    make_safety_manager_headers,
    set_clock,
    setup_emr_claims_scenario,
    setup_roster,
    submit_contractor_record,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["ehs_admin_headers"]


class TestSweepPostureCascade:
    def test_sweep_posture_cascade(self, api):
        """PRD §3.7: "Every `PLANNED` control whose `due_date` has passed moves
        to `OVERDUE`, and its hazard's and program's `overdue_control_count`
        are recomputed."
        PRD §3.7: "The posture is `RESTRICTED` when the program shows at least
        three overdue controls or at least one SLA-breached hazard."
        PRD §3.6: "when a SafetyProgram is `ACTIVE` and its posture stands at
        `RESTRICTED`, an `APPROVE` decision is blocked with
        `ERR_PROGRAM_RESTRICTED` (the posture gate is evaluated before the
        score check)."

        Design: Difficulty/transitive_cascade/sweep_posture_cascade
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        for location, description in (("L1", "Hazard one"), ("L2", "Hazard two"),
                                      ("L3", "Hazard three")):
            hazard = create_hazard_record(program["id"], manager["id"],
                                          identified_by=ann["id"],
                                          location=location,
                                          description=description)
            # MEDIUM (3x2): response SLA due 2026-07-01, unbreached at 06-15.
            hazard = assess_hazard(hazard["id"], manager["id"], severity=3,
                                   probability=2)
            add_control(hazard["id"], ann["id"], manager["id"],
                        description=f"Fix {location}",
                        due_date="2026-06-10T00:00:00Z")
        contractor = create_contractor_record()
        submitted = submit_contractor_record(contractor["id"])
        assert submitted["computed_decision"] == "APPROVE"

        set_clock("2026-06-15T00:00:00Z")
        sweep = validate_success(api.sweep_program(program["id"], {}, ADMIN))
        assert sweep["overdue_controls"] == 3, \
            "all three PLANNED controls are past due"
        assert sweep["posture"] == "RESTRICTED", \
            "three overdue controls reach the RESTRICTED threshold"

        program = get_program(program["id"])
        assert program["overdue_control_count"] == 3, \
            "the program aggregate recomputes from the child flips"
        assert program["posture"] == "RESTRICTED"
        assert program["sla_breach_count"] == 0, \
            "no SLA breach: the MEDIUM response clocks run to 2026-07-01"

        # The RESTRICTED posture gates contractor approval.
        resp = api.decide_contractor(contractor["id"], {"decision": "APPROVE"},
                                     make_safety_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_RESTRICTED)


class TestEmrDualBasis:
    def test_emr_provisional_vs_final_divergence(self, api):
        """PRD §3.9: "The two bases draw from different claim sets: the
        provisional basis includes claims in `REPORTED`, `ACCEPTED`, or
        `CLOSED` — `DENIED` claims never count — while the final basis admits
        only `ACCEPTED` or `CLOSED` claims."
        PRD §3.9: "Because the provisional basis counts `REPORTED` claims at
        their current incurred and annualizes payroll while the final basis
        does neither, identical claim data can legitimately yield two
        different rates — the forecast keeps both so mid-program estimates and
        unit-statistical valuations are never confused."
        PRD §3.9: "The `payroll_factor` is exactly 1.0 when `as_of` falls
        after December 31 of the program year"

        Design: Difficulty/dual_variant_calc/emr_provisional_vs_final_divergence
        """
        scenario = setup_emr_claims_scenario()
        program = scenario["program"]
        forecast = validate_success(api.create_emr_forecast(
            create_emr_forecast_payload(program["id"],
                                        scenario["program_version"],
                                        as_of="2027-01-15T00:00:00Z"),
            ADMIN), expected_status=201)
        assert_emr_forecast(forecast)

        # as_of is after the 2026 program year: payroll is not annualized.
        assert forecast["payroll_factor"] == pytest.approx(1.0, abs=1e-9)
        # E = 440000 + 540000 + 320000 on recorded payroll.
        assert forecast["expected_losses_final_cents"] == 1_300_000
        # (13000 - 20000) / 180000 clamps to the 0.05 floor.
        assert forecast["weighting_w"] == pytest.approx(0.05, abs=1e-9)
        assert forecast["ballast_final_cents"] == 130_000
        # Final basis (ACCEPTED only): min(2000000, split) + min(240000, split).
        assert forecast["actual_primary_final_cents"] == 1_740_000
        assert forecast["actual_excess_final_cents"] == 500_000
        # Provisional basis adds the REPORTED $50000 indemnity claim.
        assert forecast["actual_primary_provisional_cents"] == 3_240_000
        assert forecast["actual_excess_provisional_cents"] == 4_000_000
        assert forecast["emr_final"] == pytest.approx(1.80, abs=1e-9)
        assert forecast["emr_provisional"] == pytest.approx(2.97, abs=1e-9)
        assert forecast["emr_provisional"] != forecast["emr_final"], \
            "the REPORTED claim moves only the provisional basis"


class TestEmrSnapshotImmutability:
    def test_emr_forecast_snapshot_immutability(self, api):
        """PRD §2.4: "An IncentiveEvent is a point-ledger entry and an
        EMRForecast is an immutable valuation snapshot; both carry only `id`
        and `created_at`. Neither `updated_at` nor `version` exists on these
        two resources, and no endpoint modifies them after creation."
        PRD §3.9: "The ratio, rounded half-up to two decimal places, is
        `emr_provisional` on the provisional basis and `emr_final` on the
        final basis."

        Design: Corner/entities/emr_forecast_snapshot_immutability
        """
        set_clock("2027-01-15T00:00:00Z")
        program = create_active_program()
        forecast = validate_success(api.create_emr_forecast(
            create_emr_forecast_payload(program["id"], program["version"]),
            ADMIN), expected_status=201)
        assert_emr_forecast(forecast)
        assert "version" not in forecast
        assert "updated_at" not in forecast

        # No claims; as_of defaults to the logical now, after the 2026 year
        # end, so both bases price identically: (0.95*165000 + 30000) / 330000.
        assert forecast["emr_final"] == pytest.approx(0.57, abs=1e-9)
        assert forecast["emr_provisional"] == pytest.approx(0.57, abs=1e-9)


class TestEmrForecastOcc:
    def test_occ_stale_emr_forecast_returns_412(self, api):
        """PRD §2.8: "A request to create an EMR forecast against a program
        must likewise carry `expected_program_version`; a mismatch with the
        program's current `version` is rejected with the same
        `ERR_STALE_VERSION` (HTTP 412). Forecast creation otherwise always
        legitimately succeeds against the latest program state — each forecast
        is an immutable snapshot — so the stale-version rejection is the only
        concurrency signal, and a successful forecast creation increments the
        program's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_emr_forecast_returns_412
        """
        set_clock("2027-01-15T00:00:00Z")
        program = create_active_program()
        observed_version = program["version"]

        first = validate_success(api.create_emr_forecast(
            create_emr_forecast_payload(program["id"], observed_version),
            ADMIN), expected_status=201)
        assert first["program_id"] == program["id"]
        assert get_program(program["id"])["version"] == observed_version + 1, \
            "a successful forecast creation increments the program version"

        resp = api.create_emr_forecast(
            create_emr_forecast_payload(program["id"], observed_version),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        _rows, meta = validate_paginated(api.list_emr_forecasts(
            ADMIN, params={"program_id": program["id"]}))
        assert meta["total_count"] == 1, \
            "the stale create persisted no second snapshot"
