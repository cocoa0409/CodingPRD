"""Exam day and score processing: attendance split, irregularity filing and
its divergent resolve/cancel-scores paths, transactional bulk release gates,
credit-threshold posting, and the independent parallel state dimensions
(PRD §3.6, §3.7).
"""
from test_helpers import (
    COORD,
    REGISTRAR,
    SCORE_RELEASE_AT,
    ApiErrorId,
    administer_session,
    cancel_scores_report,
    file_irregularity,
    get_registration,
    get_report,
    get_session,
    get_statement,
    make_active_course,
    make_open_cycle,
    make_proctor_assignment,
    make_registration,
    make_session,
    make_student,
    make_teacher,
    make_student_headers,
    post_to_transcript,
    release_scores,
    resolve_report,
    set_clock,
    setup_released_registrations,
    setup_sat_scenario,
    setup_under_investigation,
    validate_error,
    validate_success,
)


class TestAdminister:
    def test_administer_splits_present_from_absent(self, api):
        """PRD §3.6: "Administration then splits the course's roster in two:
        each listed registration moves from `REGISTERED` to `SAT` with its
        `score_status` staying `PENDING`, while every `REGISTERED` registration
        of the course not in the list moves to `NO_SHOW` and its `score_status`
        moves to `NO_SCORE`."
        PRD §3.6: "The session itself transitions from `SCHEDULED` to
        `ADMINISTERED`, and its `seats_reserved` recomputes to 0, since no
        `REGISTERED` registrations remain for the course."

        Design: Corner/state_machines/administer_marks_absentees_no_show
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"])
        s1 = make_student(full_name="Stu A")
        s2 = make_student(full_name="Stu B")
        reg_1 = make_registration(s1["id"], course["id"])
        reg_2 = make_registration(s2["id"], course["id"])
        session = make_session(course["id"])
        set_clock("2027-05-05T12:00:00Z")
        administered = administer_session(session["id"], [reg_1["id"]])
        assert administered["status"] == "ADMINISTERED"
        assert administered["seats_reserved"] == 0
        present = get_registration(reg_1["id"])
        assert present["registration_status"] == "SAT"
        assert present["score_status"] == "PENDING"
        absent = get_registration(reg_2["id"])
        assert absent["registration_status"] == "NO_SHOW"
        assert absent["score_status"] == "NO_SCORE"

    def test_administer_before_session_end_rejected(self, api):
        """PRD §3.6: "Administering a session requires the logical clock to be
        at or after the session's `end_at` — administering earlier is rejected
        with `ERR_SESSION_NOT_ENDED` — and requires the session to be in
        `SCHEDULED` status."

        Design: Corner/validations/administer_before_session_end_rejected
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"])
        student = make_student()
        registration = make_registration(student["id"], course["id"])
        session = make_session(course["id"])
        # The clock reads 10:00, mid-sitting (session ends 11:00).
        set_clock("2027-05-05T10:00:00Z")
        res = api.administer_exam_session(
            session["id"], {"present_registration_ids": [registration["id"]]},
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_SESSION_NOT_ENDED, 422)
        # No attendance was recorded.
        assert get_registration(registration["id"])["registration_status"] == (
            "REGISTERED"
        )


class TestIrregularityPaths:
    def test_resolve_restores_administered_and_unblocks_release(self, api):
        """PRD §3.6: "When the resolved report was the session's last remaining
        `FILED` report, the session moves back from `UNDER_INVESTIGATION` to
        `ADMINISTERED` and the course's `HELD` score records return to
        `PENDING`, unblocking release"

        Design: Corner/state_machines/irregularity_resolve_restores_administered_and_unblocks_scores
        """
        scenario = setup_under_investigation(
            category="MATERIALS", details="Defective booklet replaced"
        )
        registration = scenario["registrations"][0]
        report = scenario["report"]
        assert get_registration(registration["id"])["score_status"] == "HELD"
        resolved = resolve_report(report["id"])
        assert resolved["status"] == "RESOLVED"
        assert get_session(scenario["session"]["id"])["status"] == "ADMINISTERED"
        assert get_registration(registration["id"])["score_status"] == "PENDING"
        # Release is unblocked once the record returns to PENDING.
        set_clock(SCORE_RELEASE_AT)
        release = release_scores(
            scenario["cycle"]["id"],
            [{"registration_id": registration["id"], "score": 4}],
        )
        assert release["released_count"] == 1
        assert release["released_registration_ids"] == [registration["id"]]
        assert get_registration(registration["id"])["score_status"] == "RELEASED"

    def test_cancel_scores_invalidates_session_and_voids_records(self, api):
        """PRD §3.6: "Cancelling scores is the severe path: the report moves
        from `FILED` to `SCORES_CANCELLED`, its terminal state, the session —
        whether `ADMINISTERED` or `UNDER_INVESTIGATION` — moves to
        `INVALIDATED`, its terminal state, and every `SAT` registration of the
        course whose `score_status` is `PENDING` or `HELD` moves to `VOID`,
        meaning those records can never be released or posted."
        PRD §2.8: "a record in any other non-`PENDING` state rejects the whole
        request with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/irregularity_cancel_scores_invalidates_session_and_voids_records
        """
        scenario = setup_under_investigation(
            category="SECURITY_BREACH", details="Phone observed in use"
        )
        registration = scenario["registrations"][0]
        report = scenario["report"]
        cancelled = cancel_scores_report(report["id"])
        assert cancelled["status"] == "SCORES_CANCELLED"
        assert get_session(scenario["session"]["id"])["status"] == "INVALIDATED"
        voided = get_registration(registration["id"])
        assert voided["score_status"] == "VOID"
        # A VOID record rejects a later release listing it.
        set_clock(SCORE_RELEASE_AT)
        res = api.release_scores(
            scenario["cycle"]["id"],
            {"scores": [{"registration_id": registration["id"], "score": 4}]},
            REGISTRAR,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_release_blocked_by_open_irregularity_is_transactional(self, api):
        """PRD §2.8: "When releasing scores, every listed record must currently
        be `PENDING`: a `HELD` record rejects the whole request with
        `ERR_IRREGULARITY_OPEN` (HTTP 409) ... The release is transactional —
        on rejection nothing is written."
        PRD §3.6: "The first report on an administered session moves it from
        `ADMINISTERED` to `UNDER_INVESTIGATION`"

        Design: Difficulty/cross_entity_state_dependency/score_release_blocked_by_open_irregularity
        """
        scenario = setup_under_investigation()
        registration = scenario["registrations"][0]
        # Filing cascade landed before the release attempt.
        assert get_report(scenario["report"]["id"])["status"] == "FILED"
        assert get_session(scenario["session"]["id"])["status"] == (
            "UNDER_INVESTIGATION"
        )
        set_clock(SCORE_RELEASE_AT)
        res = api.release_scores(
            scenario["cycle"]["id"],
            {"scores": [{"registration_id": registration["id"], "score": 4}]},
            REGISTRAR,
        )
        validate_error(res, ApiErrorId.ERR_IRREGULARITY_OPEN, 409)
        # Transactional: the HELD record kept its state and null score.
        held = get_registration(registration["id"])
        assert held["score_status"] == "HELD"
        assert held["score"] is None

    def test_held_record_blocks_co_listed_clean_record(self, api):
        """PRD §2.8: "if any listed record's `score_status` is `HELD`, the
        entire request is rejected with `ERR_IRREGULARITY_OPEN`" — quoted rule
        restated at §3.7; "on any such rejection nothing at all is written."

        Design: Difficulty/cross_entity_state_dependency/score_release_blocked_by_open_irregularity
        """
        # Two independent courses, each administered; only course B's session
        # draws an irregularity, so r_a stays PENDING while r_b is HELD.
        cycle = make_open_cycle()
        course_a, _, _ = make_active_course(
            cycle["id"], subject_code="AP_CALC_BC"
        )
        course_b, _, _ = make_active_course(
            cycle["id"], subject_code="AP_BIOLOGY"
        )
        student_a = make_student(full_name="Stu A")
        student_b = make_student(full_name="Stu B")
        reg_a = make_registration(student_a["id"], course_a["id"])
        reg_b = make_registration(student_b["id"], course_b["id"])
        session_a = make_session(course_a["id"], room_name="ROOMA")
        session_b = make_session(course_b["id"], room_name="ROOMB")
        proctor = make_teacher(full_name="T Proctor", email="proc@x.edu")
        make_proctor_assignment(session_b["id"], proctor["id"])
        set_clock("2027-05-05T12:00:00Z")
        administer_session(session_a["id"], [reg_a["id"]])
        administer_session(session_b["id"], [reg_b["id"]])
        file_irregularity(
            session_b["id"], proctor["id"], category="TIMING_ERROR"
        )
        assert get_registration(reg_a["id"])["score_status"] == "PENDING"
        assert get_registration(reg_b["id"])["score_status"] == "HELD"
        set_clock(SCORE_RELEASE_AT)
        res = api.release_scores(
            cycle["id"],
            {
                "scores": [
                    {"registration_id": reg_a["id"], "score": 4},
                    {"registration_id": reg_b["id"], "score": 5},
                ]
            },
            REGISTRAR,
        )
        validate_error(res, ApiErrorId.ERR_IRREGULARITY_OPEN, 409)
        # Nothing written: the clean co-listed record was not released either.
        assert get_registration(reg_a["id"])["score_status"] == "PENDING"
        assert get_registration(reg_a["id"])["score"] is None


class TestScoreReleaseGates:
    def test_release_before_score_release_date_rejected(self, api):
        """PRD §3.7: "Timing: the logical clock must be at or after the
        cycle's `score_release_at`, otherwise the release is rejected with
        `ERR_SCORES_NOT_YET_AVAILABLE`."

        Design: Corner/validations/release_before_score_release_date_rejected
        """
        scenario = setup_sat_scenario(num_students=1, present=1)
        registration = scenario["registrations"][0]
        # Clock is still 2027-05-05, weeks before the 2027-07-05 release date.
        res = api.release_scores(
            scenario["cycle"]["id"],
            {"scores": [{"registration_id": registration["id"], "score": 4}]},
            REGISTRAR,
        )
        validate_error(res, ApiErrorId.ERR_SCORES_NOT_YET_AVAILABLE, 422)

    def test_release_rejects_out_of_program_range_score(self, api):
        """PRD §3.7: "Shape: each supplied score must lie within the course's
        program range — 1 through 5 for AP, 1 through 7 for IB — otherwise
        `ERR_INVALID_REQUEST`."
        PRD §3.7: "and on any such rejection nothing at all is written."

        Design: Corner/endpoints/release_scores_rejects_out_of_range_score
        """
        scenario = setup_sat_scenario(num_students=2, present=2)
        reg_1, reg_2 = scenario["registrations"]
        set_clock(SCORE_RELEASE_AT)
        # Score 6 is outside the AP range 1..5 (course is AP_CALC_BC).
        res = api.release_scores(
            scenario["cycle"]["id"],
            {
                "scores": [
                    {"registration_id": reg_1["id"], "score": 4},
                    {"registration_id": reg_2["id"], "score": 6},
                ]
            },
            REGISTRAR,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)
        # The valid co-listed row is not released either.
        pending = get_registration(reg_1["id"])
        assert pending["score_status"] == "PENDING"
        assert pending["score"] is None


class TestTranscriptPosting:
    def test_posted_score_cannot_be_reposted(self, api):
        """PRD §3.7: "Posting a released score to the student's transcript
        moves the record's `score_status` from `RELEASED` to `POSTED`, its
        terminal state, and increments the student's `transcript_posted_count`
        by 1."
        PRD §2.8: "The target entity is in a valid from-state for the requested
        transition"

        Design: Corner/state_machines/posted_score_cannot_be_reposted
        """
        scenario = setup_released_registrations({0: 4})
        registration = scenario["registrations"][0]
        student = scenario["students"][0]
        posted = post_to_transcript(registration["id"])
        assert posted["score_status"] == "POSTED"
        assert get_statement(student["id"])["transcript_posted_count"] == 1
        res = api.post_to_transcript(registration["id"], REGISTRAR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
        # No double increment.
        assert get_statement(student["id"])["transcript_posted_count"] == 1

    def test_score_threshold_exact_equality_posts(self, api):
        """PRD §3.7: "The gate is the course's credit threshold: the `score`
        must be greater than or equal to the course's `credit_threshold` —
        equality posts — otherwise the post is rejected with
        `ERR_SCORE_BELOW_THRESHOLD`."

        Design: Corner/calculations/score_threshold_exact_equality_posts
        """
        # IB course: credit threshold 4 on the 1..7 IB scale.
        scenario = setup_released_registrations(
            {0: 4, 1: 3},
            num_students=2,
            present=2,
            course_overrides={
                "subject_code": "IB_HIST_HL",
                "program": "IB",
                "exam_fee_cents": 11900,
                "credit_threshold": 4,
            },
        )
        reg_1, reg_2 = scenario["registrations"]
        student_1 = scenario["students"][0]
        # Score 4 == threshold 4: equality posts.
        posted = post_to_transcript(reg_1["id"])
        assert posted["score_status"] == "POSTED"
        assert get_statement(student_1["id"])["transcript_posted_count"] == 1
        # Score 3 < 4: rejected, and the record stays RELEASED.
        res = api.post_to_transcript(reg_2["id"], REGISTRAR)
        validate_error(res, ApiErrorId.ERR_SCORE_BELOW_THRESHOLD, 422)
        assert get_registration(reg_2["id"])["score_status"] == "RELEASED"


class TestParallelDimensions:
    def test_registration_and_score_dimensions_evolve_independently(self, api):
        """PRD §3.3: "These two state dimensions evolve independently from here
        on: attendance moves `registration_status`, while score processing
        moves `score_status`, and each dimension gates the other only where
        stated."
        PRD §3.7: "A successful release moves each listed record from
        `PENDING` to `RELEASED`, stores the supplied value as the record's
        `score`, and responds with the `released_count` and the
        `released_registration_ids`."

        Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions_independent
        """
        scenario = setup_sat_scenario(num_students=2, present=1)
        reg_1, reg_2 = scenario["registrations"]
        # After administration: SAT x PENDING vs NO_SHOW x NO_SCORE.
        assert reg_1["registration_status"] == "SAT"
        assert reg_1["score_status"] == "PENDING"
        assert reg_2["registration_status"] == "NO_SHOW"
        assert reg_2["score_status"] == "NO_SCORE"
        # Score processing advances r1's score dimension only.
        set_clock(SCORE_RELEASE_AT)
        release = release_scores(
            scenario["cycle"]["id"],
            [{"registration_id": reg_1["id"], "score": 4}],
        )
        assert release["released_count"] == 1
        post_to_transcript(reg_1["id"])
        final_1 = get_registration(reg_1["id"])
        assert final_1["registration_status"] == "SAT"
        assert final_1["score_status"] == "POSTED"
        assert final_1["score"] == 4
        # r2 is untouched by r1's release and posting.
        final_2 = get_registration(reg_2["id"])
        assert final_2["registration_status"] == "NO_SHOW"
        assert final_2["score_status"] == "NO_SCORE"
        assert final_2["score"] is None

    def test_cancel_jumps_both_dimensions_to_terminal(self, api):
        """PRD §3.3: "cancellation moves it to `CANCELLED`, a terminal state,
        and moves the parallel `score_status` to `VOID`."
        PRD §3.3: "These two state dimensions evolve independently from here
        on: attendance moves `registration_status`, while score processing
        moves `score_status`, and each dimension gates the other only where
        stated."

        Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions_independent
        """
        scenario_cycle = make_open_cycle()
        course, _, _ = make_active_course(scenario_cycle["id"])
        student = make_student()
        registration = make_registration(student["id"], course["id"])
        assert registration["registration_status"] == "REGISTERED"
        assert registration["score_status"] == "PENDING"
        # The attendance dimension never left REGISTERED, yet cancellation
        # drives the score dimension straight to its VOID terminal state.
        cancelled = validate_success(
            api.cancel_registration(
                registration["id"], make_student_headers(student["id"])
            ),
            200,
        )
        assert cancelled["registration_status"] == "CANCELLED"
        assert cancelled["score_status"] == "VOID"
