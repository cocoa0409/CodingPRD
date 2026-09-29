"""Half-open juror session intervals, round containment, and the honorarium
proration that follows each booking."""

from test_helpers import (
    JURY_CHAIR_A,
    ApiErrorId,
    api_client,
    create_assignment_payload,
    fixtures,
    validate_error,
    validate_paginated,
)

WORK = {
    "title": "Ridge Line", "medium_category": "PAINTING",
    "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
}

MORNING_START = "2026-10-06T09:00:00Z"
MORNING_END = "2026-10-06T13:00:00Z"
AFTERNOON_START = "2026-10-06T13:00:00Z"
AFTERNOON_END = "2026-10-06T17:00:00Z"
OVERLAP_START = "2026-10-06T12:59:00Z"
OVERLAP_END = "2026-10-06T14:00:00Z"
OUTSIDE_START = "2026-10-13T09:00:00Z"
OUTSIDE_END = "2026-10-13T11:00:00Z"

SESSION_MINUTES = 240
HONORARIUM_CENTS = 50000
EQUAL_SHARE_CENTS = 25000


def _round_with_one_confirmed_juror():
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    fixtures.setup_submitted_entry(exhibition["id"], artist, [WORK])
    fixtures.enter_jurying(exhibition["id"])
    juror = fixtures.invite_and_confirm_juror(honorarium_cents=HONORARIUM_CENTS)
    jury_round = fixtures.create_jury_round(exhibition["id"], quorum_required=1)
    return exhibition, juror, jury_round


def _attempt_booking(jury_round_id, juror, start, end):
    """Book a session without asserting success, at the round's current version."""
    version = fixtures.read_jury_round(jury_round_id)["version"]
    return api_client.create_juror_assignment(
        jury_round_id,
        create_assignment_payload(
            juror["id"], version, session_start_at=start, session_end_at=end
        ),
        JURY_CHAIR_A,
    )


def test_back_to_back_sessions_touching_at_an_endpoint_are_both_booked(api):
    """PRD §3.4: "Because the intervals are half-open, a session ending at exactly
    the instant another begins does not collide, and back-to-back sittings are
    legal."

    Design: Difficulty/resource_temporal_overlap/juror_session_half_open_adjacency_allowed_overlap_rejected
    """
    _, juror, jury_round = _round_with_one_confirmed_juror()

    morning = fixtures.book_session(
        jury_round["id"], juror, MORNING_START, MORNING_END
    )
    assert morning["status"] == "BOOKED"
    assert morning["session_minutes"] == SESSION_MINUTES
    assert morning["scores_submitted_count"] == 0

    afternoon = fixtures.book_session(
        jury_round["id"], juror, AFTERNOON_START, AFTERNOON_END
    )
    assert afternoon["status"] == "BOOKED"
    assert afternoon["session_minutes"] == SESSION_MINUTES
    assert afternoon["session_start_at"] == MORNING_END, (
        "the second sitting begins at the instant the first ends"
    )

    _, meta = validate_paginated(
        api_client.list_juror_assignments(
            JURY_CHAIR_A, params={"juror_id": juror["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_session_overlapping_an_existing_sitting_by_a_minute_is_refused(api):
    """PRD §3.4: "And the session must not collide with the juror's existing
    commitments: if any other assignment of the same juror whose `status` is
    `BOOKED` or `COMPLETED` has a half-open interval intersecting the requested
    `[session_start_at, session_end_at)`, the booking is refused with
    `ERR_JUROR_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/juror_session_half_open_adjacency_allowed_overlap_rejected
    """
    _, juror, jury_round = _round_with_one_confirmed_juror()
    fixtures.book_session(jury_round["id"], juror, MORNING_START, MORNING_END)
    fixtures.book_session(jury_round["id"], juror, AFTERNOON_START, AFTERNOON_END)

    response = _attempt_booking(
        jury_round["id"], juror, OVERLAP_START, OVERLAP_END
    )
    validate_error(response, ApiErrorId.ERR_JUROR_SESSION_OVERLAP.value)

    _, meta = validate_paginated(
        api_client.list_juror_assignments(
            JURY_CHAIR_A, params={"juror_id": juror["id"]}
        )
    )
    assert meta["total_count"] == 2, "the colliding sitting was not stored"


def test_session_outside_the_rounds_window_is_refused_on_containment(api):
    """PRD §3.4: "The session must lie entirely inside the round's `[opens_at,
    closes_at]` window, or `ERR_SESSION_OUTSIDE_ROUND_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/juror_session_half_open_adjacency_allowed_overlap_rejected
    """
    _, juror, jury_round = _round_with_one_confirmed_juror()
    fixtures.book_session(jury_round["id"], juror, MORNING_START, MORNING_END)

    response = _attempt_booking(
        jury_round["id"], juror, OUTSIDE_START, OUTSIDE_END
    )
    validate_error(response, ApiErrorId.ERR_SESSION_OUTSIDE_ROUND_WINDOW.value)

    _, meta = validate_paginated(
        api_client.list_juror_assignments(
            JURY_CHAIR_A, params={"juror_id": juror["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_honorarium_is_prorated_evenly_across_two_equal_sittings(api):
    """PRD §3.4: "Each active assignment's `honorarium_share_cents` is then the
    juror's `honorarium_cents` multiplied by that assignment's `session_minutes`,
    divided by the total minutes, truncated downward to a whole cent."

    Design: Difficulty/resource_temporal_overlap/juror_session_half_open_adjacency_allowed_overlap_rejected
    """
    exhibition, juror, jury_round = _round_with_one_confirmed_juror()

    first = fixtures.book_session(
        jury_round["id"], juror, MORNING_START, MORNING_END
    )
    assert first["honorarium_share_cents"] == HONORARIUM_CENTS, (
        "a lone sitting carries the juror's whole agreed fee"
    )

    second = fixtures.book_session(
        jury_round["id"], juror, AFTERNOON_START, AFTERNOON_END
    )
    assert second["honorarium_share_cents"] == EQUAL_SHARE_CENTS

    reprorated = fixtures.read_assignment(first["id"])
    assert reprorated["honorarium_share_cents"] == EQUAL_SHARE_CENTS
    assert (
        reprorated["honorarium_share_cents"] + second["honorarium_share_cents"]
        == HONORARIUM_CENTS
    )

    committed = fixtures.read_juror(juror["id"])
    assert committed["honorarium_committed_cents"] == HONORARIUM_CENTS
    assert committed["assignment_count"] == 2
