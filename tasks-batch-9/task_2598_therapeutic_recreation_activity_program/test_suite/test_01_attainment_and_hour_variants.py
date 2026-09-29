"""Two views of the same facts: plan attainment variants and volunteer hour variants."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_rounded, assert_values


def _refused_social_session(api):
    """An ACTIVE plan targeting one SOCIAL session, with that session refused."""
    resident, assessment = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Rose Alvarez", "room_number": "201A",
                         "admission_date": "2026-01-15"},
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SOCIAL"],
        effective_date="2026-07-20",
    )
    plan = fx.active_plan(
        api,
        resident["id"],
        assessment["id"],
        targets=f.domain_targets(social=1),
    )
    program = fx.create_program(api, name="Coffee Social", domain="SOCIAL")
    room = fx.create_room(api, name="Great Room", capacity=20, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-03T14:00:00Z",
        ends_at="2026-08-03T15:00:00Z",
    )
    record = fx.enroll(api, session["id"], resident["id"])
    fx.advance_clock(api, "2026-08-03T14:00:00Z")
    fx.start_session(api, session["id"])
    return resident, plan, record


def test_plan_attainment_credited_vs_offered_diverge(api, aide):
    """A documented refusal is a documented offer: the regulatory variant reaches 100.0
    while the clinical variant stays at 0.0 on the very same plan and cycle.

    PRD: "Under **offered attainment**, a record qualifies when its `outcome` is either
    `ATTENDED` or `REFUSED`, at any engagement level".

    Design: Difficulty/dual_variant_calc/plan_attainment_credited_vs_offered_diverge
    """
    resident, plan, record = _refused_social_session(api)

    response = api.document_participation(record["id"], f.refusal_payload(), aide)
    documented = validate_success(response, 200)
    assert_values(documented, outcome="REFUSED")

    stored_plan = fx.read_plan(api, plan["id"])
    assert_rounded(stored_plan["offered_attainment_pct"], 100.0, 1)
    assert_rounded(stored_plan["credited_attainment_pct"], 0.0, 1)
    assert_values(stored_plan, status="ACTIVE")


def test_plan_attainment_credited_vs_offered_diverge_resident_side(api, aide):
    """The same refusal that lifts the regulatory variant leaves the resident with a
    one-long refusal run and an engagement index of zero, because a refusal enters the
    engagement window worth nothing.

    PRD: "a refusal does enter the engagement window, worth zero points".

    Design: Difficulty/dual_variant_calc/plan_attainment_credited_vs_offered_diverge
    """
    resident, plan, record = _refused_social_session(api)

    validate_success(api.document_participation(record["id"], f.refusal_payload(), aide), 200)

    stored = fx.read_resident(api, resident["id"])
    assert_values(stored, refusal_streak=1)
    assert_rounded(stored["engagement_index"], 0.0, 3)


def _confirmed_two_hour_assignment(api):
    """A CLEARED volunteer holding a CONFIRMED assignment on an IN_PROGRESS session."""
    fx.advance_clock(api, "2026-08-05T08:00:00Z")
    resident, _ = fx.assessed_resident(
        api,
        resident_kwargs={"full_name": "Ana Reyes", "room_number": "118B",
                         "admission_date": "2026-02-02"},
        interest_domains=["CREATIVE"],
        effective_date="2026-07-20",
    )
    program = fx.create_program(
        api,
        name="Watercolor Studio",
        domain="CREATIVE",
        max_group_size=8,
        max_supervision_tier="TIER_2",
        volunteer_eligible=True,
        required_screening_level="FULL",
    )
    room = fx.create_room(api, name="Art Room", capacity=8, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-05T10:00:00Z",
        ends_at="2026-08-05T12:00:00Z",
    )
    record = fx.enroll(api, session["id"], resident["id"])
    volunteer = fx.cleared_volunteer(api, full_name="Dana Kim")
    assignment = fx.assign_volunteer(api, volunteer["id"], session["id"])
    fx.confirm_assignment(api, assignment["id"])
    fx.advance_clock(api, "2026-08-05T10:00:00Z")
    fx.start_session(api, session["id"])
    fx.document_attendance(api, record["id"])
    return volunteer, session, assignment


def test_volunteer_scheduled_vs_credited_hours_diverge(api, aide):
    """Closing documentation completes the assignment, which drops it out of the
    forward-looking weekly commitment and moves the same two hours into lifetime
    credited service.

    PRD: "An assignment drops out of this figure the instant it becomes `COMPLETED` or
    `WITHDRAWN`."

    Design: Difficulty/dual_variant_calc/volunteer_scheduled_vs_credited_hours_diverge
    """
    volunteer, session, assignment = _confirmed_two_hour_assignment(api)

    before = fx.read_volunteer(api, volunteer["id"])
    assert_rounded(before["scheduled_hours_week"], 2.0, 2)
    assert_rounded(before["credited_service_hours"], 0.0, 2)

    closed = validate_success(
        api.session_status(session["id"], {"action": "CLOSE_DOCUMENTATION"}, aide), 200
    )
    assert_values(closed, status="DOCUMENTED")

    after = fx.read_volunteer(api, volunteer["id"])
    assert_rounded(after["scheduled_hours_week"], 0.0, 2)
    assert_rounded(after["credited_service_hours"], 2.0, 2)


def test_volunteer_scheduled_vs_credited_hours_diverge_assignment_row(api, aide):
    """The assignment itself reaches COMPLETED and keeps the two hours derived from its
    session span, which is the quantity both variants read.

    PRD: "its `hours` is computed immediately as the session's `ends_at` minus its
    `starts_at`, expressed in hours and rounded half up to two decimal places".

    Design: Difficulty/dual_variant_calc/volunteer_scheduled_vs_credited_hours_diverge
    """
    volunteer, session, assignment = _confirmed_two_hour_assignment(api)

    validate_success(
        api.session_status(session["id"], {"action": "CLOSE_DOCUMENTATION"}, aide), 200
    )

    stored = fx.read_assignment(api, assignment["id"])
    assert_values(stored, status="COMPLETED")
    assert_rounded(stored["hours"], 2.0, 2)
