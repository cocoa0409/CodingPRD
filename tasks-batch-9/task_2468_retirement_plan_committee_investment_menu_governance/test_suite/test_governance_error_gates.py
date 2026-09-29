"""Rejection gates on the governance side of the plan: meetings, the
documentation gate, review presentation, the rolling scoring variant and the
onboarding join point.

Every check here asserts the specific error identifier the PRD names, because
the precedence ladder of PRD 2.12 only has meaning if the winning identifier is
pinned rather than the bare HTTP status.
"""

import pytest

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fields,
    assert_status,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    Paths,
    acceptance_payload,
    convene_payload,
    end_term_payload,
    scorecard_payload,
    seat_status_payload,
    training_completion_payload,
    training_waiver_payload,
)
from test_helpers.fixtures import (
    CLEAN_SCORECARDS,
    adjourn,
    adopt_ips,
    appoint_member,
    assign_training,
    carry_motion_unanimously,
    cast_vote,
    complete_training,
    create_seat,
    draft_ips,
    hold_meeting_and_carry_motion,
    move_motion,
    open_meeting,
    open_review,
    read_member,
    read_meeting,
    read_motion,
    read_plan,
    read_review,
    review_version,
    schedule_meeting,
    set_clock,
    setup_full_menu,
    sign_acceptance,
    submit_quarter_scorecards,
    submit_scorecard,
)
from test_helpers.test_users import (
    consultant_headers,
    member_headers,
    sponsor_headers,
)
from test_helpers.types import (
    FiduciaryTrainingStatus,
    IpsStatus,
    MeetingStatus,
    MemberStatus,
    MotionStatus,
    MotionSubjectType,
    ReviewStatus,
    ScoringVariant,
    SeatClass,
    SeatStatus,
    SeatStatusAction,
    TrainingModule,
    TrainingStatus,
    Vote,
)


# --------------------------------------------------------------------------
# Local readers for the few rows the shared helpers do not expose
# --------------------------------------------------------------------------


def _read_seat(client, seat_id):
    return get_success_data(client.get(Paths.seat(seat_id), sponsor_headers()))


def _read_ips(client, ips_id):
    return get_success_data(client.get(Paths.ips(ips_id), sponsor_headers()))


def _read_training_record(client, record_id):
    return get_success_data(
        client.get(Paths.training_record(record_id), sponsor_headers())
    )


def _appoint_independent(ctx, term_start_date="2026-10-01", term_end_date="2027-09-30"):
    """A fourth voting seat and the appointment that fills it.  The plan allows
    five voting seats (PRD 3.2 appointment ceiling), so the seat itself is
    always legal; the term interval is what the caller varies."""
    seat = create_seat(
        ctx.client,
        ctx.plan_id,
        seat_code="S-IND",
        seat_class=SeatClass.INDEPENDENT,
        voting=True,
        seat_index=4,
    )
    member = appoint_member(
        ctx.client,
        seat["id"],
        member_name="Dana Ruiz",
        person_email="dana.ruiz@example.com",
        term_start_date=term_start_date,
        term_end_date=term_end_date,
    )
    ctx.seats["independent"] = seat
    ctx.members["independent"] = member
    return seat, member


def _clear_required_training(ctx, member_id):
    """Complete both required modules (PRD 3.2 required module set) so the only
    open activation preconditions left are the seat and the term interval."""
    for module in TrainingModule.REQUIRED:
        record = assign_training(ctx.client, member_id, module_code=module)
        complete_training(ctx.client, record["id"], member_id, 95.00)


# --------------------------------------------------------------------------
# PRD 3.4 meeting gates and the PRD 3.2 vote lock
# --------------------------------------------------------------------------


def test_convening_under_a_draft_charter_is_refused(api, committee):
    """A quorate roster cannot convene a meeting while the plan's charter is
    still DRAFT.

    Design: Corner/errors/the_meeting_and_documentation_gates_fire_in_declaration_order_and_the_vote_lock_outlives_the_ballot
    """
    meeting = schedule_meeting(committee, "2026-08-04")

    response = api.post(
        Paths.convene(meeting["id"]),
        convene_payload(committee.member_ids),
        committee.chair,
    )
    validate_error(response, ApiErrorId.CHARTER_NOT_ADOPTED)

    unchanged = read_meeting(api, meeting["id"])
    assert_status(unchanged, MeetingStatus.SCHEDULED)
    assert_fields(unchanged, quorum_met=False, charter_version_pinned=None)


def test_convening_without_the_acting_chair_on_the_roster_is_refused(
    api, governed_plan
):
    """The chair who convenes must appear in the attendee roster.

    Design: Corner/errors/the_meeting_and_documentation_gates_fire_in_declaration_order_and_the_vote_lock_outlives_the_ballot
    """
    meeting = schedule_meeting(governed_plan, "2026-08-04")
    without_the_chair = [
        governed_plan.members["finance"]["id"],
        governed_plan.members["hr"]["id"],
    ]

    response = api.post(
        Paths.convene(meeting["id"]),
        convene_payload(without_the_chair),
        governed_plan.chair,
    )
    validate_error(response, ApiErrorId.CHAIR_NOT_PRESENT)

    unchanged = read_meeting(api, meeting["id"])
    assert_status(unchanged, MeetingStatus.SCHEDULED)
    assert_fields(unchanged, quorum_met=False)


def test_a_second_meeting_cannot_convene_while_one_is_in_session(api, governed_plan):
    """Only one meeting on a plan may sit at a time.

    Design: Corner/errors/the_meeting_and_documentation_gates_fire_in_declaration_order_and_the_vote_lock_outlives_the_ballot
    """
    sitting = open_meeting(governed_plan, "2026-08-04")
    assert_status(sitting, MeetingStatus.IN_SESSION)
    assert_fields(sitting, quorum_met=True, voting_attendee_count=3)

    second = schedule_meeting(governed_plan, "2026-08-05")
    response = api.post(
        Paths.convene(second["id"]),
        convene_payload(governed_plan.member_ids),
        governed_plan.chair,
    )
    validate_error(response, ApiErrorId.MEETING_IN_SESSION)

    assert_status(read_meeting(api, second["id"]), MeetingStatus.SCHEDULED)


def test_a_filled_seat_cannot_be_suspended_while_a_meeting_sits(api, governed_plan):
    """The same identifier that blocks a second convening also blocks the
    FILLED to SUSPENDED seat transition (PRD 3.2 seat status).

    Design: Corner/errors/the_meeting_and_documentation_gates_fire_in_declaration_order_and_the_vote_lock_outlives_the_ballot
    """
    open_meeting(governed_plan, "2026-08-04")
    hr_seat_id = governed_plan.seats["hr"]["id"]

    response = api.post(
        Paths.seat_status(hr_seat_id),
        seat_status_payload(SeatStatusAction.SUSPEND),
        sponsor_headers(),
    )
    validate_error(response, ApiErrorId.MEETING_IN_SESSION)

    assert_status(_read_seat(api, hr_seat_id), SeatStatus.FILLED)


def test_adopting_a_statement_before_the_minutes_are_approved_is_refused(
    api, governed_plan
):
    """A carried motion is not enough: the meeting that carried it must have
    reached MINUTES_APPROVED (PRD 3.3 adoption gate).

    Design: Corner/errors/the_meeting_and_documentation_gates_fire_in_declaration_order_and_the_vote_lock_outlives_the_ballot
    """
    statement = draft_ips(api, governed_plan.plan_id, version_label="IPS-2026-X1")
    meeting = open_meeting(governed_plan, "2026-08-04")
    motion = carry_motion_unanimously(
        governed_plan,
        meeting["id"],
        MotionSubjectType.IPS_ADOPTION,
        statement["id"],
    )
    assert_status(motion, MotionStatus.CARRIED)

    response = api.post(
        Paths.ips_adopt(statement["id"]),
        {"approving_motion_id": motion["id"]},
        governed_plan.chair,
    )
    validate_error(response, ApiErrorId.MINUTES_NOT_APPROVED)

    unchanged = _read_ips(api, statement["id"])
    assert_status(unchanged, IpsStatus.DRAFT)
    assert_fields(unchanged, approving_motion_id=None)


def test_a_term_cannot_end_while_an_open_motion_holds_that_members_vote(
    api, governed_plan
):
    """The vote lock outlives the ballot: it holds while the motion is OPEN and
    releases the moment adjournment withdraws it (PRD 3.4 adjourning).

    Design: Corner/errors/the_meeting_and_documentation_gates_fire_in_declaration_order_and_the_vote_lock_outlives_the_ballot
    """
    statement = draft_ips(api, governed_plan.plan_id, version_label="IPS-2026-X1")
    meeting = open_meeting(governed_plan, "2026-08-04")
    motion = move_motion(
        governed_plan,
        meeting["id"],
        MotionSubjectType.IPS_ADOPTION,
        statement["id"],
    )
    hr_member_id = governed_plan.members["hr"]["id"]
    hr_seat_id = governed_plan.seats["hr"]["id"]
    cast_vote(governed_plan, motion["id"], hr_member_id, Vote.FOR)

    locked = api.post(
        Paths.end_term(hr_member_id), end_term_payload("RESIGNATION"), sponsor_headers()
    )
    validate_error(locked, ApiErrorId.OPEN_MOTION_VOTE_LOCK)
    assert_status(read_member(api, hr_member_id), MemberStatus.ACTIVE)
    assert_status(_read_seat(api, hr_seat_id), SeatStatus.FILLED)
    assert_fields(read_plan(api, governed_plan.plan_id), documented_acceptance_count=3)

    adjourn(governed_plan, meeting["id"])
    assert_status(read_motion(api, motion["id"]), MotionStatus.WITHDRAWN)

    released = api.post(
        Paths.end_term(hr_member_id), end_term_payload("RESIGNATION"), sponsor_headers()
    )
    resigned = get_success_data(released)
    assert_status(resigned, MemberStatus.RESIGNED)
    assert_status(_read_seat(api, hr_seat_id), SeatStatus.VACANT)
    assert_fields(read_plan(api, governed_plan.plan_id), documented_acceptance_count=2)


# --------------------------------------------------------------------------
# PRD 3.5 presentation gates
# --------------------------------------------------------------------------


def test_presenting_a_review_with_no_pinned_meeting_is_refused(api, full_menu):
    """The review's own meeting pointer is what is checked, not whether a
    quorate meeting happens to be sitting.

    Design: Corner/errors/presenting_a_review_needs_a_pinned_meeting_first_and_then_a_scorecard_for_every_seated_slot
    """
    open_review(full_menu, 0)
    submit_quarter_scorecards(full_menu)
    open_meeting(full_menu, "2026-08-10")
    review_id = full_menu.review["id"]

    response = api.post(Paths.review_present(review_id), {}, consultant_headers())
    validate_error(response, ApiErrorId.REVIEW_MEETING_MISSING)

    unchanged = read_review(api, review_id)
    assert_status(unchanged, ReviewStatus.SCORING)
    assert_fields(unchanged, meeting_id=None)


def test_presenting_a_review_with_one_seated_slot_unscored_is_refused(api, full_menu):
    """Coverage counts seated asset-class slots, so the fifth slot's scorecard
    is mandatory before the review can be presented.

    Design: Corner/errors/presenting_a_review_needs_a_pinned_meeting_first_and_then_a_scorecard_for_every_seated_slot
    """
    open_review(full_menu, 0)
    for fund_key in ("lc_a", "bond", "small", "intl"):
        submit_scorecard(full_menu, fund_key, CLEAN_SCORECARDS[fund_key])
    meeting = open_meeting(full_menu, "2026-08-10")
    review_id = full_menu.review["id"]

    response = api.post(
        Paths.review_present(review_id),
        {"meeting_id": meeting["id"]},
        consultant_headers(),
    )
    validate_error(response, ApiErrorId.SCORECARD_COVERAGE_INCOMPLETE)

    partial = read_review(api, review_id)
    assert_status(partial, ReviewStatus.SCORING)
    assert_fields(
        partial, scorecard_count=4, submitted_scorecard_count=4, meeting_id=None
    )

    fifth = api.post(
        Paths.SCORECARDS,
        scorecard_payload(
            review_id,
            full_menu.fund("tips")["id"],
            review_version(api, review_id),
            **CLEAN_SCORECARDS["tips"],
        ),
        consultant_headers(),
    )
    validate_success(fifth, 201)

    presented = get_success_data(
        api.post(
            Paths.review_present(review_id),
            {"meeting_id": meeting["id"]},
            consultant_headers(),
        )
    )
    assert_status(presented, ReviewStatus.PENDING_MINUTES)
    assert_fields(presented, meeting_id=meeting["id"], submitted_scorecard_count=5)


# --------------------------------------------------------------------------
# PRD 3.5 rolling-since-watch variant
# --------------------------------------------------------------------------


@pytest.fixture
def rolling_menu(api):
    """A seated menu whose adopted statement has been superseded by one scoring
    on the rolling-since-watch variant, with a quarter-0 review opened under
    it.  No review has ever finalized, so every fund is still CLEAR."""
    ctx = setup_full_menu(api)
    superseded_id = ctx.ips_id
    rolling = draft_ips(
        api,
        ctx.plan_id,
        version_label="IPS-2026-R",
        scoring_variant=ScoringVariant.ROLLING_SINCE_WATCH,
    )
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.IPS_ADOPTION,
        rolling["id"],
        meeting_date="2026-08-11",
        minutes_doc_ref="MIN-2026-Q0-R01",
        key="rolling",
    )
    ctx.ips = adopt_ips(ctx, rolling["id"], motion["id"])
    ctx.superseded_ips_id = superseded_id
    open_review(ctx, 0)
    return ctx


def test_rolling_since_watch_refuses_a_fund_that_never_went_on_watch(
    api, rolling_menu
):
    """Adopting the rolling variant changes what a scorecard means: a fund with
    no watch history can no longer be scored at all.

    Design: Corner/errors/the_rolling_since_watch_variant_refuses_to_score_a_fund_that_never_went_on_watch
    """
    assert_status(_read_ips(api, rolling_menu.ips_id), IpsStatus.ADOPTED)
    superseded = _read_ips(api, rolling_menu.superseded_ips_id)
    assert_status(superseded, IpsStatus.SUPERSEDED)
    assert_fields(superseded, superseded_quarter_index=0)

    review_id = rolling_menu.review["id"]
    opened = read_review(api, review_id)
    assert_status(opened, ReviewStatus.DRAFT)
    assert_fields(
        opened,
        ips_id=rolling_menu.ips_id,
        scoring_variant=ScoringVariant.ROLLING_SINCE_WATCH,
    )

    response = api.post(
        Paths.SCORECARDS,
        scorecard_payload(
            review_id,
            rolling_menu.fund("lc_a")["id"],
            opened["version"],
            **CLEAN_SCORECARDS["lc_a"],
        ),
        consultant_headers(),
    )
    validate_error(response, ApiErrorId.ROLLING_WINDOW_UNAVAILABLE)

    after = read_review(api, review_id)
    assert_status(after, ReviewStatus.DRAFT)
    assert_fields(
        after,
        version=opened["version"],
        scorecard_count=0,
        submitted_scorecard_count=0,
    )


def test_supplying_the_rolling_fields_does_not_rescue_a_clear_fund(api, rolling_menu):
    """The gate is the fund's watch history, not the payload's completeness, so
    populating both rolling inputs yields the identical refusal.

    Design: Corner/errors/the_rolling_since_watch_variant_refuses_to_score_a_fund_that_never_went_on_watch
    """
    review_id = rolling_menu.review["id"]
    inputs = dict(CLEAN_SCORECARDS["lc_a"])
    inputs["rolling_since_watch_return_bps"] = 600
    inputs["rolling_since_watch_benchmark_bps"] = 500

    response = api.post(
        Paths.SCORECARDS,
        scorecard_payload(
            review_id,
            rolling_menu.fund("lc_a")["id"],
            review_version(api, review_id),
            **inputs,
        ),
        consultant_headers(),
    )
    validate_error(response, ApiErrorId.ROLLING_WINDOW_UNAVAILABLE)

    assert_status(read_review(api, review_id), ReviewStatus.DRAFT)


# --------------------------------------------------------------------------
# PRD 3.2 onboarding: training, acceptance and the activation join point
# --------------------------------------------------------------------------


def test_the_fiduciary_duties_module_can_never_be_waived(api, governed_plan):
    """A waiver may never close out FIDUCIARY_DUTIES, however long its basis,
    while IPS_MECHANICS accepts one.

    Design: Corner/errors/the_onboarding_join_point_refuses_a_fourth_member_module_by_module_seat_by_seat_and_day_by_day
    """
    _seat, member = _appoint_independent(governed_plan, "2026-01-01", "2027-12-31")
    duties = assign_training(
        api, member["id"], module_code=TrainingModule.FIDUCIARY_DUTIES
    )

    refused = api.post(
        Paths.training_complete(duties["id"]),
        training_waiver_payload(
            waiver_basis="holds an ASPPA fiduciary credential renewed in 2026"
        ),
        sponsor_headers(),
    )
    validate_error(refused, ApiErrorId.MODULE_NOT_WAIVABLE)

    untouched = _read_training_record(api, duties["id"])
    assert_status(untouched, TrainingStatus.ASSIGNED)
    assert_fields(untouched, completed_quarter_index=None)

    mechanics = assign_training(
        api, member["id"], module_code=TrainingModule.IPS_MECHANICS
    )
    waived = get_success_data(
        api.post(
            Paths.training_complete(mechanics["id"]),
            training_waiver_payload(
                waiver_basis="co-authored the plan's prior statement as counsel"
            ),
            sponsor_headers(),
        )
    )
    assert_status(waived, TrainingStatus.WAIVED)
    assert_fields(waived, completed_quarter_index=0, score_pct=None)


def test_a_completion_below_the_score_floor_is_refused_and_the_retry_is_legal(
    api, governed_plan
):
    """A completion scoring 79.99 is refused and leaves the record ASSIGNED, so
    the same member may resubmit at the 80 floor.

    Design: Corner/errors/the_onboarding_join_point_refuses_a_fourth_member_module_by_module_seat_by_seat_and_day_by_day
    """
    _seat, member = _appoint_independent(governed_plan, "2026-01-01", "2027-12-31")
    duties = assign_training(
        api, member["id"], module_code=TrainingModule.FIDUCIARY_DUTIES
    )
    assert_status(read_member(api, member["id"]), MemberStatus.TRAINING_ASSIGNED)

    refused = api.post(
        Paths.training_complete(duties["id"]),
        training_completion_payload(79.99),
        member_headers(member["id"]),
    )
    validate_error(refused, ApiErrorId.TRAINING_SCORE_INSUFFICIENT)

    untouched = _read_training_record(api, duties["id"])
    assert_status(untouched, TrainingStatus.ASSIGNED)
    assert_fields(untouched, completed_quarter_index=None, score_pct=None)

    accepted = get_success_data(
        api.post(
            Paths.training_complete(duties["id"]),
            training_completion_payload(80.00),
            member_headers(member["id"]),
        )
    )
    assert_status(accepted, TrainingStatus.COMPLETED)
    assert_fields(accepted, completed_quarter_index=0)


def test_a_second_acceptance_signature_is_refused(api, governed_plan):
    """Acceptance is signed once; a re-sign must not overwrite the reference or
    double-count the plan's documented acceptances.

    Design: Corner/errors/the_onboarding_join_point_refuses_a_fourth_member_module_by_module_seat_by_seat_and_day_by_day
    """
    _seat, member = _appoint_independent(governed_plan, "2026-01-01", "2027-12-31")
    first = sign_acceptance(
        api, member["id"], acceptance_doc_ref="ACC-2026-IND-01"
    )
    assert_status(first, MemberStatus.ACCEPTANCE_PENDING)
    assert_fields(read_plan(api, governed_plan.plan_id), documented_acceptance_count=4)

    response = api.post(
        Paths.acceptance(member["id"]),
        acceptance_payload(acceptance_doc_ref="ACC-2026-IND-02"),
        member_headers(member["id"]),
    )
    validate_error(response, ApiErrorId.ACCEPTANCE_ALREADY_SIGNED)

    unchanged = read_member(api, member["id"])
    assert_fields(
        unchanged,
        acceptance_doc_ref="ACC-2026-IND-01",
        acceptance_signed_at=first["acceptance_signed_at"],
    )
    assert_fields(read_plan(api, governed_plan.plan_id), documented_acceptance_count=4)


def test_activation_is_refused_while_the_seat_is_suspended(api, governed_plan):
    """With acceptance on file and training current, a suspended seat is what
    answers the activation attempt.

    Design: Corner/errors/the_onboarding_join_point_refuses_a_fourth_member_module_by_module_seat_by_seat_and_day_by_day
    """
    seat, member = _appoint_independent(governed_plan, "2026-01-01", "2027-12-31")
    _clear_required_training(governed_plan, member["id"])
    sign_acceptance(api, member["id"], acceptance_doc_ref="ACC-2026-IND-01")
    ready = read_member(api, member["id"])
    assert_fields(ready, fiduciary_training_status=FiduciaryTrainingStatus.CURRENT)

    suspended = get_success_data(
        api.post(
            Paths.seat_status(seat["id"]),
            seat_status_payload(SeatStatusAction.SUSPEND),
            sponsor_headers(),
        )
    )
    assert_status(suspended, SeatStatus.SUSPENDED)
    assert_status(read_member(api, member["id"]), MemberStatus.ACCEPTANCE_PENDING)

    response = api.post(Paths.activate(member["id"]), {}, sponsor_headers())
    validate_error(response, ApiErrorId.SEAT_NOT_ACTIVE)
    assert_status(read_member(api, member["id"]), MemberStatus.ACCEPTANCE_PENDING)

    reinstated = get_success_data(
        api.post(
            Paths.seat_status(seat["id"]),
            seat_status_payload(SeatStatusAction.REINSTATE),
            sponsor_headers(),
        )
    )
    assert_status(reinstated, SeatStatus.FILLED)


def test_activation_is_refused_until_the_term_interval_contains_the_clock(
    api, governed_plan
):
    """The term interval is the last gate on the join point, and only a clock
    move can close it.

    Design: Corner/errors/the_onboarding_join_point_refuses_a_fourth_member_module_by_module_seat_by_seat_and_day_by_day
    """
    _seat, member = _appoint_independent(governed_plan, "2026-10-01", "2027-09-30")
    _clear_required_training(governed_plan, member["id"])
    sign_acceptance(api, member["id"], acceptance_doc_ref="ACC-2026-IND-01")

    early = api.post(Paths.activate(member["id"]), {}, sponsor_headers())
    validate_error(early, ApiErrorId.TERM_NOT_IN_EFFECT)
    assert_status(read_member(api, member["id"]), MemberStatus.ACCEPTANCE_PENDING)
    assert_fields(read_plan(api, governed_plan.plan_id), documented_acceptance_count=4)

    set_clock(api, "2026-10-01T09:00:00Z")
    activated = get_success_data(
        api.post(Paths.activate(member["id"]), {}, sponsor_headers())
    )
    assert_status(activated, MemberStatus.ACTIVE)
    assert_fields(read_plan(api, governed_plan.plan_id), documented_acceptance_count=4)
