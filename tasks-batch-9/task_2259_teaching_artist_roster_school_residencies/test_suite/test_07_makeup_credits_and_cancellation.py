"""Cancellation and its make-up credit: the session-obligation ledger stays
conserved, and a cancelled row is beyond the reach of a confirmation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    cancel_session_as_coordinator,
    cancel_session_as_liaison,
    create_confirm_payload,
    read_residency,
    read_session,
    schedule_session,
    set_clock_to_default,
    set_roster_status,
    setup_active_residency,
    setup_approved_residency,
    validate_error,
)

RC = TEST_USERS["roster_coordinator_headers"]


# ==========================================================================
# The session-obligation ledger across a make-up round trip
# ==========================================================================
def _cancelled_school_session_with_a_credit() -> dict:
    """A ten-session allotment with one make-up-eligible cancellation, so one
    credit sits outstanding."""
    set_clock_to_default()
    scenario = setup_approved_residency(
        residency_overrides={"required_strands": ["CREATING"]}
    )
    assert scenario["residency"]["sessions_unscheduled_count"] == 10
    origin = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        start_time="09:00",
        end_time="10:00",
    )
    scenario["origin"] = cancel_session_as_coordinator(
        origin["id"], "SCHOOL_CLOSURE", note="boiler failure"
    )
    return scenario


def test_cancelling_an_eligible_session_moves_the_unit_into_the_credit_bucket(api):
    """PRD §2.12: "The **session obligation ledger** partitions the contracted
    allotment across five buckets: `sessions_unscheduled_count` (allotment not
    yet turned into a session row), `sessions_open_count` (sessions that are
    `PLANNED`, `CONFIRMED`, or `VACATED`), `sessions_delivered_count` (sessions
    that are `DELIVERED`), `sessions_forfeited_count` (cancelled sessions that
    earned no make-up credit, plus allotment written off at completion), and
    `makeup_credits_outstanding` (cancelled sessions that earned a make-up credit
    which has not yet been consumed)."
    PRD §2.12: "Cancelling a make-up-eligible session moves one unit from the
    open bucket to the outstanding-credit bucket; creating the make-up session
    moves it back to the open bucket."
    PRD §3.7: "From `PLANNED` there is nothing held, so the effects are just the
    eligibility flag and the ledger move: `sessions_open_count` loses one, and
    `makeup_credits_outstanding` gains one when the session was make-up-eligible
    while `sessions_forfeited_count` gains one when it was not."

    Design: Difficulty/compensating_invariant/makeup_credit_round_trip_preserves_session_obligation_invariant
    """
    scenario = _cancelled_school_session_with_a_credit()
    origin = scenario["origin"]
    assert origin["status"] == "CANCELLED_SCHOOL"
    assert origin["makeup_eligible"] is True

    residency = read_residency(scenario["residency"]["id"])
    assert residency["sessions_unscheduled_count"] == 9
    assert residency["sessions_open_count"] == 0
    assert residency["makeup_credits_outstanding"] == 1
    assert residency["sessions_forfeited_count"] == 0
    assert (
        residency["sessions_unscheduled_count"]
        + residency["sessions_open_count"]
        + residency["sessions_delivered_count"]
        + residency["sessions_forfeited_count"]
        + residency["makeup_credits_outstanding"]
        == 10
    ), "the five buckets must still partition the contracted allotment"


def test_creating_the_makeup_session_returns_the_unit_to_the_open_bucket(api):
    """PRD §3.6: "Creating the session updates the residency's ledger: a
    `REGULAR` session subtracts one from `sessions_unscheduled_count`, while a
    `MAKEUP` session leaves that counter alone and instead sets `makeup_consumed`
    to true on its origin session and subtracts one from
    `makeup_credits_outstanding`."
    PRD §3.6: "And the allotment must support the request: a `REGULAR` session
    requires `sessions_unscheduled_count` to be at least 1, or the refusal is
    `ERR_SESSION_ALLOTMENT_EXHAUSTED`; a `MAKEUP` session requires
    `makeup_credits_outstanding` to be at least 1 together with a matching origin
    session, and a make-up request that names a session which is not an
    unconsumed, make-up-eligible cancellation of the **same** residency — or
    which omits `makeup_for_session_id` altogether — is refused with
    `ERR_MAKEUP_CREDIT_UNAVAILABLE`."
    PRD §2.12: "Neither leg ever changes `contracted_session_count`."

    Design: Difficulty/compensating_invariant/makeup_credit_round_trip_preserves_session_obligation_invariant
    """
    scenario = _cancelled_school_session_with_a_credit()
    origin_id = scenario["origin"]["id"]

    makeup = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-29",
        start_time="09:00",
        end_time="10:00",
        session_type="MAKEUP",
        makeup_for_session_id=origin_id,
    )
    assert makeup["session_type"] == "MAKEUP"
    assert makeup["makeup_for_session_id"] == origin_id
    assert read_session(origin_id)["makeup_consumed"] is True, (
        "the credit must be marked consumed on its origin session"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["sessions_unscheduled_count"] == 9, (
        "a make-up draws no allotment, got "
        f"{residency['sessions_unscheduled_count']}"
    )
    assert residency["sessions_open_count"] == 1
    assert residency["makeup_credits_outstanding"] == 0
    assert residency["sessions_delivered_count"] == 0
    assert residency["sessions_forfeited_count"] == 0
    assert residency["encumbered_cents"] == 0
    assert (
        residency["sessions_unscheduled_count"]
        + residency["sessions_open_count"]
        + residency["sessions_delivered_count"]
        + residency["sessions_forfeited_count"]
        + residency["makeup_credits_outstanding"]
        == 10
    )


# ==========================================================================
# Confirming a session that no longer exists as a live row
# ==========================================================================
def _cancelled_session_of_a_suspended_artist() -> dict:
    """A session cancelled by the school, whose artist was then suspended."""
    set_clock_to_default()
    scenario = setup_active_residency()
    session = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        start_time="09:00",
        end_time="10:00",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    scenario["session"] = cancel_session_as_liaison(
        session["id"],
        scenario["school"]["id"],
        "SCHOOL_CLOSURE",
        note="boiler failure",
    )
    scenario["artist"] = set_roster_status(
        scenario["artist"]["id"], "SUSPENDED", reason="conduct review"
    )
    return scenario


def test_state_refusal_outranks_the_roster_standing_refusal_on_confirm(api):
    """PRD §2.9: "Checks are therefore evaluated in a fixed global order, and the
    **first** violated check decides the response."
    PRD §2.9: "8. The target row is in a state from which the requested
    transition is declared, on the addressed axis, with a legal reason or decision
    value for that transition — `ERR_INVALID_STATE_TRANSITION`."
    PRD §2.9: "11. The artist's roster standing permits the operation —
    `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`."
    PRD §3.6: "That artist's `roster_status` must be `ACTIVE`, or the refusal is
    `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_business_safety_on_confirm_of_cancelled_session
    """
    scenario = _cancelled_session_of_a_suspended_artist()
    assert scenario["session"]["status"] == "CANCELLED_SCHOOL"
    assert scenario["artist"]["roster_status"] == "SUSPENDED"

    res = api_client.confirm_session(
        scenario["session"]["id"],
        create_confirm_payload("Ms. Delgado", True),
        RC,
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409
    )

    session = read_session(scenario["session"]["id"])
    assert session["status"] == "CANCELLED_SCHOOL"
    assert session["classroom_teacher_name"] is None, (
        "the refused confirmation must persist nothing, got "
        f"{session['classroom_teacher_name']}"
    )
    assert session["encumbered_cents"] == 0


def test_suspension_leaves_an_already_cancelled_session_alone(api):
    """PRD §3.2: "Link two: every session of this artist whose status is
    `PLANNED` or `CONFIRMED` moves to `VACATED`, with the artist's identifier
    copied from `assigned_artist_id` into `vacated_artist_id` and
    `assigned_artist_id` set to null; each session that was `CONFIRMED` also
    releases its held amount, subtracting the session's held cents from the
    residency's `encumbered_cents`, zeroing the session's own held amount, and
    recomputing `available_cents`."
    PRD §3.7: "`makeup_eligible` becomes true when the reason is
    `SCHOOL_CLOSURE`, `TESTING_CONFLICT`, `ARTIST_ILLNESS`, or `ARTIST_NO_SHOW`,
    and false when it is `LOW_ENROLLMENT` or `RESIDENCY_DESCOPED`."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_business_safety_on_confirm_of_cancelled_session
    """
    scenario = _cancelled_session_of_a_suspended_artist()
    session = read_session(scenario["session"]["id"])
    assert session["status"] == "CANCELLED_SCHOOL", (
        f"a cancelled row is not vacatable, got {session['status']}"
    )
    assert session["assigned_artist_id"] == scenario["artist"]["id"], (
        "the suspension must not empty the artist reference of a cancelled "
        f"session, got {session['assigned_artist_id']}"
    )
    assert session["vacated_artist_id"] is None
    assert session["makeup_eligible"] is True

    residency = read_residency(scenario["residency"]["id"])
    assert residency["makeup_credits_outstanding"] == 1
    assert residency["vacated_session_count"] == 0
    assert residency["encumbered_cents"] == 0

    # The confirmation is still refused on the state of the row, not on the
    # artist's roster standing.
    validate_error(
        api_client.confirm_session(
            scenario["session"]["id"], create_confirm_payload("Ms. Delgado", True), RC
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        expected_status=409,
    )
