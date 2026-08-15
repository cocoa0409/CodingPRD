"""Entrance evaluations, test sessions, committee scoring (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_evaluation_payload,
    get_application,
    get_evaluation,
    get_session,
    make_applicant,
    make_application,
    make_open_world,
    make_parent_headers,
    make_student,
    schedule_interview,
    schedule_test,
    score_evaluation,
    setup_decision_world,
    setup_scored_application,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
)


def _submitted_app(world, family, first_name="Ann", legacy=False):
    applicant = make_applicant(family, first_name=first_name,
                               legacy_parent=legacy)
    application = make_application(applicant["id"], world["cycle"]["id"],
                                   world["section"]["id"], family, "EARLY")
    submit_application(application["id"], family)
    return application


class TestEvaluationGateOnApplication:
    """Difficulty: evaluation creation is gated on the referenced
    application's state — DRAFT rejects, SUBMITTED admits."""

    def test_evaluation_blocked_while_application_draft(self, api,
                                                        officer_headers):
        """PRD §3.3: "The target application must be `SUBMITTED` or
        `EVALUATION_COMPLETE`; one that has not reached the submission gate is
        rejected with `ERR_APPLICATION_NOT_SUBMITTED`, and one in a terminal
        state with `ERR_APPLICATION_TERMINAL`."

        Design: Difficulty/cross_entity_state_dependency/evaluation_blocked_until_application_submitted
        """
        world = make_open_world()
        applicant = make_applicant("fam-a")
        application = make_application(applicant["id"], world["cycle"]["id"],
                                       world["section"]["id"], "fam-a", "EARLY")
        resp = api.create_evaluation(
            create_evaluation_payload(
                application["id"], "TEST",
                test_session_id=world["session"]["id"],
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED, 409)

    def test_evaluation_admitted_once_application_submitted(self, api,
                                                            officer_headers):
        """PRD §3.3: "The target application must be `SUBMITTED` or
        `EVALUATION_COMPLETE`; one that has not reached the submission gate is
        rejected with `ERR_APPLICATION_NOT_SUBMITTED`".
        PRD §3.3: "A successfully scheduled evaluation starts in `SCHEDULED`
        and, for tests, adds one to the session's `booked_count`."

        Design: Difficulty/cross_entity_state_dependency/evaluation_blocked_until_application_submitted
        """
        ctx = setup_submitted_application("fam-a")
        resp = api.create_evaluation(
            create_evaluation_payload(
                ctx["application"]["id"], "TEST",
                test_session_id=ctx["session"]["id"],
            ),
            officer_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "SCHEDULED"


class TestInterviewerCalendar:
    """Difficulty: half-open interval semantics on the interviewer resource —
    adjacency is allowed, partial overlap is rejected."""

    def test_adjacent_interviews_allowed(self, api, officer_headers):
        """PRD §3.3: "For interviews, the new window must not overlap — under
        half-open interval semantics, where one window ending exactly when
        another begins is allowed — any other non-cancelled interview booked
        for the same `interviewer_id`; a conflict is
        `ERR_INTERVIEWER_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/interviewer_half_open_overlap_rules
        """
        world = make_open_world()
        app_a = _submitted_app(world, "fam-a", "Ann")
        app_b = _submitted_app(world, "fam-b", "Ben")
        resp_a = api.create_evaluation(
            create_evaluation_payload(
                app_a["id"], "INTERVIEW",
                scheduled_start="2026-10-12T10:00:00Z",
                scheduled_end="2026-10-12T11:00:00Z", interviewer_id="int-7",
            ),
            officer_headers,
        )
        validate_success(resp_a, 201)
        # [11:00,12:00) touches [10:00,11:00) at one instant: not an overlap.
        resp_b = api.create_evaluation(
            create_evaluation_payload(
                app_b["id"], "INTERVIEW",
                scheduled_start="2026-10-12T11:00:00Z",
                scheduled_end="2026-10-12T12:00:00Z", interviewer_id="int-7",
            ),
            officer_headers,
        )
        validate_success(resp_b, 201)

    def test_partial_overlap_rejected_but_other_interviewer_allowed(
            self, api, officer_headers):
        """PRD §3.3: "For interviews, the new window must not overlap — under
        half-open interval semantics, where one window ending exactly when
        another begins is allowed — any other non-cancelled interview booked
        for the same `interviewer_id`; a conflict is
        `ERR_INTERVIEWER_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/interviewer_half_open_overlap_rules
        """
        world = make_open_world()
        app_a = _submitted_app(world, "fam-a", "Ann")
        app_c = _submitted_app(world, "fam-c", "Cat")
        schedule_interview(app_a["id"], "int-7",
                           ("2026-10-12T10:00:00Z", "2026-10-12T11:00:00Z"))
        # [10:30,11:30) intersects [10:00,11:00) for the same interviewer.
        resp = api.create_evaluation(
            create_evaluation_payload(
                app_c["id"], "INTERVIEW",
                scheduled_start="2026-10-12T10:30:00Z",
                scheduled_end="2026-10-12T11:30:00Z", interviewer_id="int-7",
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEWER_SCHEDULE_CONFLICT, 409)
        # The resource is the interviewer, not the clock window: a different
        # interviewer accepts the same window.
        resp = api.create_evaluation(
            create_evaluation_payload(
                app_c["id"], "INTERVIEW",
                scheduled_start="2026-10-12T10:30:00Z",
                scheduled_end="2026-10-12T11:30:00Z", interviewer_id="int-8",
            ),
            officer_headers,
        )
        validate_success(resp, 201)


class TestSessionAggregateCapacity:
    """Difficulty (aggregate semantics): only the non-cancelled TEST count
    matters; fully overlapping windows are fine until the room is full."""

    def test_fully_overlapping_test_bookings_accepted(self, api,
                                                      officer_headers):
        """PRD §3.3: "For tests, the session's capacity is an aggregate
        headcount: the session is full when it already holds `room_capacity`
        non-cancelled `TEST` evaluations, regardless of how their individual
        windows overlap in time, and booking into a full session is
        `ERR_TEST_SESSION_FULL`."

        Design: Difficulty/resource_temporal_overlap/test_session_aggregate_capacity_overlap
        """
        world = make_open_world(session_capacity=2)
        app_a = _submitted_app(world, "fam-a", "Ann")
        app_b = _submitted_app(world, "fam-b", "Ben")
        for application in (app_a, app_b):
            resp = api.create_evaluation(
                create_evaluation_payload(
                    application["id"], "TEST",
                    scheduled_start="2026-10-10T09:00:00Z",
                    scheduled_end="2026-10-10T10:00:00Z",
                    test_session_id=world["session"]["id"],
                ),
                officer_headers,
            )
            validate_success(resp, 201)
        assert get_session(world["session"]["id"])["booked_count"] == 2

    def test_third_booking_rejected_despite_free_window(self, api,
                                                        officer_headers):
        """PRD §3.3: "the session is full when it already holds
        `room_capacity` non-cancelled `TEST` evaluations, regardless of how
        their individual windows overlap in time, and booking into a full
        session is `ERR_TEST_SESSION_FULL`."

        Design: Difficulty/resource_temporal_overlap/test_session_aggregate_capacity_overlap
        """
        world = make_open_world(session_capacity=2)
        app_a = _submitted_app(world, "fam-a", "Ann")
        app_b = _submitted_app(world, "fam-b", "Ben")
        app_c = _submitted_app(world, "fam-c", "Cat")
        for application in (app_a, app_b):
            schedule_test(application["id"], world["session"]["id"])
        # 10:00-11:00 overlaps nothing pairwise-blocked; only the count rules.
        resp = api.create_evaluation(
            create_evaluation_payload(
                app_c["id"], "TEST",
                scheduled_start="2026-10-10T10:00:00Z",
                scheduled_end="2026-10-10T11:00:00Z",
                test_session_id=world["session"]["id"],
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_SESSION_FULL, 409)
        assert get_session(world["session"]["id"])["booked_count"] == 2


class TestSessionCapacityBoundary:
    """Difficulty (count boundary): booked == room_capacity is the last legal
    state; one more booking is rejected."""

    def test_booking_up_to_exact_capacity_succeeds(self, api, officer_headers):
        """PRD §3.3: "the session is full when it already holds
        `room_capacity` non-cancelled `TEST` evaluations".

        Design: Difficulty/boundary_precision_check/test_session_capacity_exact_then_full
        """
        world = make_open_world(session_capacity=2)
        app_a = _submitted_app(world, "fam-a", "Ann")
        app_b = _submitted_app(world, "fam-b", "Ben")
        resp_a = api.create_evaluation(
            create_evaluation_payload(
                app_a["id"], "TEST",
                scheduled_start="2026-10-10T09:00:00Z",
                scheduled_end="2026-10-10T10:00:00Z",
                test_session_id=world["session"]["id"],
            ),
            officer_headers,
        )
        validate_success(resp_a, 201)
        resp_b = api.create_evaluation(
            create_evaluation_payload(
                app_b["id"], "TEST",
                scheduled_start="2026-10-10T10:00:00Z",
                scheduled_end="2026-10-10T11:00:00Z",
                test_session_id=world["session"]["id"],
            ),
            officer_headers,
        )
        validate_success(resp_b, 201)  # booked_count reaches exactly 2
        assert get_session(world["session"]["id"])["booked_count"] == 2

    def test_booking_past_capacity_rejected(self, api, officer_headers):
        """PRD §3.3: "booking into a full session is `ERR_TEST_SESSION_FULL`."

        Design: Difficulty/boundary_precision_check/test_session_capacity_exact_then_full
        """
        world = make_open_world(session_capacity=2)
        app_a = _submitted_app(world, "fam-a", "Ann")
        app_b = _submitted_app(world, "fam-b", "Ben")
        app_c = _submitted_app(world, "fam-c", "Cat")
        schedule_test(app_a["id"], world["session"]["id"],
                      ("2026-10-10T09:00:00Z", "2026-10-10T10:00:00Z"))
        schedule_test(app_b["id"], world["session"]["id"],
                      ("2026-10-10T10:00:00Z", "2026-10-10T11:00:00Z"))
        resp = api.create_evaluation(
            create_evaluation_payload(
                app_c["id"], "TEST",
                scheduled_start="2026-10-10T11:00:00Z",
                scheduled_end="2026-10-10T11:30:00Z",
                test_session_id=world["session"]["id"],
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_SESSION_FULL, 409)
        # The rejected booking consumed no capacity.
        assert get_session(world["session"]["id"])["booked_count"] == 2


class TestEvaluationLifecycleRules:
    def test_duplicate_evaluation_kind_then_rebook_after_cancel(
            self, api, officer_headers):
        """PRD §3.3: "An application may carry at most one non-cancelled
        evaluation of each kind; a duplicate kind while the earlier one is
        still live draws `ERR_DUPLICATE_EVALUATION_KIND`."
        PRD §3.3: "An officer may also cancel a `SCHEDULED` evaluation, moving
        it to `CANCELLED`; cancelling a test frees its seat by subtracting one
        from the session's `booked_count`. A cancelled evaluation no longer
        blocks re-scheduling the same kind."

        Design: Corner/validations/duplicate_evaluation_kind_then_rebook_after_cancel
        """
        ctx = setup_submitted_application("fam-a")
        session_id = ctx["session"]["id"]
        first = schedule_test(ctx["application"]["id"], session_id,
                              ("2026-10-10T09:00:00Z", "2026-10-10T10:00:00Z"))
        resp = api.create_evaluation(
            create_evaluation_payload(
                ctx["application"]["id"], "TEST",
                scheduled_start="2026-10-10T10:00:00Z",
                scheduled_end="2026-10-10T11:00:00Z",
                test_session_id=session_id,
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EVALUATION_KIND, 409)
        validate_success(api.cancel_evaluation(first["id"], officer_headers))
        assert get_evaluation(first["id"])["status"] == "CANCELLED"
        resp = api.create_evaluation(
            create_evaluation_payload(
                ctx["application"]["id"], "TEST",
                scheduled_start="2026-10-10T10:00:00Z",
                scheduled_end="2026-10-10T11:00:00Z",
                test_session_id=session_id,
            ),
            officer_headers,
        )
        validate_success(resp, 201)
        # Cancel decremented the session count; the rebook brings it back to 1.
        assert get_session(session_id)["booked_count"] == 1

    def test_evaluation_outside_session_window_rejected(self, api,
                                                        officer_headers):
        """PRD §3.3: "A test evaluation's window must also lie entirely within
        its session's `session_start`-to-`session_end` window, or it is
        rejected with `ERR_EVALUATION_OUTSIDE_SESSION`."

        Design: Corner/validations/evaluation_outside_session_window_rejected
        """
        ctx = setup_submitted_application("fam-a")
        resp = api.create_evaluation(
            create_evaluation_payload(
                ctx["application"]["id"], "TEST",
                scheduled_start="2026-10-10T08:00:00Z",  # before 09:00 start
                scheduled_end="2026-10-10T09:00:00Z",
                test_session_id=ctx["session"]["id"],
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATION_OUTSIDE_SESSION, 409)
        assert get_session(ctx["session"]["id"])["booked_count"] == 0

    def test_score_already_scored_evaluation_rejected(self, api,
                                                      officer_headers):
        """PRD §3.3: "An officer records a `score` — an integer from 0 to 100
        inclusive, anything outside drawing `ERR_VALIDATION` — on a
        `SCHEDULED` evaluation (`ERR_EVALUATION_NOT_SCHEDULED` otherwise),
        moving it to `SCORED`; the field is null until then."

        Design: Corner/state_machines/score_already_scored_evaluation_rejected
        """
        ctx = setup_submitted_application("fam-a")
        evaluation = schedule_test(ctx["application"]["id"],
                                   ctx["session"]["id"])
        score_evaluation(evaluation["id"], 80)
        resp = api.score_evaluation(evaluation["id"], 95, officer_headers)
        validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_SCHEDULED, 409)
        assert get_evaluation(evaluation["id"])["score"] == 80


class TestCompositeScoring:
    def test_second_scored_evaluation_completes_application(
            self, api, officer_headers):
        """PRD §3.3: "The moment an application's second evaluation kind
        reaches `SCORED`, the system computes the committee composite and
        advances the application `SUBMITTED` → `EVALUATION_COMPLETE`."
        PRD §3.3: "The weighted component is sixty percent of the `TEST` score
        plus forty percent of the `INTERVIEW` score, rounded half-up to two
        decimal places."

        Design: Corner/state_machines/second_scored_evaluation_completes_application
        """
        ctx = setup_submitted_application("fam-a")
        test_eval = schedule_test(ctx["application"]["id"],
                                  ctx["session"]["id"])
        interview = schedule_interview(ctx["application"]["id"], "int-a")
        score_evaluation(test_eval["id"], 80)
        between = get_application(ctx["application"]["id"])
        assert between["status"] == "SUBMITTED"
        assert between["composite_score"] is None
        score_evaluation(interview["id"], 90)
        after = get_application(ctx["application"]["id"])
        assert after["status"] == "EVALUATION_COMPLETE"
        assert after["composite_score"] == pytest.approx(84.0)
        assert after["preference_points"] == 0
        assert after["sibling_verified"] is False

    def test_composite_with_sibling_and_legacy_points(self, api,
                                                      officer_headers):
        """PRD §3.3: "Preference points are then evaluated as integers and
        added after that rounding: sibling verification is resolved at this
        exact instant, with `sibling_verified` true if and only if an `ACTIVE`
        student exists whose `family_id` matches the applicant's family, worth
        ten points when true, and the applicant's `legacy_parent` flag is
        worth five points when set; the sum lands in `preference_points`, and
        the weighted component plus the preference points is the application's
        `composite_score`."

        Design: Corner/calculations/composite_with_sibling_and_legacy_points
        """
        world = make_open_world()
        make_student("fam-s", world["section"]["id"], first_name="Sid")
        applicant = make_applicant("fam-s", legacy_parent=True)
        application = make_application(applicant["id"], world["cycle"]["id"],
                                       world["section"]["id"], "fam-s", "EARLY")
        submit_application(application["id"], "fam-s")
        test_eval = schedule_test(application["id"], world["session"]["id"])
        interview = schedule_interview(application["id"], "int-a")
        score_evaluation(test_eval["id"], 80)
        score_evaluation(interview["id"], 90)
        data = get_application(application["id"])
        # 0.6*80 + 0.4*90 = 84.0 weighted; +10 sibling +5 legacy afterwards.
        assert data["composite_score"] == pytest.approx(99.0)
        assert data["preference_points"] == 15
        assert data["sibling_verified"] is True

    def test_sibling_points_require_same_family_active_student(
            self, api, officer_headers):
        """PRD §3.3: "`sibling_verified` true if and only if an `ACTIVE`
        student exists whose `family_id` matches the applicant's family".

        Design: Corner/calculations/sibling_points_require_same_family_active_student
        """
        world = make_open_world()
        # An ACTIVE student of a DIFFERENT family must not count.
        make_student("fam-other", world["section"]["id"], first_name="Ola")
        applicant = make_applicant("fam-a", legacy_parent=True)
        application = make_application(applicant["id"], world["cycle"]["id"],
                                       world["section"]["id"], "fam-a", "EARLY")
        submit_application(application["id"], "fam-a")
        test_eval = schedule_test(application["id"], world["session"]["id"])
        interview = schedule_interview(application["id"], "int-a")
        score_evaluation(test_eval["id"], 80)
        score_evaluation(interview["id"], 90)
        data = get_application(application["id"])
        assert data["sibling_verified"] is False
        assert data["composite_score"] == pytest.approx(89.0)  # 84.0 + 5
        assert data["preference_points"] == 5

    def test_composite_tie_broken_by_submitted_at(self, api, director_headers):
        """PRD §3.5: "Candidates are ranked by `composite_score` descending,
        then `submitted_at` ascending, then `created_at` ascending; per §2.5,
        identifiers are never consulted."

        Design: Corner/calculations/composite_tie_broken_by_submitted_at
        """
        ctx = setup_decision_world(
            [
                {"family": "fam-early", "test": 80, "interview": 90,
                 "submit_at": "2026-09-01T00:00:00Z"},
                {"family": "fam-late", "test": 80, "interview": 90,
                 "submit_at": "2026-09-02T00:00:00Z"},
            ],
            capacity=1,
        )
        early = ctx["candidates"][0]["application"]
        late = ctx["candidates"][1]["application"]
        assert early["composite_score"] == pytest.approx(84.0)
        assert late["composite_score"] == pytest.approx(84.0)
        # Equal composites: the earlier submitted_at wins the single seat.
        assert early["status"] == "OFFERED"
        assert late["status"] == "WAITLISTED"


class TestRescheduleOcc:
    def test_occ_evaluation_reschedule_stale_rejected(self, api,
                                                      officer_headers):
        """PRD §2.8: "Rescheduling an entrance evaluation requires the request
        to carry `expected_evaluation_version`, holding the `version` of the
        `EntranceEvaluation` as the client last read it. A reschedule leaves
        the evaluation in `SCHEDULED`, so a second sequential reschedule
        observes an identical state field and would itself legitimately
        succeed; only the stale version distinguishes the lost update. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_evaluation_reschedule_stale_rejected
        """
        ctx = setup_submitted_application("fam-a")
        evaluation = schedule_interview(
            ctx["application"]["id"], "int-7",
            ("2026-10-12T10:00:00Z", "2026-10-12T11:00:00Z"),
        )
        stale_version = evaluation["version"]
        resp = api.reschedule_evaluation(
            evaluation["id"],
            {"expected_evaluation_version": stale_version,
             "scheduled_start": "2026-10-12T14:00:00Z",
             "scheduled_end": "2026-10-12T15:00:00Z"},
            officer_headers,
        )
        moved = validate_success(resp, 200)
        assert moved["version"] == stale_version + 1
        assert moved["scheduled_start"] == "2026-10-12T14:00:00Z"
        assert moved["status"] == "SCHEDULED"
        # Replaying the pre-patch version is the lost-update case.
        resp = api.reschedule_evaluation(
            evaluation["id"],
            {"expected_evaluation_version": stale_version,
             "scheduled_start": "2026-10-12T16:00:00Z",
             "scheduled_end": "2026-10-12T17:00:00Z"},
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        current = get_evaluation(evaluation["id"])
        assert current["scheduled_start"] == "2026-10-12T14:00:00Z"
        assert current["scheduled_end"] == "2026-10-12T15:00:00Z"

    def test_reschedule_into_interviewer_conflict_rejected(
            self, api, officer_headers):
        """PRD §3.3: "Rescheduling requires the evaluation to still be
        `SCHEDULED` (`ERR_EVALUATION_NOT_SCHEDULED` otherwise), re-applies the
        interviewer-overlap and session-window rules excluding the evaluation
        itself".

        Design: Corner/complexity_layers/reschedule_into_interviewer_conflict_rejected
        """
        world = make_open_world()
        app_a = _submitted_app(world, "fam-a", "Ann")
        app_b = _submitted_app(world, "fam-b", "Ben")
        schedule_interview(app_a["id"], "int-9",
                           ("2026-10-12T10:00:00Z", "2026-10-12T11:00:00Z"))
        eval_b = schedule_interview(
            app_b["id"], "int-9",
            ("2026-10-12T12:00:00Z", "2026-10-12T13:00:00Z"),
        )
        # Fresh OCC version, but 10:30-11:30 collides with A's 10:00-11:00.
        resp = api.reschedule_evaluation(
            eval_b["id"],
            {"expected_evaluation_version": eval_b["version"],
             "scheduled_start": "2026-10-12T10:30:00Z",
             "scheduled_end": "2026-10-12T11:30:00Z"},
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEWER_SCHEDULE_CONFLICT, 409)
        current = get_evaluation(eval_b["id"])
        assert current["scheduled_start"] == "2026-10-12T12:00:00Z"
        assert current["scheduled_end"] == "2026-10-12T13:00:00Z"
