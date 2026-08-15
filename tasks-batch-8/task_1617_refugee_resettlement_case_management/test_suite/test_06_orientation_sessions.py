"""Orientation sessions (PRD §3.4, §3.5): the 30-minute buffer rule, topic
uniqueness rules, topics_completed reconciliation, and the all-six-topics
auto-fulfillment of the CULTURAL_ORIENTATION benchmark.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    date_part,
    ALL_ORIENTATION_TOPICS,
    setup_arrived_case, set_clock, get_case,
    make_orientation_session, complete_orientation_session,
    get_benchmark_by_type,
)
from test_helpers.fixtures import CM


def _arrived_case(case_number):
    return setup_arrived_case(case_number=case_number, household_size=1)


class TestOrientationBufferSemantics:
    def test_start_exactly_thirty_minutes_after_prior_end_allowed(self, api):
        """PRD §3.5: "the new session must keep a 30-minute buffer against
        every `SCHEDULED` or `COMPLETED` session of the same case — meaning
        no other such session may start less than 30 minutes after this one
        ends or end less than 30 minutes before this one starts — and a
        violation is rejected with `ERR_SESSION_SCHEDULE_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/orientation_buffer_semantics
        """
        ctx = _arrived_case("CASE-TO2")
        s1 = make_orientation_session(ctx["case"]["id"], topic="US_LAWS",
                                      start_at="2026-08-12T09:00:00Z",
                                      end_at="2026-08-12T10:00:00Z")
        assert s1["status"] == "SCHEDULED"
        resp = api.create_orientation_session(
            {"case_id": ctx["case"]["id"], "topic": "HEALTHCARE_ACCESS",
             "start_at": "2026-08-12T10:30:00Z", "end_at": "2026-08-12T11:30:00Z"}, CM)
        s2 = validate_success(resp, 201)
        assert s2["status"] == "SCHEDULED"

    def test_start_inside_thirty_minute_buffer_rejected(self, api):
        """PRD §3.5: "the new session must keep a 30-minute buffer against
        every `SCHEDULED` or `COMPLETED` session of the same case — meaning
        no other such session may start less than 30 minutes after this one
        ends or end less than 30 minutes before this one starts — and a
        violation is rejected with `ERR_SESSION_SCHEDULE_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/orientation_buffer_semantics
        """
        ctx = _arrived_case("CASE-TO2B")
        make_orientation_session(ctx["case"]["id"], topic="US_LAWS",
                                 start_at="2026-08-12T09:00:00Z",
                                 end_at="2026-08-12T10:00:00Z")
        resp = api.create_orientation_session(
            {"case_id": ctx["case"]["id"], "topic": "EDUCATION_SYSTEM",
             "start_at": "2026-08-12T10:00:00Z", "end_at": "2026-08-12T11:00:00Z"}, CM)
        validate_error(resp, ApiErrorId.ERR_SESSION_SCHEDULE_CONFLICT)


class TestTopicUniquenessRules:
    def test_completed_topic_cannot_be_scheduled_again(self, api):
        """PRD §3.5: "a topic already delivered — that is, having a
        `COMPLETED` session for this case — is rejected with
        `ERR_TOPIC_ALREADY_DELIVERED` (HTTP 409)".

        Design: Corner/validations/topic_already_delivered_returns_error
        """
        ctx = _arrived_case("CASE-V14")
        s1 = make_orientation_session(ctx["case"]["id"], topic="US_LAWS",
                                      start_at="2026-08-12T09:00:00Z",
                                      end_at="2026-08-12T10:00:00Z")
        set_clock("2026-08-13T10:00:00Z")
        complete_orientation_session(s1["id"])
        resp = api.create_orientation_session(
            {"case_id": ctx["case"]["id"], "topic": "US_LAWS",
             "start_at": "2026-08-20T09:00:00Z", "end_at": "2026-08-20T10:00:00Z"}, CM)
        validate_error(resp, ApiErrorId.ERR_TOPIC_ALREADY_DELIVERED)

    def test_scheduled_topic_cannot_be_double_booked(self, api):
        """PRD §3.5: "a topic that already has a `SCHEDULED` session for this
        case is rejected with `ERR_TOPIC_ALREADY_SCHEDULED` (HTTP 409)".

        Design: Corner/validations/topic_already_scheduled_returns_error
        """
        ctx = _arrived_case("CASE-V15")
        make_orientation_session(ctx["case"]["id"], topic="HEALTHCARE_ACCESS",
                                 start_at="2026-08-12T09:00:00Z",
                                 end_at="2026-08-12T10:00:00Z")
        resp = api.create_orientation_session(
            {"case_id": ctx["case"]["id"], "topic": "HEALTHCARE_ACCESS",
             "start_at": "2026-08-13T09:00:00Z", "end_at": "2026-08-13T10:00:00Z"}, CM)
        validate_error(resp, ApiErrorId.ERR_TOPIC_ALREADY_SCHEDULED)


class TestSessionWindowValidation:
    def test_end_not_after_start_rejected(self, api):
        """PRD §3.5: "A `CaseManager` schedules an orientation session with
        the `case_id`, a `topic` from the six-topic curriculum — `US_LAWS`,
        `HEALTHCARE_ACCESS`, `EDUCATION_SYSTEM`, `EMPLOYMENT_RIGHTS`,
        `HOUSING_SAFETY`, `BUDGETING` — and a window `start_at` to `end_at`
        (both ISO 8601 datetimes; an end not strictly after the start fails
        with `ERR_VALIDATION`)."

        Design: Corner/validations/session_inverted_times_returns_invalid_request
        """
        ctx = _arrived_case("CASE-V4")
        resp = api.create_orientation_session(
            {"case_id": ctx["case"]["id"], "topic": "US_LAWS",
             "start_at": "2026-08-12T10:00:00Z", "end_at": "2026-08-12T09:00:00Z"}, CM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestTopicsCompletedReconciliation:
    def test_single_completion_adds_exactly_one_topic(self, api):
        """PRD §3.5: "That completion recomputes the case's derived
        `topics_completed`, the sorted unique list of topics with a
        `COMPLETED` session, adding the session's topic."

        Design: Corner/complexity_layers/topics_completed_recomputed_on_complete
        """
        ctx = _arrived_case("CASE-CL3")
        s1 = make_orientation_session(ctx["case"]["id"], topic="US_LAWS",
                                      start_at="2026-08-12T09:00:00Z",
                                      end_at="2026-08-12T10:00:00Z")
        set_clock("2026-08-13T10:00:00Z")
        complete_orientation_session(s1["id"])
        case = get_case(ctx["case"]["id"], headers=CM)
        assert case["topics_completed"] == ["US_LAWS"]

    def test_benchmark_stays_pending_until_all_six_topics(self, api):
        """PRD §3.5: "And if that recomputation makes `topics_completed`
        cover all six topics while the case's `CULTURAL_ORIENTATION`
        benchmark is still `PENDING`, the benchmark auto-transitions to `MET`
        as described in §3.4".

        Design: Corner/complexity_layers/topics_completed_recomputed_on_complete
        """
        ctx = _arrived_case("CASE-CL3B")
        s1 = make_orientation_session(ctx["case"]["id"], topic="US_LAWS",
                                      start_at="2026-08-12T09:00:00Z",
                                      end_at="2026-08-12T10:00:00Z")
        set_clock("2026-08-13T10:00:00Z")
        complete_orientation_session(s1["id"])
        bm = get_benchmark_by_type(ctx["case"]["id"], "CULTURAL_ORIENTATION")
        assert bm["status"] == "PENDING"


def _schedule_all_six_topics(case_id):
    """Schedule all six curriculum sessions with >= 30-minute gaps."""
    slots = {
        "US_LAWS": ("2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z"),
        "HEALTHCARE_ACCESS": ("2026-08-12T10:30:00Z", "2026-08-12T11:30:00Z"),
        "EDUCATION_SYSTEM": ("2026-08-12T13:00:00Z", "2026-08-12T14:00:00Z"),
        "EMPLOYMENT_RIGHTS": ("2026-08-12T14:30:00Z", "2026-08-12T15:30:00Z"),
        "HOUSING_SAFETY": ("2026-08-12T16:00:00Z", "2026-08-12T17:00:00Z"),
        "BUDGETING": ("2026-08-13T09:00:00Z", "2026-08-13T10:00:00Z"),
    }
    sessions = {}
    for topic in ALL_ORIENTATION_TOPICS:
        start_at, end_at = slots[topic]
        sessions[topic] = make_orientation_session(
            case_id, topic=topic, start_at=start_at, end_at=end_at)
    return sessions


class TestSixthCompletionAutoFulfillsBenchmark:
    def test_sixth_completion_marks_session_and_covers_topics(self, api):
        """PRD §3.5: "Completing a session — again a `CaseManager` action,
        requiring no open transfer — moves it `SCHEDULED → COMPLETED` and
        stamps `completed_on` from the logical clock. That completion
        recomputes the case's derived `topics_completed`, the sorted unique
        list of topics with a `COMPLETED` session, adding the session's
        topic."

        Design: Difficulty/transitive_cascade/orientation_completion_depth2_cascade
        """
        ctx = _arrived_case("CASE-TC2")
        sessions = _schedule_all_six_topics(ctx["case"]["id"])
        set_clock("2026-08-13T10:00:00Z")
        for topic in ALL_ORIENTATION_TOPICS[:5]:
            complete_orientation_session(sessions[topic]["id"])
        last = complete_orientation_session(sessions["BUDGETING"]["id"])
        assert last["status"] == "COMPLETED"
        assert date_part(last["completed_on"]) == "2026-08-13"
        case = get_case(ctx["case"]["id"], headers=CM)
        assert sorted(case["topics_completed"]) == sorted(ALL_ORIENTATION_TOPICS)

    def test_benchmark_auto_met_with_null_evidence_and_on_time(self, api):
        """PRD §3.4: "The `CULTURAL_ORIENTATION` benchmark moves `PENDING →
        MET` automatically at the moment an orientation-session completion
        makes the case's `topics_completed` cover all six curriculum topics;
        in that auto-fulfillment `fulfilled_on` is the completing session's
        `completed_on`, `evidence_note_id` stays null, and `on_time` is
        computed by the same inclusive comparison."

        Design: Difficulty/transitive_cascade/orientation_completion_depth2_cascade
        """
        ctx = _arrived_case("CASE-TC2B")
        sessions = _schedule_all_six_topics(ctx["case"]["id"])
        set_clock("2026-08-13T10:00:00Z")
        for topic in ALL_ORIENTATION_TOPICS:
            complete_orientation_session(sessions[topic]["id"])
        bm = get_benchmark_by_type(ctx["case"]["id"], "CULTURAL_ORIENTATION")
        assert bm["status"] == "MET"
        assert date_part(bm["fulfilled_on"]) == "2026-08-13"
        assert bm["evidence_note_id"] is None
        assert bm["on_time"] is True
