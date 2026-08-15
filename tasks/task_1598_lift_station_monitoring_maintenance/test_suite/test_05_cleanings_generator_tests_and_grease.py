"""Wet-well cleanings, generator tests, overdue derivation, duration
boundaries, the permit gate, and grease-accumulation analytics."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_operator,
    complete_cleaning_now,
    create_station,
    get_cleaning,
    get_generator_test,
    make_operator_headers,
    reset_clock,
    schedule_cleaning,
    schedule_generator_test,
    setup_completed_cleaning,
    setup_issued_permit,
    setup_running_generator_test,
    setup_station_with_pumps,
    tick,
    validate_error,
    validate_success,
)


class TestOverdueDerivation:
    def test_generator_test_overdue_auto_transition(self, api, utility_admin_headers):
        """PRD §3.7: "Like cleanings, a test still `SCHEDULED` more than 24
        hours past its `scheduled_for` flips to `OVERDUE` on the next tick and
        triggers a station-posture recompute — an overdue (or running, or
        failed) test whose planned time has passed is one of the three drivers
        into `DEGRADED`."
        PRD §2.9: "may invoke a tick capability that re-evaluates all
        time-driven automatic transitions described in §3, returning a
        `transitioned_counts` object summarizing what moved: scheduled cleanings
        and generator tests that have slipped more than 24 hours past their
        planned start become `OVERDUE`, and station postures are recomputed
        against the new "now"."

        Design: Corner/state_machines/generator_test_overdue_auto_transition
        """
        reset_clock()
        station, _ = setup_station_with_pumps(has_backup_generator=True)
        gt = schedule_generator_test(station["id"], scheduled_for="2026-08-01T00:00:00Z")
        reset_clock("2026-08-03T00:00:00Z")
        res = api.tick(utility_admin_headers)
        validate_success(res, 200)
        assert get_generator_test(gt["id"])["status"] == "OVERDUE"

    def test_wet_well_cleaning_overdue_via_tick(self, api, utility_admin_headers):
        """PRD §3.6: "Time pressure is built in: if the logical clock passes
        `scheduled_for` by more than 24 hours while the cleaning is still
        `SCHEDULED`, the system flips it to `OVERDUE` on the next tick and
        auto-fires a `MINOR` alarm with `alarm_code` `CLEANING_OVERDUE`."

        Design: Corner/state_machines/wet_well_cleaning_overdue_via_tick
        """
        reset_clock()
        station = create_station()
        lead = add_operator(full_name="Lead", certifications=["CSE_1"])
        cleaning = schedule_cleaning(
            station["id"], lead["id"], scheduled_for="2026-08-01T00:00:00Z",
        )
        reset_clock("2026-08-03T00:00:00Z")
        res = api.tick(utility_admin_headers)
        validate_success(res, 200)
        assert get_cleaning(cleaning["id"])["status"] == "OVERDUE"


class TestGeneratorDurationBoundary:
    def test_load_bank_29_rejected_then_30_accepted(self, api, operator_headers):
        """PRD §3.7: "Finishing a running test records a pass: the operator
        supplies `duration_minutes`, and the run must have lasted at least 30
        minutes when `test_kind` is `LOAD_BANK`, or at least 15 minutes for the
        other kinds; a shorter duration is rejected with
        `ERR_TEST_DURATION_TOO_SHORT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/generator_test_load_bank_duration_boundary
        """
        reset_clock()
        station, _ = setup_station_with_pumps(has_backup_generator=True)
        test = setup_running_generator_test(station["id"], test_kind="LOAD_BANK")
        res = api.finish_generator_test(test["id"], 29, operator_headers)
        validate_error(res, ApiErrorId.ERR_TEST_DURATION_TOO_SHORT)
        assert get_generator_test(test["id"])["status"] == "RUNNING", (
            "a rejected finish leaves the run in place"
        )
        res = api.finish_generator_test(test["id"], 30, operator_headers)
        passed = validate_success(res, 200)
        assert passed["status"] == "PASSED", "30 minutes meets the LOAD_BANK minimum"
        assert passed["duration_minutes"] == 30

    def test_no_load_14_rejected_then_15_accepted(self, api, operator_headers):
        """PRD §3.7: "Finishing a running test records a pass: the operator
        supplies `duration_minutes`, and the run must have lasted at least 30
        minutes when `test_kind` is `LOAD_BANK`, or at least 15 minutes for the
        other kinds; a shorter duration is rejected with
        `ERR_TEST_DURATION_TOO_SHORT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/generator_test_load_bank_duration_boundary
        """
        reset_clock()
        station, _ = setup_station_with_pumps(has_backup_generator=True)
        test = setup_running_generator_test(station["id"], test_kind="NO_LOAD",
                                            load_percent=0)
        res = api.finish_generator_test(test["id"], 14, operator_headers)
        validate_error(res, ApiErrorId.ERR_TEST_DURATION_TOO_SHORT)
        res = api.finish_generator_test(test["id"], 15, operator_headers)
        passed = validate_success(res, 200)
        assert passed["status"] == "PASSED", "15 minutes meets the non-LOAD_BANK minimum"
        assert passed["duration_minutes"] == 15


class TestCleaningPermitGate:
    def test_cleaning_start_requires_permit_state(self, api, operator_headers):
        """PRD §3.6: "Two preconditions bind: the station must not be `FROZEN`,
        and if `requires_confined_space_entry` is true there must exist a
        confined-space permit for the station in `ISSUED` or `ACTIVE` status —
        without one, the start is rejected with `ERR_PERMIT_REQUIRED` (HTTP
        422)."

        Design: Difficulty/cross_entity_state_dependency/cleaning_start_requires_permit_state
        """
        reset_clock()
        station = create_station()
        lead = add_operator(full_name="Lead", certifications=["CSE_1"])
        cleaning = schedule_cleaning(
            station["id"], lead["id"], scheduled_for="2026-08-01T06:00:00Z",
            grease_depth_inches_pre=5.0, requires_confined_space_entry=True,
        )
        res = api.start_cleaning(cleaning["id"], operator_headers)
        validate_error(res, ApiErrorId.ERR_PERMIT_REQUIRED)
        assert get_cleaning(cleaning["id"])["status"] == "SCHEDULED"

    def test_cleaning_start_succeeds_with_issued_permit(self, api, operator_headers):
        """PRD §3.6: "An `Operator` starts the work, moving `SCHEDULED →
        IN_PROGRESS` or `OVERDUE → IN_PROGRESS`. Two preconditions bind: the
        station must not be `FROZEN`, and if `requires_confined_space_entry` is
        true there must exist a confined-space permit for the station in
        `ISSUED` or `ACTIVE` status — without one, the start is rejected with
        `ERR_PERMIT_REQUIRED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/cleaning_start_requires_permit_state
        """
        reset_clock()
        station, trio, permit = setup_issued_permit()
        assert permit["status"] == "ISSUED"
        cleaning = schedule_cleaning(
            station["id"], trio[0]["id"], scheduled_for="2026-08-01T06:00:00Z",
            grease_depth_inches_pre=5.0, requires_confined_space_entry=True,
        )
        res = api.start_cleaning(cleaning["id"], operator_headers)
        started = validate_success(res, 200)
        assert started["status"] == "IN_PROGRESS"


class TestGreaseDepthValidation:
    def test_grease_depth_post_must_be_less_than_pre(self, api):
        """PRD §3.6: "Completion moves `IN_PROGRESS → COMPLETED` (or `OVERDUE →
        COMPLETED` when work finished without an intervening start), requires
        the request to supply `grease_depth_inches_post`, and demands that the
        post-cleaning depth be strictly less than `grease_depth_inches_pre`; a
        post depth greater than or equal to the pre depth is rejected with
        `ERR_GREASE_DEPTH_INVALID` (HTTP 422)."

        Design: Corner/validations/grease_depth_post_must_be_less_than_pre
        """
        reset_clock()
        station = create_station()
        lead = add_operator(full_name="Lead", certifications=["CSE_1"])
        cleaning = schedule_cleaning(
            station["id"], lead["id"], grease_depth_inches_pre=5.0,
        )
        headers = make_operator_headers(lead["id"])
        res = api.start_cleaning(cleaning["id"], headers)
        validate_success(res, 200)
        res = api.complete_cleaning(cleaning["id"], 5.5, headers)
        validate_error(res, ApiErrorId.ERR_GREASE_DEPTH_INVALID)


class TestGreaseAccumulationRate:
    def test_calendar_day_rate_two_completions(self, api, operations_supervisor_headers):
        """PRD §3.6: "The historical accumulation rate is computed from the
        station's completed cleanings ordered by `completed_at`: with fewer than
        two completed cleanings the rate is undefined; otherwise it is the sum
        of `grease_depth_inches_pre` across all completed cleanings after the
        first (the first serves as the baseline) divided by the calendar days
        between the first and last completed `completed_at`, rounded half-up to
        three decimal places — and undefined when that day-span is zero."
        PRD §3.11: "the current `grease_accumulation_rate_inches_per_day`"

        Design: Difficulty/dual_variant_calc/grease_accumulation_calendar_vs_operating
        """
        reset_clock()
        station = create_station(design_capacity_gpm=400, wet_well_volume_gal=4000)
        lead = add_operator(full_name="Crew Lead", certifications=["CSE_1"])
        setup_completed_cleaning(
            station["id"], lead["id"], scheduled_for="2026-08-01T00:00:00Z",
            clock_at_work="2026-08-01T00:00:00Z", pre=4.0, post=0.5,
        )
        setup_completed_cleaning(
            station["id"], lead["id"], scheduled_for="2026-08-11T00:00:00Z",
            clock_at_work="2026-08-11T00:00:00Z", pre=5.0, post=0.5,
        )
        res = api.get_station_summary(station["id"], operations_supervisor_headers)
        summary = validate_success(res, 200)
        assert summary["grease_accumulation_rate_inches_per_day"] == pytest.approx(0.5), (
            "5.0 inches over 10 calendar days (first cleaning is the baseline)"
        )

    def test_calendar_day_rate_with_different_depths(self, api, operations_supervisor_headers):
        """PRD §3.6: "otherwise it is the sum of `grease_depth_inches_pre`
        across all completed cleanings after the first (the first serves as the
        baseline) divided by the calendar days between the first and last
        completed `completed_at`, rounded half-up to three decimal places — and
        undefined when that day-span is zero."
        PRD §3.11: "the current `grease_accumulation_rate_inches_per_day`"

        Design: Difficulty/dual_variant_calc/grease_accumulation_calendar_vs_operating
        """
        reset_clock()
        station = create_station(design_capacity_gpm=400, wet_well_volume_gal=4000)
        lead = add_operator(full_name="Crew Lead", certifications=["CSE_1"])
        setup_completed_cleaning(
            station["id"], lead["id"], scheduled_for="2026-08-01T00:00:00Z",
            clock_at_work="2026-08-01T00:00:00Z", pre=6.0, post=1.0,
        )
        setup_completed_cleaning(
            station["id"], lead["id"], scheduled_for="2026-08-06T00:00:00Z",
            clock_at_work="2026-08-06T00:00:00Z", pre=3.0, post=0.5,
        )
        res = api.get_station_summary(station["id"], operations_supervisor_headers)
        summary = validate_success(res, 200)
        assert summary["grease_accumulation_rate_inches_per_day"] == pytest.approx(0.6), (
            "3.0 inches over 5 calendar days"
        )
