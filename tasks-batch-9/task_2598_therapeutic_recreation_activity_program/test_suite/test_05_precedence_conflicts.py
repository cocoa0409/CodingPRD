"""Requests that violate two ranked rules at once must answer with the higher rank only."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_rounded, assert_values


def _cancelled_session_and_tier_three_resident(api):
    """A CANCELLED single-staff session plus a TIER_3 resident who would need three staff."""
    resident, _ = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Walter Krupa", "room_number": "230A",
                         "admission_date": "2026-01-30"},
        cognitive_level="SEVERE_IMPAIRMENT",
        functional_mobility="ASSIST_2",
        interest_domains=["PHYSICAL"],
        preferred_group_size="SOLO",
        effective_date="2026-07-20",
    )
    program = fx.create_program(
        api,
        name="Range of Motion",
        domain="PHYSICAL",
        staffing_ratio_denominator=1,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    room = fx.create_room(api, name="Therapy Gym", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-07T10:00:00Z",
        ends_at="2026-08-07T11:00:00Z",
        assigned_staff_count=1,
    )
    fx.cancel_session(api, session["id"], cancel_reason="Staff callout")
    return resident, session


def test_state_outranks_staffing_on_cancelled_session(api, aide):
    """Enrolling a TIER_3 resident into a cancelled single-staff session breaks both the
    state precondition and the staffing quota; only the state error may surface.

    PRD: "Every write endpoint evaluates its applicable rules in one strict,
    globally-ordered sequence and returns the **first** violated rule's error identifier."

    Design: Difficulty/priority_pair_validation_conflict/state_outranks_staffing_on_cancelled_session
    """
    resident, session = _cancelled_session_and_tier_three_resident(api)
    assert_values(fx.read_resident(api, resident["id"]), supervision_tier="TIER_3")

    response = api.create_enrollment(
        session["id"], f.enrollment_payload(resident["id"]), aide
    )
    validate_error(response, ApiErrorId.SESSION_INVALID_STATE, 409)


def test_state_outranks_staffing_on_cancelled_session_leaves_no_trace(api, aide):
    """The rejected enrollment leaves the cancelled session's roster and supervision load
    at zero, so the ratio arithmetic never ran against it.

    PRD: "The session's own `enrolled_count`, `weighted_supervision_load`, and
    `required_staff_count` are recomputed — all three reach zero once every row on the
    roster is `VOID`."

    Design: Difficulty/priority_pair_validation_conflict/state_outranks_staffing_on_cancelled_session
    """
    resident, session = _cancelled_session_and_tier_three_resident(api)

    validate_error(
        api.create_enrollment(session["id"], f.enrollment_payload(resident["id"]), aide),
        ApiErrorId.SESSION_INVALID_STATE,
        409,
    )

    stored = fx.read_session(api, session["id"])
    assert_values(stored, status="CANCELLED", enrolled_count=0)
    assert_rounded(stored["weighted_supervision_load"], 0.0, 2)


def _gated_resident_already_enrolled(api):
    """A resident holding a live PLANNED row whose plan has since gone UNDER_REVISION."""
    resident, assessment, plan = fx.resident_with_active_plan(
        api,
        targets=f.domain_targets(social=2),
        resident_kwargs={"full_name": "Nadia Farrow", "room_number": "225B",
                         "admission_date": "2026-02-08"},
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SOCIAL"],
        effective_date="2026-07-20",
    )
    program = fx.create_program(api, name="Tea Time", domain="SOCIAL")
    room = fx.create_room(api, name="Sun Porch", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-08T10:00:00Z",
        ends_at="2026-08-08T11:00:00Z",
    )
    record = fx.enroll(api, session["id"], resident["id"])
    fx.get_success_data(
        api.transition_activity_plan(
            plan["id"],
            {"action": "REVISE", "review_reason": "THERAPIST_REQUEST"},
            fx.THERAPIST_HEADERS,
        )
    )
    return resident, session, record


def test_safety_gate_outranks_duplicate_enrollment(api, aide):
    """A repeat enrollment on the same session while the review gate is up violates both
    the clinical gate and the duplicate rule; the clinical gate is the higher rank.

    PRD: "Because the ranks are globally distinct, any request that violates two rules at
    once has exactly one determinate answer."

    Design: Difficulty/priority_pair_validation_conflict/safety_gate_outranks_duplicate_enrollment
    """
    resident, session, _ = _gated_resident_already_enrolled(api)
    assert_values(
        fx.read_resident(api, resident["id"]), enrollment_gate="THERAPIST_REVIEW"
    )

    response = api.create_enrollment(
        session["id"], f.enrollment_payload(resident["id"]), aide
    )
    validate_error(response, ApiErrorId.ENROLLMENT_GATED, 409)


def test_safety_gate_outranks_duplicate_enrollment_roster_unchanged(api, aide):
    """The original roster row survives untouched: the session still counts exactly one
    enrollment and that record is still PLANNED.

    PRD: "anything else — an aide trying, a therapist trying without a reason, an empty
    reason string — is refused with `ERR_ENROLLMENT_GATED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_gate_outranks_duplicate_enrollment
    """
    resident, session, record = _gated_resident_already_enrolled(api)

    validate_error(
        api.create_enrollment(session["id"], f.enrollment_payload(resident["id"]), aide),
        ApiErrorId.ENROLLMENT_GATED,
        409,
    )

    assert_values(fx.read_session(api, session["id"]), enrolled_count=1)
    assert_values(fx.read_record(api, record["id"]), status="PLANNED")
