"""Seat releases, dimension forks and the parallel machine that check-in advances."""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.test_users import (
    ELIGIBILITY_REVIEWER_1_ID,
    ELIGIBILITY_REVIEWER_2_ID,
    make_eligibility_reviewer_headers,
)

REVIEWER_ONE = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_1_ID)
REVIEWER_TWO = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_2_ID)

FIRST_CANCELLATION = {"cancel_reason": "candidate deferred"}
SECOND_CANCELLATION = {"cancel_reason": "duplicate request"}
WINDOW_OPENS = "2026-08-09T23:30:00Z"
ONE_MINUTE_EARLY = "2026-08-09T23:29:00Z"


class TestSeatReleaseIsATransitionNotAnIdempotentWrite:
    """The second cancellation finds nothing to release."""

    def test_a_repeated_cancellation_is_refused_and_the_ledger_never_goes_negative(
            self, api):
        """The first release empties the seat, and the second is refused on state, which
        is what keeps `seats_reserved` from being decremented twice.

        PRD §3.7: "Releasing a seat voluntarily moves the registration `SCHEDULED →
        UNSCHEDULED` and takes an optional `cancel_reason`."

        PRD §3.7: "The registration must be `SCHEDULED`, or `ERR_INVALID_STATE`, and the
        logical clock must still be strictly before the held session's `starts_at`, or
        `ERR_SESSION_CLOSED` — a candidate cannot walk away from a session that has
        already begun."

        Design: Corner/state_machines/registration_cancel_schedule_repeated_from_unscheduled_returns_invalid_state
        """
        state = fx.pipeline_through_scheduled_seat(api)

        released = validate_success(api.cancel_seat_schedule(
            state.registration_id, FIRST_CANCELLATION, fx.EXAM_OPERATIONS), 200)
        assert released["seat_status"] == "UNSCHEDULED"
        assert fx.read_session(api, state.session_id)["seats_reserved"] == 0

        refused = api.cancel_seat_schedule(
            state.registration_id, SECOND_CANCELLATION, fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)
        session = fx.read_session(api, state.session_id)
        assert session["seats_reserved"] == 0
        assert session["status"] == "OPEN"
        ax.assert_seat_ledger_within_bounds(session)


class TestEachEligibilityDimensionIsDecidedOnce:
    """The fork admits one decision per branch, whoever submits it."""

    def test_verifying_the_same_dimension_twice_is_refused(self, api):
        """A second EDUCATION decision — even from a different reviewer with the same
        outcome — is refused, the verifier list keeps exactly one entry, and the
        application does not short-cut to APPROVED on one dimension.

        PRD §3.6: "The application must be in `SUBMITTED` or `UNDER_REVIEW` status, or
        `ERR_INVALID_STATE`, and the named dimension must still be `PENDING`, or
        `ERR_DIMENSION_ALREADY_VERIFIED`."

        PRD §3.6: "Each accepted call appends a record of the `dimension` together with
        the acting `user_id` to `verifier_user_ids`, in call order."

        PRD §3.6: "A first call out of `SUBMITTED` that verifies its dimension moves the
        application `SUBMITTED → UNDER_REVIEW`."

        Design: Corner/state_machines/application_verifying_the_same_dimension_twice_returns_dimension_already_verified
        """
        program = fx.active_program(api)
        candidate = fx.create_candidate(api)
        application = fx.submitted_application(api, candidate["id"], program["id"])

        first = validate_success(api.verify_application_dimension(
            application["id"],
            f.verify_dimension_payload("EDUCATION", "PASS",
                                       review_note="transcript sighted"),
            REVIEWER_ONE), 200)
        assert first["status"] == "UNDER_REVIEW"
        assert first["education_status"] == "VERIFIED"

        refused = api.verify_application_dimension(
            application["id"],
            f.verify_dimension_payload("EDUCATION", "PASS",
                                       review_note="second sighting"),
            REVIEWER_TWO)

        validate_error(refused, ApiErrorId.ERR_DIMENSION_ALREADY_VERIFIED.value, 409)
        unchanged = fx.read_application(api, application["id"])
        education_entries = [entry for entry in unchanged["verifier_user_ids"]
                            if entry["dimension"] == "EDUCATION"]
        assert len(education_entries) == 1
        assert education_entries[0]["user_id"] == ELIGIBILITY_REVIEWER_1_ID
        assert unchanged["status"] == "UNDER_REVIEW"
        assert unchanged["experience_status"] == "PENDING"


class TestCheckInAdvancesBothDimensions:
    """One call, two status dimensions, and a seat that stays occupied."""

    def test_check_in_moves_the_seat_and_the_score_dimension_together(self, api):
        """`seat_status` and `score_status` advance on the same call, no score fields are
        written yet, and the seat ledger does not move because a checked-in seat is still
        occupied.

        PRD §3.8: "Check-in is performed by an `ExamOperations` operator, optionally
        annotated with a `checkin_note`, and it is the one call in this system that
        advances **both** of a registration's status dimensions at once: `seat_status`
        moves `SCHEDULED → CHECKED_IN` and, on the same call, `score_status` moves
        `NOT_APPLICABLE → PENDING`."

        PRD §3.7: "`seats_reserved` is the number of exam registrations pointing at the
        session whose `seat_status` is `SCHEDULED`, `CHECKED_IN`, or `COMPLETED`; the
        `UNSCHEDULED`, `NO_SHOW`, and `CANCELLED` states all release the seat."

        Design: Corner/state_machines/check_in_moves_the_score_dimension_to_pending_on_the_same_call
        """
        state = fx.pipeline_at_session_open(api, session_start=WINDOW_OPENS)

        seated = validate_success(api.check_in(
            state.registration_id, f.check_in_payload(checkin_note="photo id verified"),
            fx.EXAM_OPERATIONS), 200)

        assert seated["seat_status"] == "CHECKED_IN"
        assert seated["score_status"] == "PENDING"
        assert seated["raw_score"] is None
        assert seated["scaled_score"] is None
        assert seated["outcome"] is None
        assert seated["score_status_before_hold"] is None

        session = fx.read_session(api, state.session_id)
        assert session["seats_reserved"] == 1
        assert session["seat_capacity"] == 5
        assert session["status"] == "OPEN"


class TestCheckInWindowOpensExactlyThirtyMinutesEarly:
    """The early edge of the window is inclusive to the minute."""

    def test_one_minute_before_the_window_is_refused_and_writes_nothing(self, api):
        """At `starts_at` less 31 minutes the call is refused and both dimensions stay
        where they were.

        PRD §3.8: "Four preconditions apply: the registration must be `SCHEDULED`, or
        `ERR_INVALID_STATE`; the candidate's `status` must be `ACTIVE`, or
        `ERR_CANDIDATE_BARRED`; the logical clock must fall within the check-in window,
        which opens 30 minutes before the session's `starts_at` and closes at the
        session's `ends_at`, both ends inclusive, or `ERR_CHECKIN_WINDOW_CLOSED`; and the
        cited form's `status` must still be `PUBLISHED`, or `ERR_FORM_NOT_PUBLISHED`."

        Design: Corner/state_machines/check_in_before_the_thirty_minute_window_returns_checkin_window_closed
        """
        state = fx.pipeline_through_scheduled_seat(api)
        fx.set_clock(api, ONE_MINUTE_EARLY)

        refused = api.check_in(
            state.registration_id, f.check_in_payload(checkin_note="one minute early"),
            fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED.value, 409)
        unchanged = fx.read_registration(api, state.registration_id)
        assert unchanged["seat_status"] == "SCHEDULED"
        assert unchanged["score_status"] == "NOT_APPLICABLE"

    def test_at_exactly_thirty_minutes_before_the_start_the_same_call_succeeds(self, api):
        """Moving the clock one minute later — to precisely `starts_at` less 30 minutes —
        admits the identical call, which is what makes the early edge inclusive.

        PRD §3.8: "Four preconditions apply: the registration must be `SCHEDULED`, or
        `ERR_INVALID_STATE`; the candidate's `status` must be `ACTIVE`, or
        `ERR_CANDIDATE_BARRED`; the logical clock must fall within the check-in window,
        which opens 30 minutes before the session's `starts_at` and closes at the
        session's `ends_at`, both ends inclusive, or `ERR_CHECKIN_WINDOW_CLOSED`; and the
        cited form's `status` must still be `PUBLISHED`, or `ERR_FORM_NOT_PUBLISHED`."

        Design: Corner/state_machines/check_in_before_the_thirty_minute_window_returns_checkin_window_closed
        """
        state = fx.pipeline_through_scheduled_seat(api)
        fx.set_clock(api, ONE_MINUTE_EARLY)
        api.check_in(state.registration_id, f.check_in_payload(), fx.EXAM_OPERATIONS)
        fx.set_clock(api, WINDOW_OPENS)

        seated = validate_success(api.check_in(
            state.registration_id, f.check_in_payload(checkin_note="window open"),
            fx.EXAM_OPERATIONS), 200)

        assert seated["seat_status"] == "CHECKED_IN"
        assert seated["score_status"] == "PENDING"
        ax.assert_exam_registration(seated)
