"""Lab test results: measurement-range vs referential ordering, study-chain
coherence, and the micro-sensory correlation read."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate,
    add_arm,
    add_time_point,
    analyze_session,
    assign_panelist,
    create_client,
    create_draft_study,
    create_lab_result_payload,
    create_qualified_panelist,
    create_session,
    get_success_data,
    get_time_point,
    lock_session,
    open_session,
    pull_units,
    set_clock,
    setup_study_in_progress,
    submit_all_scores,
    submit_and_approve,
    validate_error,
    validate_paginated,
    validate_success,
)

LD = TEST_USERS["lab_director_headers"]
SCI = TEST_USERS["scientist_headers"]
PC = TEST_USERS["coordinator_headers"]
AN = TEST_USERS["analyst_headers"]


def _two_active_studies(api):
    """Shared client topped 200; studies A and B each with 1 control arm + tp0,
    both IN_PROGRESS."""
    set_clock()
    client = create_client(topup_hours=200)
    envs = []
    for name, variant in (("Milk A", "STANDARD_FILM"), ("Milk B", "MAP")):
        study = create_draft_study(client["id"], product_name=name)
        arm = add_arm(study["id"], variant, is_control=True)
        tp0 = add_time_point(study["id"], 0)
        submit_and_approve(study["id"])
        activate(study["id"])
        envs.append({"study": study, "arm": arm, "tp0": tp0})
    return envs


class TestMeasurementRangePrecedence:
    def test_range_error_beats_foreign_arm(self, api):
        """PRD §3.6: "The measurement-range check is evaluated before the referential checks: `APC` accepts values from 0 to 12 inclusive, `YEAST_MOLD` and `LACTIC` from 0 to 10 inclusive, `PEROXIDE_VALUE` from 0 to 500 inclusive, `PH` from 0 to 14 inclusive, and `WATER_ACTIVITY` from 0 to 1 inclusive; anything outside is `ERR_MEASUREMENT_OUT_OF_RANGE`."

        Design: Difficulty/priority_pair_validation_conflict/measurement_range_error_beats_referential_error
        """
        a, b = _two_active_studies(api)
        # 999.0 is outside APC [0,12] AND arm_b belongs to another study:
        # the business_safety error must win over business_referential.
        resp = api.create_lab_result(
            create_lab_result_payload(a["study"]["id"], b["arm"]["id"],
                                      a["tp0"]["id"], "APC", 999.0), AN)
        validate_error(resp, ApiErrorId.ERR_MEASUREMENT_OUT_OF_RANGE, 422)

        _rows, meta = validate_paginated(
            api.list_lab_results(AN, params={"study_id": a["study"]["id"]}))
        assert meta["total_count"] == 0, "no result row may be created"

    def test_range_error_beats_foreign_time_point(self, api):
        """PRD §3.6: "The measurement-range check is evaluated before the referential checks"
        PRD §2.6: "Every request is validated against an ordered ladder of checks, and the first rung that fails determines the error returned."

        Design: Difficulty/priority_pair_validation_conflict/measurement_range_error_beats_referential_error
        """
        a, b = _two_active_studies(api)
        # Same double violation on the time-point leg: own arm, foreign time
        # point, out-of-range value — the range error still wins.
        resp = api.create_lab_result(
            create_lab_result_payload(a["study"]["id"], a["arm"]["id"],
                                      b["tp0"]["id"], "APC", 999.0), AN)
        validate_error(resp, ApiErrorId.ERR_MEASUREMENT_OUT_OF_RANGE, 422)

        _rows, meta = validate_paginated(
            api.list_lab_results(AN, params={"study_id": a["study"]["id"]}))
        assert meta["total_count"] == 0


class TestStudyChainCoherence:
    def test_lab_result_arm_and_timepoint_study_mismatch(self, api):
        """PRD §3.6: "Then the arm and time point must belong to the named study (else `ERR_ARM_STUDY_MISMATCH` or `ERR_TIME_POINT_STUDY_MISMATCH`)."

        Design: Corner/validations/lab_result_arm_and_timepoint_study_mismatch
        """
        a, b = _two_active_studies(api)
        # well-ranged value, foreign arm
        validate_error(api.create_lab_result(
            create_lab_result_payload(a["study"]["id"], b["arm"]["id"],
                                      a["tp0"]["id"], "APC", 3.0), AN),
            ApiErrorId.ERR_ARM_STUDY_MISMATCH, 422)
        # well-ranged value, own arm, foreign time point
        validate_error(api.create_lab_result(
            create_lab_result_payload(a["study"]["id"], a["arm"]["id"],
                                      b["tp0"]["id"], "APC", 3.0), AN),
            ApiErrorId.ERR_TIME_POINT_STUDY_MISMATCH, 422)
        _rows, meta = validate_paginated(
            api.list_lab_results(AN, params={"study_id": a["study"]["id"]}))
        assert meta["total_count"] == 0


class TestCorrelation:
    def test_correlation_perfect_negative_over_three_pairs(self, api):
        """PRD §3.6: "The coefficient is the Pearson product-moment correlation over the paired deviations — the sum of the products of each series' deviations from its own mean, divided by the square root of the product of the two sums of squared deviations — rounded half-up to 4 decimal places, and the response carries the `coefficient`, the `pair_count`, and the echoed `arm_id`, `test_type`, and `attribute`."
        PRD §3.5: "when every session of the time point that is not `CANCELLED` has reached `ANALYZED`, with at least one having done so, the time point itself moves `PULLED → EVALUATED`."

        Design: Corner/calculations/correlation_perfect_negative_over_three_pairs
        """
        env = setup_study_in_progress(day_indexes=(0, 7, 14),
                                      chamber_capacity=20)
        study_id = env["study"]["id"]
        arm_id = env["arms"][0]["id"]
        chamber_id = env["chamber"]["id"]
        tp0, tp7, tp14 = [tp["id"] for tp in env["time_points"]]
        panelists = [create_qualified_panelist() for _ in range(4)]
        sessions = {}
        assignments = {}
        for tp_id, start in ((tp0, "2026-08-01T10:00:00Z"),
                             (tp7, "2026-08-08T10:00:00Z"),
                             (tp14, "2026-08-15T10:00:00Z")):
            end = start.replace("T10:00", "T11:00")
            s = create_session(study_id, tp_id, arm_id, start, end)
            sessions[tp_id] = s
            assignments[tp_id] = [assign_panelist(s["id"], p["id"])
                                  for p in panelists]

        day_plan = [
            (tp0, "2026-08-01", 9, 1.0),
            (tp7, "2026-08-08", 7, 2.0),
            (tp14, "2026-08-15", 5, 3.0),
        ]
        for tp_id, day, overall, ph_value in day_plan:
            set_clock(f"{day}T00:00:00Z")
            pull_units(tp_id, chamber_id, arm_id, quantity=4,
                       unit_purpose="EVALUATION")
            set_clock(f"{day}T10:00:00Z")
            open_session(sessions[tp_id]["id"])
            for i, p in enumerate(panelists):
                submit_all_scores(assignments[tp_id][i]["id"], p["id"],
                                  uniform_score=overall)
            lock_session(sessions[tp_id]["id"])
            analyze_session(sessions[tp_id]["id"])
            # PH values 1.0/2.0/3.0: inside [0,14], below the 8.0 trip limit
            get_success_data(api.create_lab_result(
                create_lab_result_payload(study_id, arm_id, tp_id, "PH",
                                          ph_value), AN))

        resp = api.get_correlation(study_id, SCI,
                                   params={"arm_id": arm_id, "test_type": "PH",
                                           "attribute": "OVERALL"})
        data = validate_success(resp)
        assert data["pair_count"] == 3
        assert data["coefficient"] == pytest.approx(-1.0, abs=0.0001), (
            "pairs (1.0, 9.0), (2.0, 7.0), (3.0, 5.0) are perfectly anti-linear")
        assert data["arm_id"] == arm_id and data["test_type"] == "PH"
        assert data["attribute"] == "OVERALL"

        for tp_id in (tp0, tp7, tp14):
            assert get_time_point(tp_id)["status"] == "EVALUATED", (
                "bubble-up after the session at that point is ANALYZED")
        for tp_id in (tp0, tp7, tp14):
            sess = get_success_data(api.get_session(sessions[tp_id]["id"], PC))
            assert sess["sensory_failed"] is False, (
                "single-arm study: no significant control difference exists")

    def test_correlation_insufficient_pairs_rejected(self, api):
        """PRD §3.6: "Fewer than three such pairs is `ERR_INSUFFICIENT_CORRELATION_PAIRS`."

        Design: Corner/calculations/correlation_insufficient_pairs_rejected
        """
        env = setup_study_in_progress()
        get_success_data(api.create_lab_result(
            create_lab_result_payload(env["study"]["id"], env["arms"][0]["id"],
                                      env["time_points"][0]["id"], "PH", 4.2),
            AN))
        # zero ANALYZED sessions -> zero pairs
        validate_error(api.get_correlation(
            env["study"]["id"], SCI,
            params={"arm_id": env["arms"][0]["id"], "test_type": "PH",
                    "attribute": "OVERALL"}),
            ApiErrorId.ERR_INSUFFICIENT_CORRELATION_PAIRS, 422)
