"""No-show strike discipline and survey response scoring."""
import pytest

from test_helpers import (
    ApiErrorId,
    assign_moderator,
    book_session,
    close_study,
    create_and_publish_instrument,
    create_moderator,
    create_remote_session,
    create_response_payload,
    create_study,
    enroll_participant,
    get_participant,
    get_success_data,
    is_iso8601_timestamp,
    make_participant_headers,
    register_participant,
    run_session_at_midpoint,
    set_clock,
    setup_enrolled_participant,
    setup_participant_session_history,
    setup_study_with_published_nda,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]


def test_no_show_strike_threshold_suspends_at_third(api):
    """PRD §3.5: "Whenever a booking enters `NO_SHOW`, `no_show_recorded_at` is
    stamped and the participant's `no_show_strikes` is recomputed as the count
    of that participant's `NO_SHOW` bookings whose `no_show_recorded_at` falls
    on or after the instant ninety days before now — a rolling window with an
    inclusive boundary; `CANCELLED` and `ATTENDED` bookings never count. If the
    participant is `ACTIVE` and the recomputed count reaches 3 — exactly three
    strikes is enough — the participant transitions automatically `ACTIVE` →
    `SUSPENDED` and the full suspension cascade of §3.1 runs"
    PRD §3.5: "Completing the session — `IN_PROGRESS` → `COMPLETED`, again the
    assigned moderator only — auto-marks every booking still in `BOOKED` or
    `PROMOTED` as `NO_SHOW`, stamping each with a `no_show_recorded_at` of the
    completion instant"

    Design: Corner/calculations/no_show_strike_threshold_suspends_at_third
    """
    set_clock("2026-08-01T00:00:00Z")
    study, _nda = setup_study_with_published_nda(code="CALC3")
    participant = register_participant(email="calc3-p@x.com")
    enroll_participant(study["id"], participant)
    moderator = create_moderator(display_name="Mod Calc3")
    # First two sessions auto-no-show the participant.
    setup_participant_session_history(participant, study, moderator,
                                      ["no_show", "no_show"])
    mid = get_participant(participant["id"])
    assert mid["no_show_strikes"] == 2
    assert mid["status"] == "ACTIVE", "two strikes is still below the limit"
    # Third session (the study is already CLOSED, which still permits session
    # creation and the booking gates): strikes reach exactly 3 -> SUSPENDED.
    s3 = create_remote_session(study["id"], "2026-08-10T14:00:00Z",
                               "2026-08-10T15:00:00Z", seat_capacity=5)
    assign_moderator(s3["id"], moderator["id"])
    book_session(s3["id"], participant["id"])
    run_session_at_midpoint(s3, moderator["id"])
    end = get_participant(participant["id"])
    assert end["no_show_strikes"] == 3
    assert end["status"] == "SUSPENDED", "exactly three strikes auto-suspends"


def _setup_draft_response(api, questions, pass_threshold, answers,
                          email="cf2-p@x.com", attend=True):
    """Enrolled participant + (optionally ATTENDED) session + PUBLISHED
    instrument + a DRAFT response carrying `answers`."""
    set_clock("2026-08-01T00:00:00Z")
    study, _nda = setup_study_with_published_nda()
    participant = register_participant(email=email)
    enroll_participant(study["id"], participant)
    moderator = create_moderator()
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=5)
    assign_moderator(session["id"], moderator["id"])
    booking = book_session(session["id"], participant["id"])
    if attend:
        close_study(study["id"])
        run_session_at_midpoint(session, moderator["id"],
                                attend_booking_ids=[booking["id"]])
    instrument = create_and_publish_instrument(
        study["id"], questions=questions, pass_threshold=pass_threshold,
        title="Post-session survey")
    response = get_success_data(api.create_survey_response(
        create_response_payload(instrument["id"], session["id"], answers=answers),
        make_participant_headers(participant["id"])))
    return {"study": study, "participant": participant, "moderator": moderator,
            "session": session, "booking": booking, "instrument": instrument,
            "response": response}


class TestSurveyWeightedScoreRoundingOrder:
    QUESTIONS = [{"question_key": "q1", "weight": 1, "max_points": 3},
                 {"question_key": "q2", "weight": 1, "max_points": 3},
                 {"question_key": "q3", "weight": 1, "max_points": 3}]
    ANSWERS = [{"question_key": "q1", "points": 1},
               {"question_key": "q2", "points": 1},
               {"question_key": "q3", "points": 1}]

    def test_per_question_rounding_before_summation(self, api):
        """PRD §3.6: "Each answered question contributes its `points` divided
        by its `max_points`, multiplied by its `weight`, and that per-question
        contribution is rounded half-up to two decimal places before any
        summation — rounding only the final sum is not equivalent and is
        non-conformant. The `weighted_score` is the sum of those rounded
        contributions, itself rounded half-up to two decimals; `score_pct` is
        the `weighted_score` divided by the total weight, multiplied by 100,
        rounded half-up to two decimals"

        Design: Difficulty/combinatorial_formula/survey_weighted_score_nested_rounding_order
        """
        ctx = _setup_draft_response(api, self.QUESTIONS, 33, self.ANSWERS)
        pid = ctx["participant"]["id"]
        submitted = validate_success(api.submit_survey_response(
            ctx["response"]["id"], make_participant_headers(pid)))
        # 1/3 * 1 rounds to 0.33 per question FIRST: 0.33 + 0.33 + 0.33 = 0.99.
        # Sum-then-round would yield 1.00 and 33.33 — non-conformant.
        assert submitted["weighted_score"] == pytest.approx(0.99, abs=0.001)
        assert submitted["score_pct"] == pytest.approx(33.0, abs=0.001)

    def test_equality_at_pass_threshold_passes(self, api):
        """PRD §3.6: "`passed` is true when `score_pct` is at least the
        instrument's `pass_threshold` — equality passes. Questions with no
        matching answer contribute 0. Submission stamps `submitted_at` and
        moves the response `DRAFT` → `SUBMITTED`"

        Design: Difficulty/combinatorial_formula/survey_weighted_score_nested_rounding_order
        """
        ctx = _setup_draft_response(api, self.QUESTIONS, 33, self.ANSWERS)
        pid = ctx["participant"]["id"]
        submitted = validate_success(api.submit_survey_response(
            ctx["response"]["id"], make_participant_headers(pid)))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["passed"] is True, "33.0 >= 33 passes (inclusive boundary)"
        assert is_iso8601_timestamp(submitted["submitted_at"])


class TestSurveySubmitRequiresAttendedBooking:
    def test_submit_without_attendance_rejected(self, api):
        """PRD §3.6: "the participant must hold an `ATTENDED` booking for the
        covered session (`ERR_ATTENDANCE_REQUIRED`)"
        PRD §3.6: "A draft response holds null `weighted_score`, `score_pct`,
        and `passed` until it is submitted."

        Design: Difficulty/cross_entity_state_dependency/survey_submit_requires_attended_booking
        """
        # Booking stays BOOKED — the session never starts.
        ctx = _setup_draft_response(api, None, 50, None, email="ce3-p@x.com",
                                    attend=False)
        pid = ctx["participant"]["id"]
        resp = api.submit_survey_response(ctx["response"]["id"],
                                          make_participant_headers(pid))
        validate_error(resp, ApiErrorId.ERR_ATTENDANCE_REQUIRED)
        current = get_success_data(api.get_survey_response(ctx["response"]["id"], ADMIN))
        assert current["status"] == "DRAFT"
        assert current["weighted_score"] is None
        assert current["score_pct"] is None
        assert current["passed"] is None

    def test_submit_succeeds_once_booking_attended(self, api):
        """PRD §3.6: "the participant must hold an `ATTENDED` booking for the
        covered session (`ERR_ATTENDANCE_REQUIRED`)"
        PRD §3.6: "Submission stamps `submitted_at` and moves the response
        `DRAFT` → `SUBMITTED`"

        Design: Difficulty/cross_entity_state_dependency/survey_submit_requires_attended_booking
        """
        ctx = _setup_draft_response(api, None, 50, None, email="ce3-p@x.com",
                                    attend=True)
        pid = ctx["participant"]["id"]
        submitted = validate_success(api.submit_survey_response(
            ctx["response"]["id"], make_participant_headers(pid)))
        assert submitted["status"] == "SUBMITTED"
        # Default instrument: one question weight 1, max_points 10, answer 8.
        assert submitted["weighted_score"] == pytest.approx(0.8, abs=0.001)
        assert submitted["score_pct"] == pytest.approx(80.0, abs=0.001)
        assert submitted["passed"] is True


def test_survey_unknown_question_rejected(api):
    """PRD §3.6: "every answered `question_key` must exist in the instrument
    (`ERR_UNKNOWN_QUESTION`)"

    Design: Corner/validations/survey_unknown_question_rejected
    """
    ctx = _setup_draft_response(
        api, [{"question_key": "q1", "weight": 1, "max_points": 5}], 50,
        [{"question_key": "qX", "points": 3}], email="uq-p@x.com")
    pid = ctx["participant"]["id"]
    resp = api.submit_survey_response(ctx["response"]["id"],
                                      make_participant_headers(pid))
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_QUESTION)
    current = get_success_data(api.get_survey_response(ctx["response"]["id"], ADMIN))
    assert current["status"] == "DRAFT"


def test_duplicate_response_rejected(api):
    """PRD §3.6: "At most one response may exist per instrument, session, and
    participant triple (`ERR_DUPLICATE_RESPONSE`)."

    Design: Corner/validations/duplicate_response_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    ctx = setup_enrolled_participant(email="dr-p@x.com")
    session = create_remote_session(ctx["study"]["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=5)
    instrument = create_and_publish_instrument(
        ctx["study"]["id"], questions=[{"question_key": "q1", "weight": 1,
                                        "max_points": 5}], title="DR survey")
    pid = ctx["participant"]["id"]
    first = get_success_data(api.create_survey_response(
        create_response_payload(instrument["id"], session["id"],
                                answers=[{"question_key": "q1", "points": 3}]),
        make_participant_headers(pid)))
    assert first["status"] == "DRAFT"
    resp = api.create_survey_response(
        create_response_payload(instrument["id"], session["id"],
                                answers=[{"question_key": "q1", "points": 4}]),
        make_participant_headers(pid))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESPONSE)


def test_instrument_double_publish_rejected(api):
    """PRD §3.6: "publishing moves `DRAFT` → `PUBLISHED` and is refused with
    `ERR_INSTRUMENT_ALREADY_PUBLISHED` while any other instrument of the same
    study is `PUBLISHED`, so at most one published instrument exists per study
    at any moment"

    Design: Corner/validations/instrument_double_publish_rejected
    """
    study = create_study(open_recruitment=False, code="INST")
    i1 = create_and_publish_instrument(study["id"], title="I1",
                                       questions=[{"question_key": "q1",
                                                   "weight": 1, "max_points": 5}])
    assert i1["status"] == "PUBLISHED"
    i2 = get_success_data(api.create_survey_instrument(
        {"study_id": study["id"], "title": "I2",
         "questions": [{"question_key": "q1", "weight": 1, "max_points": 5}],
         "pass_threshold": 50}, RESEARCHER))
    resp = api.publish_survey_instrument(i2["id"], RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_ALREADY_PUBLISHED)
    current = get_success_data(api.get_survey_instrument(i2["id"], RESEARCHER))
    assert current["status"] == "DRAFT"
