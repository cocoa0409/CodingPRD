"""Two calculations in this laboratory answer differently for identical numbers.

A biologic control's deviation is measured either against the subject's
enrolment baseline or against a rolling mean of that subject's recent blows, and
a bronchodilator response is scored either against the patient's own pre value
or against the predicted value.  In both cases the variant is chosen by stored
data, never by the caller.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_fields_equal,
)
from test_helpers.test_users import LAB_MANAGER, make_technologist_headers

PRIOR_CONTROL_BLOWS = ((3.600, 4.900), (3.640, 4.910), (3.620, 4.920))


def _lab_with_stale_and_fresh_control_subjects(api):
    """A calibrated device plus two enrolled subjects of differing baseline age.

    T-090's baseline was established 565 days before the logical clock, so its
    comparator has drifted out of validity; T-091's is 94 days old.
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    tech = fx.register_technologist(api)
    tech_headers = make_technologist_headers(tech["id"])
    stale = fx.register_biologic_control_subject(api, baseline_established_on="2025-01-15")
    fresh = fx.register_biologic_control_subject(
        api,
        employee_code="T-091",
        full_name="Nia Kaur",
        baseline_established_on="2026-05-01",
    )
    device = fx.register_device(api, "SPIRO-1", "SPIROMETRY")
    fx.append_quality_event(api, device["id"], f.calibration_event_payload(), tech_headers)
    return tech_headers, stale["id"], fresh["id"], device["id"]


def _record_prior_control_history(api, device_id, subject_id, tech_headers):
    """Three warning-level blows by the same subject on the same device."""
    latest = None
    for measured_fev1_l, measured_fvc_l in PRIOR_CONTROL_BLOWS:
        latest = fx.append_quality_event(
            api,
            device_id,
            f.biologic_control_event_payload(subject_id, measured_fev1_l, measured_fvc_l),
            tech_headers,
        )
    return latest


class TestBiologicControlComparatorVariants:
    """A stale enrolment baseline hands the comparison to a rolling mean."""

    def test_rolling_mean_comparator_warns_where_the_enrolment_baseline_passes(self, api):
        """An identical blow of 3.850 L diverges on comparator choice alone.

        PRD 3.2: "Because the drift-tolerant rolling comparator and the fixed
        enrolment comparator disagree, an identical `measured_fev1_l` can pass
        under one variant and warn or fail under the other."

        Design: Difficulty/dual_variant_calc/bcs_comparator_absolute_baseline_vs_rolling_mean_divergence
        """
        tech_headers, stale_id, fresh_id, device_id = (
            _lab_with_stale_and_fresh_control_subjects(api)
        )
        _record_prior_control_history(api, device_id, stale_id, tech_headers)

        rolling = validate_success(
            api.create_quality_event(
                device_id,
                f.biologic_control_event_payload(stale_id, 3.850, 5.100),
                tech_headers,
            ),
            expected_status=201,
        )
        absolute = validate_success(
            api.create_quality_event(
                device_id,
                f.biologic_control_event_payload(fresh_id, 3.850, 5.100),
                tech_headers,
            ),
            expected_status=201,
        )

        assert rolling["deviation_variant"] == "ROLLING_MEAN"
        assert_3dp(rolling["rolling_mean_fev1_l"], 3.620)
        assert_2dp(rolling["deviation_pct"], 6.35)
        assert rolling["outcome"] == "WARN"
        assert rolling["failure_reason"] is None

        assert absolute["deviation_variant"] == "ABSOLUTE_BASELINE"
        assert absolute["rolling_mean_fev1_l"] is None
        assert_2dp(absolute["deviation_pct"], 3.75)
        assert absolute["outcome"] == "PASS"

        assert_2dp(rolling["deviation_pct"] - absolute["deviation_pct"], 2.60)
        assert rolling["outcome"] != absolute["outcome"], (
            "the same measured FEV1 must not produce the same verdict under both variants"
        )

    def test_a_window_shorter_than_three_blows_falls_back_to_the_enrolment_baseline(self, api):
        """The stale subject's third blow still measures against the stored baseline.

        PRD 3.2: "If fewer than three qualifying prior records exist, the
        variant falls back to `ABSOLUTE_BASELINE` and the stored baseline is
        used after all."

        Design: Difficulty/dual_variant_calc/bcs_comparator_absolute_baseline_vs_rolling_mean_divergence
        """
        tech_headers, stale_id, fresh_id, device_id = (
            _lab_with_stale_and_fresh_control_subjects(api)
        )
        third = _record_prior_control_history(api, device_id, stale_id, tech_headers)

        assert third["deviation_variant"] == "ABSOLUTE_BASELINE"
        assert_2dp(third["deviation_pct"], 9.50)
        assert third["rolling_mean_fev1_l"] is None

        fx.append_quality_event(
            api,
            device_id,
            f.biologic_control_event_payload(stale_id, 3.850, 5.100),
            tech_headers,
        )
        fx.append_quality_event(
            api,
            device_id,
            f.biologic_control_event_payload(fresh_id, 3.850, 5.100),
            tech_headers,
        )

        device = validate_success(api.get_device(device_id, LAB_MANAGER))
        assert_fields_equal(
            device,
            {
                "status": "AVAILABLE",
                "consecutive_biologic_failures": 0,
                "last_biologic_control_date": "2026-08-03",
            },
        )


def _record_pre_and_post_bronchodilator_efforts(api, session_id, tech_headers):
    """Three pre-bronchodilator efforts and one post-bronchodilator effort."""
    fx.append_maneuver_series(api, session_id, tech_headers)
    fx.append_maneuver(api, session_id, f.post_bronchodilator_maneuver_payload(), tech_headers)


def _two_sessions_with_identical_effort_data(api):
    """Two sessions with byte-identical blows, pinned to differing equation sets.

    The first session is booked while GLI-M-2005 is the only published set, so
    it pins that one; GLI-M-2021 is published afterwards with a narrower age
    band, so the second session pins that one instead.
    """
    lab = fx.build_lab(api, device_codes=("SPIRO-1", "SPIRO-2"))
    order1 = fx.build_ready_order(api, lab, bronchodilator_requested=True)
    session1 = fx.schedule_session(
        api,
        order1["id"],
        lab.device_ids[0],
        lab.tech1,
        "2026-08-03T09:00:00Z",
        "2026-08-03T09:30:00Z",
    )
    _record_pre_and_post_bronchodilator_efforts(api, session1["id"], lab.tech1)

    fx.publish_reference_equation(
        api,
        equation_code="GLI-M-2021",
        applicable_age_min=44,
        applicable_age_max=46,
        bd_criterion="PCT_PREDICTED_2021",
    )
    order2 = fx.build_ready_order(api, lab, bronchodilator_requested=True)
    session2 = fx.schedule_session(
        api,
        order2["id"],
        lab.device_ids[1],
        lab.tech1,
        "2026-08-03T10:00:00Z",
        "2026-08-03T10:30:00Z",
    )
    _record_pre_and_post_bronchodilator_efforts(api, session2["id"], lab.tech1)
    return lab, session1, session2


class TestBronchodilatorCriterionVariants:
    """The equation set a session pinned decides how its reversal is scored."""

    def test_the_pinned_criterion_decides_the_reversibility_verdict(self, api):
        """The same 320 mL gain is positive under one criterion and not the other.

        PRD 3.6: "Which percentage accompanies it depends on the `bd_criterion`
        of the equation set pinned to this study, and that choice is recorded in
        `bd_response_variant`. Under `PCT_BASELINE_2005` the older convention
        applies: `bd_response_pct` is the gain divided by `best_fev1_l`, times
        100, to one decimal place, and `bd_response_positive` is true only when
        that percentage is at least 12.0 **and** `bd_response_ml` is at least
        200. Under `PCT_PREDICTED_2021` the newer convention applies:
        `bd_response_pct` is the gain divided by `predicted_fev1_l`, times 100,
        to one decimal place, and `bd_response_positive` is true when that
        percentage is at least 10.0, with no accompanying absolute-volume
        requirement."

        Design: Difficulty/dual_variant_calc/bronchodilator_criterion_2005_baseline_vs_2021_predicted_divergence
        """
        lab, session1, session2 = _two_sessions_with_identical_effort_data(api)

        closed1 = fx.finalize_quality(api, session1["id"], lab.tech1)
        closed2 = fx.finalize_quality(api, session2["id"], lab.tech1)

        assert closed1["reference_equation_code"] == "GLI-M-2005"
        assert closed1["bd_response_variant"] == "PCT_BASELINE_2005"
        assert_1dp(closed1["bd_response_pct"], 13.3)
        assert closed1["bd_response_positive"] is True

        assert closed2["reference_equation_code"] == "GLI-M-2021"
        assert closed2["bd_response_variant"] == "PCT_PREDICTED_2021"
        assert_1dp(closed2["bd_response_pct"], 8.0)
        assert closed2["bd_response_positive"] is False

    def test_both_criteria_share_their_inputs_and_the_absolute_gain(self, api):
        """The divergence is attributable to the criterion and nothing else.

        PRD 3.6: "`bd_response_ml` is the whole-millilitre gain from
        `best_fev1_l` to `best_fev1_post_l`."

        Design: Difficulty/dual_variant_calc/bronchodilator_criterion_2005_baseline_vs_2021_predicted_divergence
        """
        lab, session1, session2 = _two_sessions_with_identical_effort_data(api)

        closed1 = fx.finalize_quality(api, session1["id"], lab.tech1)
        closed2 = fx.finalize_quality(api, session2["id"], lab.tech1)

        for closed in (closed1, closed2):
            assert_3dp(closed["predicted_fev1_l"], 4.000)
            assert_3dp(closed["best_fev1_l"], 2.400)
            assert_3dp(closed["best_fev1_post_l"], 2.720)
            assert closed["bd_response_ml"] == 320
            assert closed["session_status"] == "ACCEPTED"
            assert closed["quality_grade"] == "A"
