"""The interviewer calendar and the interview state machine."""

import pytest

from test_helpers import (
    CLASSIFICATION_REVIEWER_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    DEFAULT_CLOCK_STAMP,
    DutiesValidationStatus,
    ErrorId,
    InterviewStatus,
    RespondentType,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

HOLD_WINDOW = ("2026-09-10T14:00:00Z", "2026-09-10T15:00:00Z")
OVERLAPPING_WINDOW = ("2026-09-10T14:30:00Z", "2026-09-10T15:30:00Z")
ADJACENT_WINDOW = ("2026-09-10T15:00:00Z", "2026-09-10T16:00:00Z")


@pytest.fixture
def held_calendar(api, ca_engagement):
    """Interviewer int-7 already holds the 14:00-15:00 window on the only job."""
    hold = fixtures.book_interview(api, ca_engagement["position_id"], "int-7", HOLD_WINDOW)
    return {**ca_engagement, "hold": hold}


def _book_incumbent(api, position_id, window):
    return api.create_interview(
        factories.interview_payload(
            position_id,
            "int-7",
            window[0],
            window[1],
            respondent_type=RespondentType.INCUMBENT,
            respondent_ref="INC-1",
        ),
        COMPLIANCE_ANALYST_HEADERS,
    )


def test_overlapping_interviewer_window_is_rejected(api, held_calendar):
    """A window that genuinely intersects an existing hold is a double booking.

    PRD: "The requested half-open window from `scheduled_start_at` up to but not including
    `scheduled_end_at` must not intersect the window of any other interview held by the same
    `interviewer_user_id` whose `status` is `SCHEDULED`, `COMPLETED` or `ATTESTED`"

    Design: Difficulty/resource_temporal_overlap/interviewer_calendar_is_half_open_so_adjacent_windows_are_allowed
    """
    validate_error(
        _book_incumbent(api, held_calendar["position_id"], OVERLAPPING_WINDOW),
        ErrorId.INTERVIEWER_DOUBLE_BOOKED,
        409,
    )

    _, meta = validate_paginated(
        api.list_position_interviews(held_calendar["position_id"], COMPLIANCE_ANALYST_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"the rejected booking must not persist, got {meta['total_count']} rows"
    )
    assert (
        fixtures.read_interview(api, held_calendar["hold"]["id"])["status"]
        == InterviewStatus.SCHEDULED
    ), "the existing hold must be untouched"


def test_adjacent_interviewer_window_sharing_one_endpoint_is_allowed(api, held_calendar):
    """A window that starts exactly when the hold ends is back-to-back, not overlapping.

    PRD: "There is zero buffer: two windows that merely share an endpoint, where one ends exactly
    when the next begins, are back-to-back and permitted."

    Design: Difficulty/resource_temporal_overlap/interviewer_calendar_is_half_open_so_adjacent_windows_are_allowed
    """
    adjacent = validate_success(
        _book_incumbent(api, held_calendar["position_id"], ADJACENT_WINDOW), 201
    )

    assert adjacent["status"] == InterviewStatus.SCHEDULED, (
        f"the adjacent booking must be SCHEDULED, got {adjacent['status']}"
    )
    assert (
        fixtures.read_interview(api, held_calendar["hold"]["id"])["status"]
        == InterviewStatus.SCHEDULED
    ), "the earlier hold must remain SCHEDULED"

    rows, meta = validate_paginated(
        api.list_position_interviews(held_calendar["position_id"], COMPLIANCE_ANALYST_HEADERS)
    )
    assert meta["total_count"] == 2, f"exactly two interviews must exist, got {meta['total_count']}"
    assert len(rows) == 2, f"exactly two interviews must exist, got {len(rows)}"

    position = fixtures.read_position(api, held_calendar["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        f"booking alone validates nothing, got {position['duties_validation_status']}"
    )


def test_attest_before_complete_is_refused_with_interview_not_started(api, ca_engagement):
    """Attestation requires a completion first, and the specific error says so.

    PRD: "Attesting an interview that has never been completed -- one whose `completed_at` is
    still null -- is `ERR_INTERVIEW_NOT_STARTED`."

    Design: Corner/state_machines/attest_before_complete_is_refused_with_interview_not_started
    """
    interview = fixtures.book_interview(
        api,
        ca_engagement["position_id"],
        "int-12",
        ("2026-09-21T09:00:00Z", "2026-09-21T10:00:00Z"),
    )

    validate_error(
        api.attest_interview(interview["id"], COMPLIANCE_ANALYST_HEADERS),
        ErrorId.INTERVIEW_NOT_STARTED,
        409,
    )

    refused = fixtures.read_interview(api, interview["id"])
    assert refused["status"] == InterviewStatus.SCHEDULED, (
        f"the interview must stay SCHEDULED, got {refused['status']}"
    )
    assert refused["attested_at"] is None, (
        f"attested_at must stay null, got {refused['attested_at']!r}"
    )
    position = fixtures.read_position(api, ca_engagement["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        f"the duties picture must stay PENDING, got {position['duties_validation_status']}"
    )
    assert position["corroborated_supervises_headcount"] == 0, (
        "with no attested pair the corroborated headcount is 0, got "
        f"{position['corroborated_supervises_headcount']}"
    )


def test_voided_interview_is_terminal_and_rejects_further_transitions(api, ca_engagement):
    """VOIDED accepts no further trigger, and the void preserves the recorded account.

    PRD: "Voiding is permitted from `SCHEDULED`, from `COMPLETED` and from `ATTESTED` alike, and
    `VOIDED` is terminal."

    Design: Corner/state_machines/voided_interview_is_terminal_and_rejects_further_transitions
    """
    interview = fixtures.book_interview(
        api,
        ca_engagement["position_id"],
        "int-13",
        ("2026-09-22T09:00:00Z", "2026-09-22T10:00:00Z"),
    )
    fixtures.complete_interview(api, interview["id"], (46.0, 45, 3, True))
    fixtures.attest_interview(api, interview["id"])
    get_success_data(
        api.void_interview(
            interview["id"],
            {"void_reason": "RESPONDENT_LEFT_THE_ROLE"},
            CLASSIFICATION_REVIEWER_HEADERS,
        )
    )

    validate_error(
        api.attest_interview(interview["id"], COMPLIANCE_ANALYST_HEADERS),
        ErrorId.INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.complete_interview(
            interview["id"],
            factories.interview_completion_payload(46.0, 45, 3, True),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        ErrorId.INVALID_STATE_TRANSITION,
        409,
    )

    voided = fixtures.read_interview(api, interview["id"])
    assert voided["status"] == InterviewStatus.VOIDED, (
        f"the interview must stay VOIDED, got {voided['status']}"
    )
    assert voided["void_reason"] == "RESPONDENT_LEFT_THE_ROLE", (
        f"the void reason must be preserved, got {voided['void_reason']!r}"
    )
    assert voided["reported_exempt_duty_pct"] == 46.0, (
        "the void preserves the recorded account rather than blanking it, got "
        f"{voided['reported_exempt_duty_pct']}"
    )
    position = fixtures.read_position(api, ca_engagement["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        f"with no attested pair the duties are PENDING, got {position['duties_validation_status']}"
    )


def test_second_attest_on_the_same_interview_is_refused(api, ca_engagement):
    """ATTESTED has no self-loop, so a replayed attestation is an invalid transition.

    PRD: "Attesting the interview advances it `COMPLETED -> ATTESTED` and stamps `attested_at`
    from the logical clock."

    Design: Corner/state_machines/second_attest_on_the_same_interview_is_refused
    """
    interview = fixtures.book_interview(
        api,
        ca_engagement["position_id"],
        "int-14",
        ("2026-09-23T09:00:00Z", "2026-09-23T10:00:00Z"),
    )
    fixtures.complete_interview(api, interview["id"], (46.0, 45, 3, True))
    attested = fixtures.attest_interview(api, interview["id"])

    validate_error(
        api.attest_interview(interview["id"], COMPLIANCE_ANALYST_HEADERS),
        ErrorId.INVALID_STATE_TRANSITION,
        409,
    )

    replayed = fixtures.read_interview(api, interview["id"])
    assert replayed["status"] == InterviewStatus.ATTESTED, (
        f"the interview must stay ATTESTED, got {replayed['status']}"
    )
    assert replayed["attested_at"] == attested["attested_at"], (
        f"attested_at must be unchanged, got {replayed['attested_at']!r}"
    )
    position = fixtures.read_position(api, ca_engagement["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        "one attested side is not a pair, got "
        f"{position['duties_validation_status']}"
    )
    assert position["primary_duty_pct"] == 0.0, (
        f"with no duty statements the self-reported figure is 0.0, got {position['primary_duty_pct']}"
    )


def test_interview_completion_stamps_completed_at_from_the_logical_clock(api, ca_engagement):
    """Completion records the respondent's account and stamps the logical clock, not wall time.

    PRD: "The logical clock at that moment is stamped onto `completed_at`, and the interview's
    `version` is incremented."

    Design: Corner/endpoints/interview_complete_stamps_completed_at_from_the_logical_clock
    """
    interview = fixtures.book_interview(
        api,
        ca_engagement["position_id"],
        "int-31",
        ("2026-09-16T14:00:00Z", "2026-09-16T15:00:00Z"),
    )

    completed = validate_success(
        api.complete_interview(
            interview["id"],
            factories.interview_completion_payload(46.0, 45, 3, True),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        200,
    )

    assert completed["status"] == InterviewStatus.COMPLETED, (
        f"the interview must reach COMPLETED, got {completed['status']}"
    )
    assert completed["completed_at"] == DEFAULT_CLOCK_STAMP, (
        f"completed_at must read the logical clock, got {completed['completed_at']!r}"
    )
    assert completed["reported_exempt_duty_pct"] == 46.0, "the duty share must be recorded"
    assert completed["reported_weekly_hours"] == 45, "the hours must be recorded"
    assert completed["supervises_headcount"] == 3, "the supervised headcount must be recorded"
    assert completed["has_hire_fire_influence"] is True, "the hire-fire influence must be recorded"
    assert completed["attested_at"] is None, (
        f"attested_at stays null until attestation, got {completed['attested_at']!r}"
    )
    assert completed["version"] == 2, (
        f"completion is the first mutation, so version becomes 2, got {completed['version']}"
    )
    position = fixtures.read_position(api, ca_engagement["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        f"completion alone corroborates nothing, got {position['duties_validation_status']}"
    )


def test_second_manager_interview_on_the_same_position_is_rejected(api, ca_engagement):
    """Only one live interview per respondent type, but the other type is free to book.

    PRD: "At most one non-`VOIDED` interview may exist for a given position and `respondent_type`
    at a time, so a second live manager interview on the same position is
    `ERR_DUPLICATE_INTERVIEW_RESPONDENT`."

    Design: Corner/errors/second_manager_interview_on_the_same_position_is_rejected
    """
    position_id = ca_engagement["position_id"]
    fixtures.book_interview(
        api, position_id, "int-41", ("2026-09-17T09:00:00Z", "2026-09-17T10:00:00Z")
    )

    validate_error(
        api.create_interview(
            factories.interview_payload(
                position_id,
                "int-42",
                "2026-09-18T09:00:00Z",
                "2026-09-18T10:00:00Z",
                respondent_type=RespondentType.MANAGER,
                respondent_ref="MGR-2",
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        ErrorId.DUPLICATE_INTERVIEW_RESPONDENT,
        409,
    )

    incumbent = validate_success(
        api.create_interview(
            factories.interview_payload(
                position_id,
                "int-42",
                "2026-09-18T09:00:00Z",
                "2026-09-18T10:00:00Z",
                respondent_type=RespondentType.INCUMBENT,
                respondent_ref="INC-1",
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )
    assert incumbent["status"] == InterviewStatus.SCHEDULED, (
        f"the incumbent booking must succeed, got {incumbent['status']}"
    )

    rows, meta = validate_paginated(
        api.list_position_interviews(position_id, COMPLIANCE_ANALYST_HEADERS)
    )
    assert meta["total_count"] == 2, f"exactly two interviews must exist, got {meta['total_count']}"
    assert len(rows) == 2, f"exactly two interviews must exist, got {len(rows)}"
