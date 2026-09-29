"""Multi-hop consequences: a refusal that gates a resident, and a cancel that fans out."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_rounded, assert_values


def _two_refusals_then_started_third(api):
    """A resident one refusal short of review, with a third started session to document.

    A fourth session stays SCHEDULED and unenrolled so the gate can be probed on it.
    """
    resident, assessment = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Bernard Osei", "room_number": "220A",
                         "admission_date": "2026-02-14"},
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SOCIAL"],
        effective_date="2026-07-20",
    )
    plan = fx.active_plan(
        api,
        resident["id"],
        assessment["id"],
        targets=f.domain_targets(social=3),
    )
    program = fx.create_program(api, name="Music Hour", domain="SOCIAL")
    room = fx.create_room(api, name="Day Room", capacity=10, buffer_minutes=0)
    hours = [
        ("2026-08-04T10:00:00Z", "2026-08-04T11:00:00Z"),
        ("2026-08-04T12:00:00Z", "2026-08-04T13:00:00Z"),
        ("2026-08-04T14:00:00Z", "2026-08-04T15:00:00Z"),
        ("2026-08-04T16:00:00Z", "2026-08-04T17:00:00Z"),
    ]
    sessions = [
        fx.create_session(
            api, program["id"], room["id"], starts_at=start, ends_at=end
        )
        for start, end in hours
    ]
    records = [
        fx.enroll(api, session["id"], resident["id"]) for session in sessions[:3]
    ]
    for index in range(2):
        fx.advance_clock(api, hours[index][0])
        fx.start_session(api, sessions[index]["id"])
        fx.document_refusal(api, records[index]["id"])
    fx.advance_clock(api, hours[2][0])
    fx.start_session(api, sessions[2]["id"])
    return resident, plan, records[2], sessions[3]


def test_refusal_streak_cascade_depth_four(api, aide):
    """The third consecutive refusal walks the whole chain: the record turns REFUSED, the
    streak reaches the review threshold, the ACTIVE plan is driven into revision for a
    refusal pattern, and the resident is flagged for review.

    PRD: "If the recomputed streak has reached the review threshold and the resident
    holds a plan whose `status` is `ACTIVE`, that plan transitions `ACTIVE →
    UNDER_REVISION` with `review_reason` set to `REFUSAL_PATTERN`."

    Design: Difficulty/transitive_cascade/refusal_streak_cascade_depth_four
    """
    resident, plan, third_record, _ = _two_refusals_then_started_third(api)

    before = fx.read_resident(api, resident["id"])
    assert_values(before, refusal_streak=2, enrollment_gate="NONE",
                  care_plan_review_due=False)
    assert_values(fx.read_plan(api, plan["id"]), status="ACTIVE")

    documented = validate_success(
        api.document_participation(
            third_record["id"], f.refusal_payload(refusal_reason="NOT_INTERESTED"), aide
        ),
        200,
    )
    assert_values(documented, outcome="REFUSED")

    stored_resident = fx.read_resident(api, resident["id"])
    assert_values(
        stored_resident,
        refusal_streak=3,
        care_plan_review_due=True,
        enrollment_gate="THERAPIST_REVIEW",
    )

    stored_plan = fx.read_plan(api, plan["id"])
    assert_values(stored_plan, status="UNDER_REVISION", review_reason="REFUSAL_PATTERN",
                  revision_count=0)


def test_refusal_streak_cascade_depth_four_gates_next_enrollment(api, aide):
    """The final hop reaches the front line: with the gate raised, an aide's enrollment on
    an untouched still-SCHEDULED session is refused and that session gains no roster row.

    PRD: "While a resident's `enrollment_gate` reads `THERAPIST_REVIEW`, an enrollment
    succeeds only if the request carries a non-empty `gate_override_reason` **and** the
    acting `X-User-Role` is `RecreationTherapist`"

    Design: Difficulty/transitive_cascade/refusal_streak_cascade_depth_four
    """
    resident, _, third_record, spare_session = _two_refusals_then_started_third(api)

    fx.document_refusal(api, third_record["id"], refusal_reason="NOT_INTERESTED")

    response = api.create_enrollment(
        spare_session["id"], f.enrollment_payload(resident["id"]), aide
    )
    validate_error(response, ApiErrorId.ENROLLMENT_GATED, 409)

    stored_session = fx.read_session(api, spare_session["id"])
    assert_values(stored_session, status="SCHEDULED", enrolled_count=0)


def _cancellable_session_with_volunteer(api):
    """A SCHEDULED two-hour session carrying one PLANNED roster row and one CONFIRMED
    volunteer assignment, inside the ISO week the clock sits in."""
    fx.advance_clock(api, "2026-08-05T08:00:00Z")
    resident, _ = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Clara Bianchi", "room_number": "117A",
                         "admission_date": "2026-03-22"},
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["COGNITIVE"],
        effective_date="2026-07-20",
    )
    program = fx.create_program(
        api,
        name="Trivia Club",
        domain="COGNITIVE",
        max_supervision_tier="TIER_2",
        volunteer_eligible=True,
        required_screening_level="BASIC",
    )
    room = fx.create_room(api, name="Library", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-05T10:00:00Z",
        ends_at="2026-08-05T12:00:00Z",
    )
    record = fx.enroll(api, session["id"], resident["id"])
    volunteer = fx.cleared_volunteer(api, full_name="Sam Okafor")
    assignment = fx.assign_volunteer(api, volunteer["id"], session["id"])
    fx.confirm_assignment(api, assignment["id"])
    return session, record, volunteer, assignment


def test_session_cancel_cascade_depth_three(api, director):
    """Cancelling the session voids its roster row and withdraws its confirmed volunteer
    assignment under the system's own literal reason, in one request.

    PRD: "Every volunteer assignment on the session whose `status` is `PROPOSED` or
    `CONFIRMED` transitions to `WITHDRAWN` with `withdrawn_reason` stamped to the literal
    `SESSION_CANCELLED`"

    Design: Difficulty/transitive_cascade/session_cancel_cascade_depth_three
    """
    session, record, _, assignment = _cancellable_session_with_volunteer(api)

    assert_values(fx.read_record(api, record["id"]), status="PLANNED")
    assert_values(fx.read_assignment(api, assignment["id"]), status="CONFIRMED")

    cancelled = validate_success(
        api.session_status(
            session["id"], {"action": "CANCEL", "cancel_reason": "Heat advisory"}, director
        ),
        200,
    )
    assert_values(cancelled, status="CANCELLED")

    assert_values(fx.read_record(api, record["id"]), status="VOID")
    assert_values(
        fx.read_assignment(api, assignment["id"]),
        status="WITHDRAWN",
        withdrawn_reason="SESSION_CANCELLED",
    )


def test_session_cancel_cascade_depth_three_volunteer_totals(api, director):
    """The withdrawal fans on into the volunteer-level aggregate: the two committed hours
    leave the weekly figure, nothing is credited, and the volunteer stays CLEARED.

    PRD: "An assignment drops out of this figure the instant it becomes `COMPLETED` or
    `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/session_cancel_cascade_depth_three
    """
    session, _, volunteer, _ = _cancellable_session_with_volunteer(api)

    before = fx.read_volunteer(api, volunteer["id"])
    assert_rounded(before["scheduled_hours_week"], 2.0, 2)

    validate_success(
        api.session_status(
            session["id"], {"action": "CANCEL", "cancel_reason": "Heat advisory"}, director
        ),
        200,
    )

    after = fx.read_volunteer(api, volunteer["id"])
    assert_rounded(after["scheduled_hours_week"], 0.0, 2)
    assert_rounded(after["credited_service_hours"], 0.0, 2)
    assert_values(after, status="CLEARED")
