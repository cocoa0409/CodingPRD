"""Panelist pipeline, discipline, and rostering: screening boundaries, training,
deactivation cycling, no-show suspension cascade, scheduling overlap, roster cap."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_arm,
    add_time_point,
    assign_panelist,
    create_client,
    create_draft_study,
    create_panelist_payload,
    create_qualified_panelist,
    create_session,
    get_assignment,
    get_panelist,
    get_success_data,
    open_session,
    pull_units,
    set_clock,
    setup_study_in_progress,
    submit_and_approve,
    validate_error,
    validate_paginated,
    validate_success,
)

LD = TEST_USERS["lab_director_headers"]
SCI = TEST_USERS["scientist_headers"]
PC = TEST_USERS["coordinator_headers"]


class TestPanelistCreation:
    def test_panelist_creation_initial_state_and_email_unique(self, api):
        """PRD §3.4: "A new panelist starts in `APPLIED` with `training_sessions_completed` at 0, `consecutive_no_shows` at 0, `screening_acuity_score` null until screening is recorded, and both consistency indexes null until sessions supply evidence."
        PRD §3.4: "A `PanelCoordinator` registers each candidate with a `full_name`, a unique `email` (duplicates are `ERR_EMAIL_NOT_UNIQUE`), and the `qualified_attributes` the candidate may eventually score"

        Design: Corner/entities/panelist_creation_initial_state_and_email_unique
        """
        set_clock()
        panelist = validate_success(api.create_panelist(
            create_panelist_payload(full_name="New Person",
                                    email="new@lab.example.com",
                                    qualified_attributes=["OVERALL"]), PC), 201)
        assert panelist["status"] == "APPLIED"
        assert panelist["training_sessions_completed"] == 0
        assert panelist["consecutive_no_shows"] == 0
        assert panelist["screening_acuity_score"] is None
        assert panelist["consistency_index_provisional"] is None
        assert panelist["consistency_index_final"] is None

        resp = api.create_panelist(
            create_panelist_payload(full_name="Dupe", email="new@lab.example.com"),
            PC)
        validate_error(resp, ApiErrorId.ERR_EMAIL_NOT_UNIQUE, 409)


class TestScreeningAndTraining:
    def test_panelist_screening_threshold_boundary(self, api):
        """PRD §3.4: "a score of at least 80 — 80 itself qualifies — advances the panelist `APPLIED → TRAINING`, while anything below 80 routes them to `SCREENED_OUT`, a terminal state."
        PRD §3.4: "Recording a screening supplies an `acuity_score` between 0 and 100 inclusive — outside that range is `ERR_INVALID_REQUEST` — and is only legal from `APPLIED` (else `ERR_INVALID_PANELIST_STATE`). The score is stored verbatim as `screening_acuity_score`"

        Design: Corner/state_machines/panelist_screening_threshold_boundary
        """
        p1 = get_success_data(api.create_panelist(
            create_panelist_payload(full_name="Edge Pass"), PC))
        p2 = get_success_data(api.create_panelist(
            create_panelist_payload(full_name="Edge Fail"), PC))

        passed = validate_success(api.record_screening(p1["id"], 80, PC))
        assert passed["status"] == "TRAINING", "80 is the inclusive pass mark"
        assert passed["screening_acuity_score"] == 80

        failed = validate_success(api.record_screening(p2["id"], 79, PC))
        assert failed["status"] == "SCREENED_OUT"
        assert failed["screening_acuity_score"] == 79

        # SCREENED_OUT is terminal: no further screening is legal
        validate_error(api.record_screening(p2["id"], 95, PC),
                       ApiErrorId.ERR_INVALID_PANELIST_STATE, 409)

    def test_panelist_deactivate_reactivate_cycle(self, api):
        """PRD §3.4: "the moment the counter reaches 3 the same request flips the panelist `TRAINING → QUALIFIED`."
        PRD §3.4: "Deactivation moves `QUALIFIED → INACTIVE`. Reactivation branches on the final consistency evidence: when `consistency_index_final` is null or at least 60, the panelist returns `INACTIVE → QUALIFIED` directly"

        Design: Corner/state_machines/panelist_deactivate_reactivate_cycle
        """
        p = get_success_data(api.create_panelist(create_panelist_payload(), PC))
        get_success_data(api.record_screening(p["id"], 90, PC))
        for _ in range(2):
            get_success_data(api.record_training(p["id"], PC))
        third = validate_success(api.record_training(p["id"], PC))
        assert third["status"] == "QUALIFIED", "the third training flips to QUALIFIED"
        assert third["training_sessions_completed"] == 3

        inactive = validate_success(api.deactivate_panelist(p["id"], PC))
        assert inactive["status"] == "INACTIVE"

        # consistency_index_final is null -> direct (non-remedial) branch
        revived = validate_success(api.reactivate_panelist(p["id"], PC))
        assert revived["status"] == "QUALIFIED"
        assert revived["training_sessions_completed"] == 3, (
            "the non-remedial branch keeps the training counter")


class TestAssignmentGates:
    def test_no_show_requires_open_session(self, api):
        """PRD §3.5: "A `PanelCoordinator` may mark an assignment no-show only while it is `ASSIGNED` (else `ERR_INVALID_ASSIGNMENT_STATE`) and only while its session is `OPEN` (else `ERR_INVALID_SESSION_STATE`)"

        Design: Corner/state_machines/no_show_requires_open_session
        """
        env = setup_study_in_progress(with_chamber=False)
        # session planned while the study is IN_PROGRESS, but never opened
        session = create_session(env["study"]["id"], env["time_points"][0]["id"],
                                 env["arms"][0]["id"],
                                 "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        panelist = create_qualified_panelist()
        assignment = assign_panelist(session["id"], panelist["id"])

        # session is PLANNED (never opened): the session gate fires
        validate_error(api.mark_no_show(assignment["id"], PC),
                       ApiErrorId.ERR_INVALID_SESSION_STATE, 409)
        assert get_assignment(assignment["id"])["status"] == "ASSIGNED"
        assert get_panelist(panelist["id"])["consecutive_no_shows"] == 0

    def test_assignment_double_excuse_rejected(self, api):
        """PRD §3.5: "Excusing an assignment, by contrast, moves `ASSIGNED → EXCUSED` without penalty"
        PRD §2.6: "The target resource's state must permit the requested transition, else the applicable one of `ERR_INVALID_STUDY_STATE`, `ERR_INVALID_SESSION_STATE`, `ERR_INVALID_TIME_POINT_STATE`, `ERR_INVALID_PANELIST_STATE`, `ERR_INVALID_ASSIGNMENT_STATE`"

        Design: Corner/validations/assignment_double_excuse_rejected
        """
        env = setup_study_in_progress(with_chamber=False)
        session = create_session(env["study"]["id"], env["time_points"][0]["id"],
                                 env["arms"][0]["id"],
                                 "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        panelist = create_qualified_panelist()
        assignment = assign_panelist(session["id"], panelist["id"])

        excused = validate_success(api.excuse_assignment(assignment["id"], PC))
        assert excused["status"] == "EXCUSED"

        validate_error(api.excuse_assignment(assignment["id"], PC),
                       ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE, 409)
        assert get_assignment(assignment["id"])["status"] == "EXCUSED"

    def test_assignment_requires_qualified_panelist(self, api):
        """PRD §3.5: "Creating a **panel assignment** for a `session_id` and `panelist_id` requires the session to be `PLANNED` or `OPEN` (else `ERR_INVALID_SESSION_STATE`) and the panelist to be `QUALIFIED` (else `ERR_PANELIST_NOT_QUALIFIED`)."

        Design: Corner/validations/assignment_requires_qualified_panelist
        """
        client = create_client()
        study = create_draft_study(client["id"])
        arm = add_arm(study["id"], "STANDARD_FILM", is_control=True)
        tp0 = add_time_point(study["id"], 0)
        submit_and_approve(study["id"])
        session = create_session(study["id"], tp0["id"], arm["id"],
                                 "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        applied = get_success_data(
            api.create_panelist(create_panelist_payload(), PC))

        resp = api.create_assignment(
            {"session_id": session["id"], "panelist_id": applied["id"]}, PC)
        validate_error(resp, ApiErrorId.ERR_PANELIST_NOT_QUALIFIED, 409)
        _rows, meta = validate_paginated(
            api.list_assignments(PC, params={"session_id": session["id"]}))
        assert meta["total_count"] == 0

    def test_session_full_overbook_cap(self, api):
        """PRD §3.5: "the session's active count — assignments in `ASSIGNED` plus those in `SUBMITTED` — must be below `required_panelist_count` plus 2, so a count that already equals that ceiling is rejected with `ERR_SESSION_FULL`."
        PRD §3.5: "when the study has no `ANALYZED` session yet, the variance defaults to 2.25"

        Design: Corner/validations/session_full_overbook_cap
        """
        client = create_client()
        study = create_draft_study(client["id"])
        arm = add_arm(study["id"], "STANDARD_FILM", is_control=True)
        tp0 = add_time_point(study["id"], 0)
        submit_and_approve(study["id"])
        session = create_session(study["id"], tp0["id"], arm["id"],
                                 "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        # default variance 2.25, delta 3.0 -> required_panelist_count 4,
        # so the roster ceiling is 4 + 2 = 6
        assert session["required_panelist_count"] == 4

        panelists = [create_qualified_panelist() for _ in range(7)]
        for p in panelists[:6]:
            assign_panelist(session["id"], p["id"])
        resp = api.create_assignment(
            {"session_id": session["id"], "panelist_id": panelists[6]["id"]}, PC)
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL, 409)
        _rows, meta = validate_paginated(
            api.list_assignments(PC, params={"session_id": session["id"]}))
        assert meta["total_count"] == 6, "the roster stays at the ceiling"


class TestHalfOpenAdjacency:
    def _overlap_scenario(self, api):
        """SCHEDULED study; S1 (tp0, ctrl, 10:00-11:00), S2 (tp0, var,
        11:00-12:00), S3 (tp1, ctrl, 10:30-11:30) on 2026-08-02; one QUALIFIED
        panelist."""
        set_clock()
        client = create_client()
        study = create_draft_study(client["id"])
        arm_c = add_arm(study["id"], "STANDARD_FILM", is_control=True)
        arm_v = add_arm(study["id"], "MAP", is_control=False)
        tp0 = add_time_point(study["id"], 0)
        tp1 = add_time_point(study["id"], 1)
        submit_and_approve(study["id"])
        s1 = create_session(study["id"], tp0["id"], arm_c["id"],
                            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        s2 = create_session(study["id"], tp0["id"], arm_v["id"],
                            "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z")
        s3 = create_session(study["id"], tp1["id"], arm_c["id"],
                            "2026-08-02T10:30:00Z", "2026-08-02T11:30:00Z")
        panelist = create_qualified_panelist(qualified_attributes=["OVERALL"])
        return s1, s2, s3, panelist

    def test_back_to_back_sessions_permitted(self, api):
        """PRD §3.5: "Scheduling conflicts are judged on half-open window intersection: the panelist must not already hold an assignment in `ASSIGNED` or `SUBMITTED` on another session whose window strictly intersects the new one, while back-to-back sessions — one ending exactly when the other begins — are permitted; violations are `ERR_PANELIST_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/panelist_half_open_adjacency
        """
        s1, s2, _s3, panelist = self._overlap_scenario(api)
        a1 = assign_panelist(s1["id"], panelist["id"])
        a2 = assign_panelist(s2["id"], panelist["id"])
        assert a1["status"] == "ASSIGNED"
        assert a2["status"] == "ASSIGNED", (
            "[11:00,12:00) after [10:00,11:00) touches but does not intersect")

    def test_strictly_intersecting_session_rejected(self, api):
        """PRD §3.5: "Scheduling conflicts are judged on half-open window intersection: the panelist must not already hold an assignment in `ASSIGNED` or `SUBMITTED` on another session whose window strictly intersects the new one, while back-to-back sessions — one ending exactly when the other begins — are permitted; violations are `ERR_PANELIST_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/panelist_half_open_adjacency
        """
        s1, s2, s3, panelist = self._overlap_scenario(api)
        assign_panelist(s1["id"], panelist["id"])
        assign_panelist(s2["id"], panelist["id"])
        resp = api.create_assignment(
            {"session_id": s3["id"], "panelist_id": panelist["id"]}, PC)
        validate_error(resp, ApiErrorId.ERR_PANELIST_DOUBLE_BOOKED, 409)
        _rows, meta = validate_paginated(
            api.list_assignments(PC, params={"session_id": s3["id"]}))
        assert meta["total_count"] == 0


class TestNoShowSuspensionCascade:
    def _suspension_setup(self, api):
        """IN_PROGRESS study (arms ctrl+HIGH_BARRIER, tps day 0/1); four
        back-to-back sessions on 2026-08-02; one QUALIFIED panelist assigned to
        all four; first two no-shows already recorded (counter == 2)."""
        env = setup_study_in_progress(
            arm_variants=("STANDARD_FILM", "HIGH_BARRIER"),
            day_indexes=(0, 1), chamber_capacity=10)
        study_id = env["study"]["id"]
        tp0, tp1 = env["time_points"]
        arm_c, arm_v = env["arms"]
        chamber = env["chamber"]
        s1 = create_session(study_id, tp0["id"], arm_c["id"],
                            "2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z")
        s2 = create_session(study_id, tp0["id"], arm_v["id"],
                            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        s3 = create_session(study_id, tp1["id"], arm_c["id"],
                            "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z")
        s4 = create_session(study_id, tp1["id"], arm_v["id"],
                            "2026-08-02T12:00:00Z", "2026-08-02T13:00:00Z")
        pull_units(tp0["id"], chamber["id"], arm_c["id"], quantity=1)
        pull_units(tp0["id"], chamber["id"], arm_v["id"], quantity=1)
        p = create_qualified_panelist()
        a1 = assign_panelist(s1["id"], p["id"])
        a2 = assign_panelist(s2["id"], p["id"])
        a3 = assign_panelist(s3["id"], p["id"])
        a4 = assign_panelist(s4["id"], p["id"])
        # day 1: pull the day-1 time point's units, then run the first no-shows
        set_clock("2026-08-02T00:00:00Z")
        pull_units(tp1["id"], chamber["id"], arm_c["id"], quantity=1)
        pull_units(tp1["id"], chamber["id"], arm_v["id"], quantity=1)
        set_clock("2026-08-02T09:00:00Z")
        open_session(s1["id"])
        get_success_data(api.mark_no_show(a1["id"], PC))
        set_clock("2026-08-02T10:00:00Z")
        open_session(s2["id"])
        get_success_data(api.mark_no_show(a2["id"], PC))
        set_clock("2026-08-02T11:00:00Z")
        open_session(s3["id"])
        return {"panelist": p, "a1": a1, "a2": a2, "a3": a3, "a4": a4}

    def test_third_no_show_suspends_qualified_panelist(self, api):
        """PRD §3.5: "the mark moves it `ASSIGNED → NO_SHOW`, increments the panelist's `consecutive_no_shows` by 1, and — when the counter thereby reaches at least 3 and the panelist is `QUALIFIED` — fires the suspension cascade of §3.4."
        PRD §3.4: "When a panelist's `consecutive_no_shows` reaches 3 — driven by the no-show marking of §3.5 — a panelist in `QUALIFIED` is suspended by the system, moving `QUALIFIED → SUSPENDED`"

        Design: Difficulty/transitive_cascade/no_show_suspension_excuses_future_assignments
        """
        env = self._suspension_setup(api)
        third = validate_success(api.mark_no_show(env["a3"]["id"], PC))
        assert third["status"] == "NO_SHOW"
        for key in ("a1", "a2"):
            assert get_assignment(env[key]["id"])["status"] == "NO_SHOW"

        panelist = get_panelist(env["panelist"]["id"])
        assert panelist["consecutive_no_shows"] == 3
        assert panelist["status"] == "SUSPENDED", (
            "auto-transition fires at the third consecutive no-show")

    def test_suspension_excuses_future_assigned_work(self, api):
        """PRD §3.4: "every other assignment that panelist holds in `ASSIGNED` on a session in `PLANNED` or `OPEN` is excused in the same stroke."

        Design: Difficulty/transitive_cascade/no_show_suspension_excuses_future_assignments
        """
        env = self._suspension_setup(api)
        assert get_assignment(env["a4"]["id"])["status"] == "ASSIGNED", (
            "precondition: the future assignment is still ASSIGNED pre-trigger")
        get_success_data(api.mark_no_show(env["a3"]["id"], PC))
        assert get_assignment(env["a4"]["id"])["status"] == "EXCUSED", (
            "cascade hop: the PLANNED-session assignment is excused in the "
            "same stroke as the suspension")
