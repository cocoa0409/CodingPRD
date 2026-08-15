"""Failure-day projection and date-code recommendations: REAL_TIME vs Q10
projection, the tiered increment floor, recommendation gating and OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_lab_result_payload,
    get_study,
    get_success_data,
    propose_and_accept_recommendation,
    propose_recommendation,
    setup_study_in_analysis,
    setup_study_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)

SCI = TEST_USERS["scientist_headers"]
AN = TEST_USERS["analyst_headers"]


def _analysis_study_with_tripped_result(api, study_overrides=None,
                                        day_index=15, test_type="APC",
                                        measured_value=8.0):
    """ANALYSIS study (1 control arm, one SKIPPED time point) with one lab
    result posted against it. Returns (env, lab_result)."""
    env = setup_study_in_analysis(study_overrides=study_overrides,
                                  day_indexes=(day_index,))
    result = get_success_data(api.create_lab_result(
        create_lab_result_payload(env["study"]["id"], env["arms"][0]["id"],
                                  env["time_points"][0]["id"], test_type,
                                  measured_value), AN))
    return env, result


class TestRealTimeVsAcceleratedProjection:
    """Identical raw schedule (one APC 8.0 trip at day_index 15) under the two
    study designs."""

    def _both_studies(self, api):
        rt_env, rt_result = _analysis_study_with_tripped_result(api)
        ac_env, ac_result = _analysis_study_with_tripped_result(
            api,
            study_overrides={"study_type": "ACCELERATED", "storage_temp_c": 40,
                             "reference_temp_c": 20, "q10_factor": 2.0})
        return (rt_env, rt_result), (ac_env, ac_result)

    def test_failure_day_realtime_vs_q10_accelerated(self, api):
        """PRD §3.6: "the factor is the study's `q10_factor` raised to the power of one tenth of the difference between `storage_temp_c` and `reference_temp_c`, and the observation's equivalent days are its `day_index` multiplied by that factor, rounded half-up to 3 decimal places."
        PRD §3.6: "Under `REAL_TIME`, where storage and reference temperatures coincide, the factor is 1 and the equivalent days are simply the observed chronological day as-is."

        Design: Difficulty/dual_variant_calc/shelf_life_realtime_vs_q10_accelerated
        """
        (rt_env, rt_result), (ac_env, ac_result) = self._both_studies(api)
        assert rt_result["tripped"] is True and ac_result["tripped"] is True, (
            "APC 8.0 >= 6.0 trips in both designs")

        rt_arm = get_success_data(
            api.get_study_arm(rt_env["arms"][0]["id"], SCI))
        assert rt_arm["computed_failure_day_equiv"] == pytest.approx(15.0, abs=0.0005), (
            "REAL_TIME factor 1: the chronological day 15 as-is")

        ac_arm = get_success_data(
            api.get_study_arm(ac_env["arms"][0]["id"], SCI))
        # 15 * 2.0 ** ((40 - 20) / 10) = 15 * 4.0 = 60.0
        assert ac_arm["computed_failure_day_equiv"] == pytest.approx(60.0, abs=0.0005), (
            "ACCELERATED Q10: the same day_index projects to 60 equivalent days")

        assert get_study(rt_env["study"]["id"])["earliest_failure_day_equiv"] == \
            pytest.approx(15.0, abs=0.0005)
        assert get_study(ac_env["study"]["id"])["earliest_failure_day_equiv"] == \
            pytest.approx(60.0, abs=0.0005)

    def test_date_codes_diverge_across_designs(self, api):
        """PRD §3.6: "Under `ACCELERATED`, where the storage temperature exceeds the reference and the factor exceeds 1, the same observed `day_index` projects to a larger real-time-equivalent day, so identical raw schedules yield different failure days — and ultimately different date codes — across the two designs."
        PRD §3.7: "the base is the arm's `computed_failure_day_equiv` when one exists, otherwise the study's `target_shelf_life_days`; the base is then reduced by the twenty-percent safety factor — that is, multiplied by 0.8 — and the product rounded down to a whole number of safety days; the rounding increment is 7 days when those safety days are below 90 and 30 days otherwise; and `computed_days` is the safety days divided by the increment, rounded down, multiplied back by the increment."

        Design: Difficulty/dual_variant_calc/shelf_life_realtime_vs_q10_accelerated
        """
        (rt_env, _), (ac_env, _) = self._both_studies(api)

        rec_rt = propose_recommendation(rt_env["study"]["id"],
                                        rt_env["arms"][0]["id"])
        # floor(15 * 0.8) = 12; 12 < 90 -> 7-day tier; floor(12/7) * 7 = 7
        assert rec_rt["computed_days"] == 7
        assert rec_rt["basis"] == "ENDPOINT_MIN"

        rec_ac = propose_recommendation(ac_env["study"]["id"],
                                        ac_env["arms"][0]["id"])
        # floor(60 * 0.8) = 48; 48 < 90 -> 7-day tier; floor(48/7) * 7 = 42
        assert rec_ac["computed_days"] == 42
        assert rec_ac["basis"] == "ENDPOINT_MIN"


class TestTieredIncrementFloor:
    def test_seven_day_tier_below_boundary(self, api):
        """PRD §3.7: "the rounding increment is 7 days when those safety days are below 90 and 30 days otherwise; and `computed_days` is the safety days divided by the increment, rounded down, multiplied back by the increment."
        PRD §3.7: "The recommendation's `basis` records which leg supplied the base: `ENDPOINT_MIN` when the arm had a computed failure day, `TARGET_FALLBACK` otherwise."

        Design: Difficulty/combinatorial_formula/date_code_tiered_increment_floor
        """
        env, _result = _analysis_study_with_tripped_result(
            api, day_index=100, measured_value=7.0)
        rec = propose_recommendation(env["study"]["id"], env["arms"][0]["id"])
        # base 100 -> floor(100 * 0.8) = 80 safety days; 80 < 90 -> 7-day tier;
        # floor(80 / 7) * 7 = 77
        assert rec["computed_days"] == 77
        assert rec["basis"] == "ENDPOINT_MIN"
        assert rec["status"] == "PROPOSED"

    def test_thirty_day_tier_at_or_above_boundary(self, api):
        """PRD §3.7: "the base is the arm's `computed_failure_day_equiv` when one exists, otherwise the study's `target_shelf_life_days`; the base is then reduced by the twenty-percent safety factor — that is, multiplied by 0.8 — and the product rounded down to a whole number of safety days; the rounding increment is 7 days when those safety days are below 90 and 30 days otherwise"

        Design: Difficulty/combinatorial_formula/date_code_tiered_increment_floor
        """
        env = setup_study_in_analysis(
            study_overrides={"target_shelf_life_days": 120})
        rec = propose_recommendation(env["study"]["id"], env["arms"][0]["id"])
        # nothing tripped -> base = target 120 -> floor(120 * 0.8) = 96;
        # 96 >= 90 -> 30-day tier; floor(96 / 30) * 30 = 90
        assert rec["computed_days"] == 90
        assert rec["basis"] == "TARGET_FALLBACK"


class TestRecommendationGates:
    def test_recommendation_requires_analysis_state(self, api):
        """PRD §3.7: "A `SensoryScientist` proposes one against a `study_id` and `arm_id` while the study is `ANALYSIS` or `REPORTING` (else `ERR_INVALID_STUDY_STATE`), with the arm belonging to the study (else `ERR_ARM_STUDY_MISMATCH`), and the request is OCC-guarded by `expected_study_version` per §2.7."

        Design: Corner/validations/recommendation_requires_analysis_state
        """
        env = setup_study_in_progress(with_chamber=False)
        study = get_study(env["study"]["id"])  # IN_PROGRESS, current version
        resp = api.create_recommendation(
            {"study_id": study["id"], "arm_id": env["arms"][0]["id"],
             "expected_study_version": study["version"]}, SCI)
        validate_error(resp, ApiErrorId.ERR_INVALID_STUDY_STATE, 409)
        _rows, meta = validate_paginated(api.list_recommendations(
            SCI, params={"study_id": study["id"]}))
        assert meta["total_count"] == 0

    def test_occ_stale_version_on_recommendation_create(self, api):
        """PRD §2.7: "Recommendation creation legitimately supersedes the arm's prior `PROPOSED` recommendation, so a second creator holding a stale study version must be refused with `ERR_STALE_STUDY_VERSION` (HTTP 412) rather than silently superseding on old data."
        PRD §3.7: "Creation succeeds into `PROPOSED`, supersedes any existing `PROPOSED` recommendation for the same arm — with the report-flagging consequences below — and increments the study's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_recommendation_create
        """
        env = setup_study_in_analysis()  # target 60 -> fallback 42
        study = get_study(env["study"]["id"])
        stale_version = study["version"]

        rec1 = validate_success(api.create_recommendation(
            {"study_id": study["id"], "arm_id": env["arms"][0]["id"],
             "expected_study_version": stale_version}, SCI), 201)
        assert rec1["status"] == "PROPOSED"
        assert rec1["computed_days"] == 42, (
            "fallback: floor(60 * 0.8) = 48 -> 7-day tier -> 42")

        # the first create bumped Study.version; replaying the old one is stale
        resp = api.create_recommendation(
            {"study_id": study["id"], "arm_id": env["arms"][0]["id"],
             "expected_study_version": stale_version}, SCI)
        validate_error(resp, ApiErrorId.ERR_STALE_STUDY_VERSION, 412)

        rec1_now = get_success_data(api.get_recommendation(rec1["id"], SCI))
        assert rec1_now["status"] == "PROPOSED", (
            "the rejected write must not supersede the existing PROPOSED rec")

    def test_recommendation_accept_twice_rejected(self, api):
        """PRD §3.7: "A recommendation in `PROPOSED` may be accepted or rejected by a `SensoryScientist`; acting on one that is not `PROPOSED` is `ERR_RECO_NOT_PROPOSED`."

        Design: Corner/state_machines/recommendation_accept_twice_rejected
        """
        env = setup_study_in_analysis()
        rec = propose_and_accept_recommendation(env["study"]["id"],
                                                env["arms"][0]["id"])
        assert rec["status"] == "ACCEPTED"

        validate_error(api.accept_recommendation(rec["id"], SCI),
                       ApiErrorId.ERR_RECO_NOT_PROPOSED, 409)
        validate_error(api.reject_recommendation(rec["id"], SCI),
                       ApiErrorId.ERR_RECO_NOT_PROPOSED, 409)
        assert get_success_data(api.get_recommendation(rec["id"], SCI))["status"] \
            == "ACCEPTED"
