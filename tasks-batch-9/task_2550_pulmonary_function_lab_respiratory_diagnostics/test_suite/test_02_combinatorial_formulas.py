"""Two figures in this laboratory are the end of an ordered chain of steps.

A calibration's error percentage is the fourth stage of a chain that rounds at
every stage, and a report's deadline is the fifth of five normative steps whose
second step counts the report being created.  In both cases taking a shortcut
through the arithmetic gives a different, wrong answer.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_4dp,
    assert_device_quarantined,
    assert_instant,
)
from test_helpers.test_users import LAB_MANAGER, make_technologist_headers


def _newly_calibrated_spirometer(api):
    """A device promoted out of NEW by a first, exact calibration."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    tech = fx.register_technologist(api)
    tech_headers = make_technologist_headers(tech["id"])
    device = fx.register_device(api, "SPIRO-1", "SPIROMETRY")
    first = fx.append_quality_event(
        api, device["id"], f.calibration_event_payload(2.764), tech_headers
    )
    return tech, tech_headers, device["id"], first


class TestCalibrationErrorChain:
    """The error percentage is taken from the rounded corrected volume."""

    def test_error_percentage_is_derived_from_the_already_rounded_volume(self, api):
        """2.848 L reads 3.03 percent, not the 3.04 the raw product would give.

        PRD 3.2: "Deriving `error_pct` from the unrounded product instead of
        from the rounded `corrected_volume_l` yields a different answer near the
        tolerance boundary and is wrong."

        Design: Difficulty/combinatorial_formula/calibration_btps_three_stage_chained_rounding_order
        """
        _, tech_headers, device_id, exact = _newly_calibrated_spirometer(api)

        on_tolerance = validate_success(
            api.create_quality_event(
                device_id, f.calibration_event_payload(2.847), tech_headers
            ),
            expected_status=201,
        )
        fx.set_clock(api, "2026-08-03T09:00:00Z")
        over_tolerance = validate_success(
            api.create_quality_event(
                device_id, f.calibration_event_payload(2.848), tech_headers
            ),
            expected_status=201,
        )

        assert_4dp(exact["btps_factor"], 1.0854)
        assert_3dp(exact["corrected_volume_l"], 3.000)
        assert_2dp(exact["error_pct"], 0.00)

        assert_4dp(on_tolerance["btps_factor"], 1.0854)
        assert_3dp(on_tolerance["corrected_volume_l"], 3.090)
        assert_2dp(on_tolerance["error_pct"], 3.00)
        assert on_tolerance["outcome"] == "PASS"

        assert_3dp(over_tolerance["corrected_volume_l"], 3.091)
        assert_2dp(over_tolerance["error_pct"], 3.03)
        assert over_tolerance["error_pct"] != 3.04, (
            "3.04 is what the unrounded product would have produced"
        )
        assert over_tolerance["outcome"] == "FAIL"
        assert over_tolerance["failure_reason"] == "CAL_TOLERANCE_EXCEEDED"

    def test_a_failing_calibration_quarantines_without_refreshing_currency(self, api):
        """The failure records its error percentage but not a new pass instant.

        PRD 3.2: "A failing calibration sets `failure_reason` to
        `CAL_TOLERANCE_EXCEEDED`, stores `error_pct` into
        `last_calibration_error_pct` while pointedly **not** advancing
        `last_calibration_at` — only a pass refreshes calibration currency — and
        drives the device to `QUARANTINED`, stamping `quarantined_at` with the
        record's `performed_at`, `quarantine_reason` with `CALIBRATION_FAILED` and
        `quarantine_trigger_staff_id` with the acting technologist."

        Design: Difficulty/combinatorial_formula/calibration_btps_three_stage_chained_rounding_order
        """
        tech, tech_headers, device_id, _ = _newly_calibrated_spirometer(api)
        fx.append_quality_event(
            api, device_id, f.calibration_event_payload(2.847), tech_headers
        )
        fx.set_clock(api, "2026-08-03T09:00:00Z")
        fx.append_quality_event(
            api, device_id, f.calibration_event_payload(2.848), tech_headers
        )

        device = validate_success(api.get_device(device_id, LAB_MANAGER))
        assert_device_quarantined(
            device,
            "CALIBRATION_FAILED",
            trigger_staff_id=tech["id"],
            quarantined_at="2026-08-03T09:00:00Z",
        )
        assert_instant(device["last_calibration_at"], "2026-08-03T08:00:00Z")
        assert_2dp(device["last_calibration_error_pct"], 3.03)


def _two_accepted_studies_and_one_interpreter(api):
    """A routine study and a disability study, both accepted, one seat on duty."""
    lab = fx.build_lab(
        api,
        clock="2026-08-03T10:00:00Z",
        device_codes=("SPIRO-1", "SPIRO-2"),
        interpreters=1,
    )
    routine = fx.build_accepted_session(
        api,
        lab,
        scheduled_start_at="2026-08-03T11:00:00Z",
        scheduled_end_at="2026-08-03T11:30:00Z",
    )
    disability = fx.build_accepted_session(
        api,
        lab,
        device_id=lab.device_ids[1],
        scheduled_start_at="2026-08-03T12:00:00Z",
        scheduled_end_at="2026-08-03T12:30:00Z",
        indication_code="DISABILITY_ASSESSMENT",
        test_context="DISABILITY_EVALUATION",
    )
    return lab, routine, disability


class TestReportDeadlineFiveSteps:
    """The deadline counts the report it is being computed for."""

    def test_the_first_report_counts_itself_into_a_surge_queue_load(self, api):
        """One seat and one new report is a full queue, not an empty one.

        PRD 3.9: "A single on-duty interpreter with `max_concurrent_reports` of
        1 and no other open work yields an open count of 1 against a capacity of
        1, a `queue_load_pct` of 100.00, a `load_tier` of `SURGE` and, for a
        routine study, an `sla_minutes` of 2880. Measuring the load before
        insertion would have produced 0.00, `NORMAL` and 1440 — a different
        deadline for the same request."

        Design: Difficulty/combinatorial_formula/sla_deadline_five_step_self_counting_queue_load
        """
        lab, routine, _ = _two_accepted_studies_and_one_interpreter(api)

        report = fx.assign_report(api, routine["id"], routine["version"])

        assert_instant(report["assigned_at"], "2026-08-03T10:00:00Z")
        assert_2dp(report["queue_load_pct"], 100.00)
        assert report["load_tier"] == "SURGE"
        assert report["sla_minutes"] == 2880
        assert_instant(report["due_at"], "2026-08-05T10:00:00Z")
        assert report["queue_load_pct"] != 0.00
        assert report["load_tier"] != "NORMAL"

    def test_a_load_landing_exactly_on_fifty_percent_keeps_the_normal_tier(self, api):
        """A freed seat halves the load and the disability base is not multiplied.

        PRD 3.9: "the load is tiered with inclusive lower boundaries: a
        `queue_load_pct` at or below 50.00 is `load_tier` `NORMAL` with a
        multiplier of 1.00"

        Design: Difficulty/combinatorial_formula/sla_deadline_five_step_self_counting_queue_load
        """
        lab, routine, disability = _two_accepted_studies_and_one_interpreter(api)

        first = fx.assign_report(api, routine["id"], routine["version"])
        fx.sign_report(api, first["id"], lab.roster.rad1)
        second_seat = fx.register_interpreting_physician(
            api, employee_code="R-002", full_name="Ravi Menon", max_concurrent_reports=1
        )

        report = fx.assign_report(api, disability["id"], disability["version"])

        assert_2dp(report["queue_load_pct"], 50.00)
        assert report["load_tier"] == "NORMAL"
        assert report["sla_minutes"] == 4320
        assert_instant(report["due_at"], "2026-08-06T10:00:00Z")
        assert report["interpreter_staff_id"] == lab.roster.rad1_id, (
            "both interpreters are idle, so the earlier-created one wins the tie"
        )
        assert report["interpreter_staff_id"] != second_seat["id"]
