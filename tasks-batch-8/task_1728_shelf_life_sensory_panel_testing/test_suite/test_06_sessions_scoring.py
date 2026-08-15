"""Evaluation sessions, assignments, and attribute scoring: session lifecycle
gates, quorum, score validation, ownership, means, and consistency indexes."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_arm,
    add_time_point,
    analyze_session,
    assign_panelist,
    create_client,
    create_draft_study,
    create_qualified_panelist,
    create_score_payload,
    create_session,
    get_assignment,
    get_panelist,
    get_session,
    get_study,
    get_success_data,
    lock_session,
    make_panelist_headers,
    open_session,
    pull_units,
    set_clock,
    setup_session_panel,
    setup_study_in_progress,
    submit_all_scores,
    submit_and_approve,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

LD = TEST_USERS["lab_director_headers"]
SCI = TEST_USERS["scientist_headers"]
PC = TEST_USERS["coordinator_headers"]


def _scheduled_study_with_session(api, day_indexes=(0,)):
    """SCHEDULED study (1 control arm, given time points) + one PLANNED session
    on the first time point. Returns (study, arm, tps, session)."""
    set_clock()
    client = create_client()
    study = create_draft_study(client["id"])
    arm = add_arm(study["id"], "STANDARD_FILM", is_control=True)
    tps = [add_time_point(study["id"], d) for d in day_indexes]
    submit_and_approve(study["id"])
    session = create_session(study["id"], tps[0]["id"], arm["id"],
                             "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
    return study, arm, tps, session


def _open_session_with_panel(api, num_panelists=1, study_overrides=None,
                             qualified_attributes=None):
    """IN_PROGRESS study + pulled units + session (tp0, ctrl, 10:00-11:00) OPEN
    at clock 10:00 + QUALIFIED panelists assigned. Returns
    (env, session, panelists, assignments)."""
    env = setup_session_panel(num_panelists=num_panelists,
                              study_overrides=study_overrides)
    if qualified_attributes is not None:
        # rebuild the panel with narrowed qualifications
        env["panelists"] = [create_qualified_panelist(
            qualified_attributes=qualified_attributes)
            for _ in range(num_panelists)]
        env["assignments"] = {env["sessions"][0]["id"]: [
            assign_panelist(env["sessions"][0]["id"], p["id"])
            for p in env["panelists"]]}
    session = env["sessions"][0]
    set_clock("2026-08-01T10:00:00Z")
    open_session(session["id"])
    assignments = env["assignments"][session["id"]]
    return env, session, env["panelists"], assignments


class TestSessionUniquenessAndMakeup:
    def test_session_exists_per_arm_timepoint(self, api):
        """PRD §3.5: "no other session that is not `CANCELLED` may already exist for the same `(time_point_id, arm_id)` pairing (else `ERR_SESSION_EXISTS`)."

        Design: Corner/validations/session_exists_per_arm_timepoint
        """
        study, arm, tps, _s1 = _scheduled_study_with_session(api)
        resp = api.create_session(
            {"study_id": study["id"], "time_point_id": tps[0]["id"],
             "arm_id": arm["id"], "scheduled_start_utc": "2026-08-03T10:00:00Z",
             "scheduled_end_utc": "2026-08-03T11:00:00Z"}, PC)
        validate_error(resp, ApiErrorId.ERR_SESSION_EXISTS, 409)
        _rows, meta = validate_paginated(
            api.list_sessions(PC, params={"time_point_id": tps[0]["id"]}))
        assert meta["total_count"] == 1

    def test_makeup_session_links_cancelled_source(self, api):
        """PRD §3.5: "scheduling a makeup **creates a new session** in `PLANNED` that copies the source's `study_id`, `time_point_id`, and `arm_id`, records the lineage in `makeup_of_id` pointing at the source session (null on any session not born as a makeup), and receives a freshly computed `required_panelist_count`."
        PRD §3.5: "The source must be `CANCELLED` (else `ERR_INVALID_SESSION_STATE`) and stays `CANCELLED`; because the uniqueness rule of session creation counts only sessions that are not `CANCELLED`, the cancelled source does not block its own makeup"
        PRD §4: "Operations that create new resources — clients, studies, arms, time points, chambers, panelists, sessions (including makeups), assignments, scores, lab results, recommendations, reports, claims, retainer top-ups, and sample pulls — return `201 Created`."

        Design: Corner/state_machines/makeup_session_links_cancelled_source
        """
        _study, _arm, tps, s1 = _scheduled_study_with_session(api)
        cancelled = validate_success(api.cancel_session(s1["id"], PC))
        assert cancelled["status"] == "CANCELLED"

        makeup = validate_success(api.schedule_makeup(
            s1["id"], {"scheduled_start_utc": "2026-08-03T10:00:00Z",
                       "scheduled_end_utc": "2026-08-03T11:00:00Z"}, PC), 201)
        assert makeup["status"] == "PLANNED"
        assert makeup["makeup_of_id"] == s1["id"], "lineage points at the source"
        assert makeup["id"] != s1["id"], "the makeup is a new row, not a revert"

        source = get_session(s1["id"])
        assert source["status"] == "CANCELLED", "the source stays CANCELLED"

        rows, meta = validate_paginated(
            api.list_sessions(PC, params={"makeup_of_id": s1["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == makeup["id"]


class TestSessionOpenGates:
    def test_session_open_requires_pulled_samples(self, api):
        """PRD §3.5: "requires at least one sample unit to exist for the session's `time_point_id` and `arm_id` (else `ERR_NO_PULLED_SAMPLES`)"

        Design: Difficulty/cross_entity_state_dependency/session_open_requires_pulled_samples
        """
        env = setup_study_in_progress()
        session = create_session(env["study"]["id"], env["time_points"][0]["id"],
                                 env["arms"][0]["id"])
        set_clock("2026-08-01T10:00:00Z")  # inside the session's open window

        resp = api.open_session(session["id"], PC)
        validate_error(resp, ApiErrorId.ERR_NO_PULLED_SAMPLES, 409)
        assert get_session(session["id"])["status"] == "PLANNED"

    def test_session_open_succeeds_after_pull(self, api):
        """PRD §3.5: "requires at least one sample unit to exist for the session's `time_point_id` and `arm_id` (else `ERR_NO_PULLED_SAMPLES`)"
        PRD §3.5: "Opening a session — `PLANNED → OPEN`, driven by a `PanelCoordinator`"

        Design: Difficulty/cross_entity_state_dependency/session_open_requires_pulled_samples
        """
        env = setup_study_in_progress()
        session = create_session(env["study"]["id"], env["time_points"][0]["id"],
                                 env["arms"][0]["id"])
        set_clock("2026-08-01T10:00:00Z")
        validate_error(api.open_session(session["id"], PC),
                       ApiErrorId.ERR_NO_PULLED_SAMPLES, 409)

        pull_units(env["time_points"][0]["id"], env["chamber"]["id"],
                   env["arms"][0]["id"], quantity=1, unit_purpose="EVALUATION")
        opened = validate_success(api.open_session(session["id"], PC))
        assert opened["status"] == "OPEN"

    def test_session_open_outside_window_then_inside(self, api):
        """PRD §3.5: "the logical clock must read no earlier than thirty minutes before `scheduled_start_utc` and no later than `scheduled_end_utc`, both boundaries inclusive, else `ERR_OUTSIDE_SESSION_WINDOW`"

        Design: Corner/validations/session_open_outside_window_then_inside
        """
        env = setup_study_in_progress()
        session = create_session(env["study"]["id"], env["time_points"][0]["id"],
                                 env["arms"][0]["id"])
        pull_units(env["time_points"][0]["id"], env["chamber"]["id"],
                   env["arms"][0]["id"], quantity=1, unit_purpose="EVALUATION")

        set_clock("2026-08-01T09:00:00Z")  # more than 30 min before 10:00
        validate_error(api.open_session(session["id"], PC),
                       ApiErrorId.ERR_OUTSIDE_SESSION_WINDOW, 409)

        set_clock("2026-08-01T09:45:00Z")  # inside [09:30, 11:00]
        opened = validate_success(api.open_session(session["id"], PC))
        assert opened["status"] == "OPEN"


class TestLockGates:
    def test_session_lock_from_planned_rejected(self, api):
        """PRD §3.5: "Locking a session is the analytical hinge of the whole system, and it is gated on quorum: the session must be `OPEN`, and the count of its `SUBMITTED` assignments must be at least `required_panelist_count` — equality satisfies quorum — else `ERR_SESSION_UNDER_QUORUM`."
        PRD §2.6: "The target resource's state must permit the requested transition, else the applicable one of `ERR_INVALID_STUDY_STATE`, `ERR_INVALID_SESSION_STATE`, `ERR_INVALID_TIME_POINT_STATE`, `ERR_INVALID_PANELIST_STATE`, `ERR_INVALID_ASSIGNMENT_STATE`"
        (The lock sentence names the quorum error for its gated conjunction
        without committing to the state-check preemption, so either lock-gate
        error id satisfies the PRD; both are 409.)

        Design: Corner/state_machines/session_lock_from_planned_rejected
        """
        _study, _arm, tps, s1 = _scheduled_study_with_session(api,
                                                              day_indexes=(0, 1))
        s2 = create_session(_study["id"], tps[1]["id"], _arm["id"],
                            "2026-08-02T12:00:00Z", "2026-08-02T13:00:00Z")
        get_success_data(api.cancel_session(s2["id"], PC))

        resp1 = api.lock_session(s1["id"], PC)
        assert resp1.status_code == 409
        validate_error_is_one_of(resp1, [ApiErrorId.ERR_INVALID_SESSION_STATE.value,
                                         ApiErrorId.ERR_SESSION_UNDER_QUORUM.value])

        resp2 = api.lock_session(s2["id"], PC)
        assert resp2.status_code == 409
        validate_error_is_one_of(resp2, [ApiErrorId.ERR_INVALID_SESSION_STATE.value,
                                         ApiErrorId.ERR_SESSION_UNDER_QUORUM.value])

        assert get_session(s1["id"])["status"] == "PLANNED"
        assert get_session(s2["id"])["status"] == "CANCELLED"

    def test_session_quorum_boundary(self, api):
        """PRD §3.5: "the count of its `SUBMITTED` assignments must be at least `required_panelist_count` — equality satisfies quorum — else `ERR_SESSION_UNDER_QUORUM`"
        PRD §3.5: "the moment the sixth distinct attribute score is recorded — covering all six attributes — the assignment flips `ASSIGNED → SUBMITTED` automatically and the panelist's `consecutive_no_shows` resets to 0."

        Design: Corner/validations/session_quorum_boundary
        """
        env, session, panelists, assignments = _open_session_with_panel(
            api, num_panelists=4)
        assert session["required_panelist_count"] == 4

        # 3 of 4 submitted -> under quorum
        for i in range(3):
            submit_all_scores(assignments[i]["id"], panelists[i]["id"],
                              uniform_score=9)
        resp = api.lock_session(session["id"], PC)
        validate_error(resp, ApiErrorId.ERR_SESSION_UNDER_QUORUM, 409)

        # the 4th submission reaches quorum exactly -> lock succeeds
        fourth = submit_all_scores(assignments[3]["id"], panelists[3]["id"],
                                   uniform_score=9)
        assert fourth["status"] == "SUBMITTED", (
            "the sixth distinct attribute auto-flipped the assignment")
        locked = validate_success(api.lock_session(session["id"], PC))
        assert locked["status"] == "LOCKED"
        assert locked["overall_mean"] == pytest.approx(9.0, abs=0.005)


class TestScoreValidation:
    def test_score_out_of_range_rejected(self, api):
        """PRD §3.5: "the `score` must be an integer from 1 to 15 inclusive on the fifteen-point scale (else `ERR_SCORE_OUT_OF_RANGE`)"

        Design: Corner/validations/score_out_of_range_rejected
        """
        _env, _session, panelists, assignments = _open_session_with_panel(
            api, num_panelists=1)
        p, a = panelists[0], assignments[0]
        headers = make_panelist_headers(p["id"])

        validate_error(api.create_score(
            create_score_payload(a["id"], "OVERALL", 16), headers),
            ApiErrorId.ERR_SCORE_OUT_OF_RANGE, 422)
        validate_error(api.create_score(
            create_score_payload(a["id"], "OVERALL", 0), headers),
            ApiErrorId.ERR_SCORE_OUT_OF_RANGE, 422)

        ok = validate_success(api.create_score(
            create_score_payload(a["id"], "OVERALL", 1), headers), 201)
        assert ok["score"] == 1, "the lower boundary is inclusive"
        _rows, meta = validate_paginated(
            api.list_scores(PC, params={"assignment_id": a["id"]}))
        assert meta["total_count"] == 1

    def test_panelist_cannot_score_others_assignment(self, api):
        """PRD §3.5: "the assignment's `panelist_id` must equal the acting `X-User-ID` (else `ERR_FORBIDDEN_ROLE`)"
        PRD §2.1: "When `X-User-Role` is `Panelist`, `X-User-ID` is the `id` of the acting `Panelist` record; ownership checks on any resource that references a `Panelist` — in particular an assignment's `panelist_id` — compare that foreign-key field to `X-User-ID`."

        Design: Corner/validations/panelist_cannot_score_others_assignment
        """
        _env, _session, panelists, assignments = _open_session_with_panel(
            api, num_panelists=2)
        p1, a2 = panelists[0], assignments[1]

        resp = api.create_score(
            create_score_payload(a2["id"], "OVERALL", 9),
            make_panelist_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        _rows, meta = validate_paginated(
            api.list_scores(PC, params={"assignment_id": a2["id"]}))
        assert meta["total_count"] == 0

    def test_unqualified_attribute_score_rejected(self, api):
        """PRD §3.5: "the `attribute` must appear in the panelist's `qualified_attributes` (else `ERR_PANELIST_NOT_QUALIFIED`)"

        Design: Corner/validations/unqualified_attribute_score_rejected
        """
        _env, _session, panelists, assignments = _open_session_with_panel(
            api, num_panelists=1, qualified_attributes=["OVERALL"])
        p, a = panelists[0], assignments[0]
        headers = make_panelist_headers(p["id"])

        validate_error(api.create_score(
            create_score_payload(a["id"], "FLAVOR", 8), headers),
            ApiErrorId.ERR_PANELIST_NOT_QUALIFIED, 409)
        ok = validate_success(api.create_score(
            create_score_payload(a["id"], "OVERALL", 8), headers), 201)
        assert ok["attribute"] == "OVERALL"

    def test_attribute_score_immutability_and_duplicate(self, api):
        """PRD §2.5: "An `AttributeScore` and a `LabTestResult` are immutable event records: each carries only `id` and `created_at`, and both `updated_at` and `version` are absent"
        PRD §3.5: "the `(assignment_id, attribute)` pair must not already have a score (else `ERR_SCORE_ALREADY_SUBMITTED`)"
        PRD §3.5: "the moment the sixth distinct attribute score is recorded — covering all six attributes — the assignment flips `ASSIGNED → SUBMITTED` automatically"

        Design: Corner/entities/attribute_score_immutability_and_duplicate
        """
        _env, _session, panelists, assignments = _open_session_with_panel(
            api, num_panelists=1)
        p, a = panelists[0], assignments[0]
        headers = make_panelist_headers(p["id"])

        first = validate_success(api.create_score(
            create_score_payload(a["id"], "OVERALL", 9), headers), 201)
        assert "version" not in first and "updated_at" not in first, (
            "immutable event records carry only id + created_at")

        resp = api.create_score(create_score_payload(a["id"], "OVERALL", 7),
                                headers)
        validate_error(resp, ApiErrorId.ERR_SCORE_ALREADY_SUBMITTED, 409)

        kept = validate_success(api.get_score(first["id"], PC))
        assert kept["score"] == 9, "the rejected write leaves the event untouched"
        assert "version" not in kept and "updated_at" not in kept

        assert get_assignment(a["id"])["status"] == "ASSIGNED", (
            "SUBMITTED only arrives at the sixth distinct attribute")


class TestMeanAndConsistency:
    def test_attribute_mean_excludes_non_submitted(self, api):
        """PRD §3.5: "The session's `overall_mean` is computed as the mean of the `OVERALL` scores across its `SUBMITTED` assignments only — assignments in `ASSIGNED`, `NO_SHOW`, or `EXCUSED` never enter any mean — rounded half-up to 2 decimal places."

        Design: Corner/calculations/attribute_mean_excludes_non_submitted
        """
        # threshold 4.0 so the mean (8.25) cannot trip the sensory endpoint
        env, session, panelists, assignments = _open_session_with_panel(
            api, num_panelists=5, study_overrides={"sensory_fail_threshold": 4.0})
        overalls = [8, 8, 8, 9]
        for i, overall in enumerate(overalls):
            submit_all_scores(assignments[i]["id"], panelists[i]["id"],
                              uniform_score=overall)
        # fifth panelist leaves partial scores: assignment stays ASSIGNED
        fifth_headers = make_panelist_headers(panelists[4]["id"])
        for attribute in ("APPEARANCE", "AROMA", "FLAVOR"):
            get_success_data(api.create_score(
                create_score_payload(assignments[4]["id"], attribute, 1),
                fifth_headers))
        assert get_assignment(assignments[4]["id"])["status"] == "ASSIGNED"

        locked = validate_success(api.lock_session(session["id"], PC))
        assert locked["status"] == "LOCKED"
        assert locked["overall_mean"] == pytest.approx(8.25, abs=0.005), (
            "(8+8+8+9)/4 — the ASSIGNED panelist's partial 1s never enter the mean")
        assert locked["sensory_failed"] is False

    def test_consistency_provisional_at_lock_final_null(self, api):
        """PRD §3.4: "The `consistency_index_provisional` is recomputed whenever a session containing that panelist's scores locks; it considers sessions in `LOCKED` or `ANALYZED` status and measures each scored attribute cell against the plain session cell mean — a reference mean that **includes** the panelist's own score."
        PRD §3.4: "the index itself is 100 minus 20 times the penalty, floored at zero so it never goes negative, and rounded half-up to 2 decimal places"
        PRD §3.4: "Each variant stays null until the panelist has a scored session of the corresponding kind."

        Design: Difficulty/dual_variant_calc/panelist_consistency_provisional_vs_final
        """
        env, session, panelists, assignments = _open_session_with_panel(
            api, num_panelists=4)
        submit_all_scores(assignments[0]["id"], panelists[0]["id"],
                          uniform_score=8)
        for i in (1, 2, 3):
            submit_all_scores(assignments[i]["id"], panelists[i]["id"],
                              uniform_score=6)

        locked = validate_success(api.lock_session(session["id"], PC))
        assert locked["overall_mean"] == pytest.approx(6.5, abs=0.005)

        p1 = get_panelist(panelists[0]["id"])
        # cell reference mean (8+6+6+6)/4 = 6.5; penalty |8-6.5| = 1.5;
        # index = 100 - 20*1.5 = 70.00
        assert p1["consistency_index_provisional"] == pytest.approx(70.0, abs=0.005)
        assert p1["consistency_index_final"] is None, (
            "no ANALYZED session exists yet, so the final variant stays null")

    def test_consistency_final_at_analyze_diverges(self, api):
        """PRD §3.4: "The `consistency_index_final` is recomputed when such a session is analyzed; it considers `ANALYZED` sessions only and measures each cell against a **leave-one-out** panel mean that excludes the panelist's own score."
        PRD §3.4: "Identical raw scores therefore yield different indexes"

        Design: Difficulty/dual_variant_calc/panelist_consistency_provisional_vs_final
        """
        env, session, panelists, assignments = _open_session_with_panel(
            api, num_panelists=4)
        submit_all_scores(assignments[0]["id"], panelists[0]["id"],
                          uniform_score=8)
        for i in (1, 2, 3):
            submit_all_scores(assignments[i]["id"], panelists[i]["id"],
                              uniform_score=6)
        lock_session(session["id"])
        analyzed = analyze_session(session["id"])
        assert analyzed["status"] == "ANALYZED"

        p1 = get_panelist(panelists[0]["id"])
        # leave-one-out mean (6+6+6)/3 = 6.0; penalty 2.0; index 60.00
        assert p1["consistency_index_final"] == pytest.approx(60.0, abs=0.005)
        assert p1["consistency_index_provisional"] == pytest.approx(70.0, abs=0.005)
        assert p1["consistency_index_provisional"] != p1["consistency_index_final"], (
            "the two variants diverge on identical raw scores")


class TestSensoryThresholdBoundary:
    def _threshold_scenario(self, api):
        """IN_PROGRESS study (threshold 6.0, delta 3.0); control session S1
        (10:00-11:00) locked with all OVERALL 10; variant session S2
        (11:00-12:00) OPEN with all OVERALL 6 submitted."""
        env = setup_session_panel(arm_variants=("STANDARD_FILM", "HIGH_BARRIER"),
                                  num_panelists=4,
                                  session_windows=[("2026-08-01T10:00:00Z",
                                                    "2026-08-01T11:00:00Z"),
                                                   ("2026-08-01T11:00:00Z",
                                                    "2026-08-01T12:00:00Z")])
        s1, s2 = env["sessions"]
        panelists = env["panelists"]
        a_s1 = env["assignments"][s1["id"]]
        a_s2 = env["assignments"][s2["id"]]
        set_clock("2026-08-01T10:00:00Z")
        open_session(s1["id"])
        for i, p in enumerate(panelists):
            submit_all_scores(a_s1[i]["id"], p["id"], uniform_score=10)
        locked_s1 = lock_session(s1["id"])
        set_clock("2026-08-01T11:00:00Z")
        open_session(s2["id"])
        for i, p in enumerate(panelists):
            submit_all_scores(a_s2[i]["id"], p["id"], uniform_score=8,
                              overall_score=6)
        return env, locked_s1, s2

    def test_mean_exactly_at_threshold_trips_inclusive_leg(self, api):
        """PRD §3.5: "`sensory_failed` is set to true exactly when the session's `overall_mean` is at or below the study's `sensory_fail_threshold` — the at-or-below comparison is inclusive, so a mean exactly equal to the threshold satisfies that leg — **and** the difference from control is significant; otherwise `sensory_failed` is false."
        PRD §3.5: "When that control session is `LOCKED` or `ANALYZED`, `significance_delta` is computed at full precision as 1.96 times the panel standard deviation of 1.5 times the square root of the sum of the reciprocals of the two sessions' `SUBMITTED` counts"

        Design: Difficulty/boundary_precision_check/sensory_threshold_inclusive_at_or_below
        """
        env, locked_s1, s2 = self._threshold_scenario(api)
        assert locked_s1["overall_mean"] == pytest.approx(10.0, abs=0.005)
        assert locked_s1["sensory_failed"] is False, (
            "the control arm sits above the threshold")

        locked_s2 = validate_success(api.lock_session(s2["id"], PC))
        assert locked_s2["overall_mean"] == pytest.approx(6.0, abs=0.005), (
            "exactly equal to sensory_fail_threshold 6.0: the inclusive "
            "at-or-below leg is satisfied")
        # delta = 1.96 * 1.5 * sqrt(1/4 + 1/4) ~= 2.0785 (full precision in use)
        assert locked_s2["significance_delta"] is not None
        assert locked_s2["significance_delta"] == pytest.approx(2.0785, abs=0.01)
        assert abs(6.0 - 10.0) >= 2.0785, "the difference from control is significant"
        assert locked_s2["sensory_failed"] is True

    def test_threshold_trip_runs_failure_day_cascade(self, api):
        """PRD §3.5: "When the newly evaluated failure moves the arm's earliest endpoint earlier, the failure-day cascade of §3.6 runs: the arm's `computed_failure_day_equiv` is recomputed, the study's `earliest_failure_day_equiv` follows"
        PRD §3.6: "Under `REAL_TIME`, where storage and reference temperatures coincide, the factor is 1 and the equivalent days are simply the observed chronological day as-is."

        Design: Difficulty/boundary_precision_check/sensory_threshold_inclusive_at_or_below
        """
        env, _locked_s1, s2 = self._threshold_scenario(api)
        locked_s2 = validate_success(api.lock_session(s2["id"], PC))
        assert locked_s2["sensory_failed"] is True

        variant_arm = get_success_data(api.get_study_arm(env["arms"][1]["id"], SCI))
        assert variant_arm["computed_failure_day_equiv"] == pytest.approx(0.0, abs=0.0005), (
            "tripped at day_index 0; REAL_TIME factor 1 keeps the day as-is")
        study = get_study(env["study"]["id"])
        assert study["earliest_failure_day_equiv"] == pytest.approx(0.0, abs=0.0005)
