"""Role boundaries: who may write what, and in which order the gates answer.

PRD §2.1 splits six roles as a segregation-of-duties control, and PRD §2.12
orders the gates that guard every write: user context at priority 10, role
authorisation at 20, committee identity at 25, self-identity on voting at 27,
existence at 30 and only then request shape (38) and state (42).  The tests
below therefore aim every refused call at state that would *also* have been
refused later, so a 403 proves the earlier rung answered first.
"""

import pytest

from test_helpers.api_client import ApiClient, build_user_headers
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_fields,
    assert_ratio,
    assert_status,
    find_by,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    Paths,
    acceptance_payload,
    convene_payload,
    engagement_payload,
    meeting_payload,
    motion_payload,
    notice_issue_payload,
    plan_payload,
    scorecard_payload,
    seat_fund_payload,
    vote_payload,
)
from test_helpers.fixtures import (
    Ctx,
    create_fund,
    create_levelization_run,
    open_meeting,
    open_review,
    read_fund,
    read_meeting,
    read_member,
    read_motion,
    read_plan,
    read_proposal,
    read_review,
    read_run,
    read_slot,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import (
    TestUsers,
    auditor_headers,
    chair_headers,
    consultant_headers,
    member_headers,
    recordkeeper_headers,
    sponsor_headers,
)
from test_helpers.types import (
    FeeDisclosureStatus,
    FundMenuStatus,
    LevelizationMethod,
    LevelizationStatus,
    MeetingStatus,
    MemberStatus,
    MotionStatus,
    MotionSubjectType,
    ProposalStatus,
    ReviewStatus,
    Role,
    ScorecardStatus,
    SlotStatus,
    TrainingStatus,
    WatchStatus,
)

#: The instant inside the documented blackout window (PRD §3.7).
INSIDE_BLACKOUT = "2026-09-02T00:00:00Z"


@pytest.fixture
def cross_role_targets(api: ApiClient, submitted_replacement: Ctx):
    """A submitted replacement plus two more half-finished pieces of work — a
    DRAFT levelization run and an OPEN motion moved by the finance member — so
    that every wrong-role call below also has a later gate waiting for it."""
    ctx = submitted_replacement
    run = create_levelization_run(ctx, 0, LevelizationMethod.PER_CAPITA)
    meeting = open_meeting(ctx, "2026-08-19", 0, key="rbac")
    finance_id = ctx.members["finance"]["id"]
    motion = validate_success(
        api.post(
            Paths.MOTIONS,
            motion_payload(
                meeting["id"],
                MotionSubjectType.FUND_REPLACEMENT,
                ctx.proposals["proposal"]["id"],
            ),
            member_headers(finance_id),
        ),
        201,
    )
    return ctx, run, motion


def test_the_header_rung_answers_before_the_role_rung(api: ApiClient, adopted_ips: Ctx):
    """An unrecognised role name and an empty caller id are both missing user
    context, not merely an unauthorised role.

    Design: Corner/rbac/every_cross_role_write_is_refused_at_the_role_rung_before_any_state_or_business_check_runs
    """
    ctx = adopted_ips
    before = read_plan(api, ctx.plan_id)

    # PRD 2.12 priority 10: the role token must be one of the six documented
    # names before the endpoint's own role list is even consulted.
    unknown_role = api.post(
        Paths.recompute_posture(ctx.plan_id),
        {},
        build_user_headers(TestUsers.PLAN_SPONSOR_ADMIN, "PlanTrustee"),
    )
    validate_error(unknown_role, ApiErrorId.MISSING_USER_CONTEXT)

    # A permitted role with a blank caller id is still no user context at all.
    blank_actor = api.post(
        Paths.recompute_posture(ctx.plan_id),
        {},
        build_user_headers("", Role.PLAN_SPONSOR_ADMIN),
    )
    validate_error(blank_actor, ApiErrorId.MISSING_USER_CONTEXT)

    after = read_plan(api, ctx.plan_id)
    assert after["version"] == before["version"], (
        "a request refused for want of user context must not touch the plan"
    )


def test_the_auditor_may_move_the_logical_clock(api: ApiClient, adopted_ips: Ctx):
    """PRD 2.1 grants the auditor the clock even though it grants no writes.

    Design: Corner/rbac/every_cross_role_write_is_refused_at_the_role_rung_before_any_state_or_business_check_runs
    """
    moved = api.set_clock(INSIDE_BLACKOUT, headers=auditor_headers())
    validate_success(moved)


def test_the_role_rung_answers_before_the_proposal_and_run_state_gates(
    api: ApiClient, cross_role_targets
):
    """A consultant may not approve, and the chair may neither execute a
    proposal still under review nor post a run still in draft.

    Design: Corner/rbac/every_cross_role_write_is_refused_at_the_role_rung_before_any_state_or_business_check_runs
    """
    ctx, run, _motion = cross_role_targets
    proposal_id = ctx.proposals["proposal"]["id"]
    before = read_plan(api, ctx.plan_id)

    # PRD 4: approval belongs to the chair alone.  The motion quoted here is
    # still OPEN, so PRD 2.12 priority 60 is armed too and the role rung has to
    # be the one that answers.
    validate_error(
        api.post(
            Paths.proposal_approve(proposal_id),
            {"approving_motion_id": _motion["id"]},
            consultant_headers(),
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    # Execution belongs to the recordkeeper.  UNDER_REVIEW is also an illegal
    # source state for execution (PRD 3.7), and the role gate still wins.
    validate_error(
        api.post(Paths.proposal_execute(proposal_id), {}, ctx.chair),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    # Posting belongs to the recordkeeper; a DRAFT run is not postable either.
    validate_error(
        api.post(Paths.run_post(run["id"]), {}, ctx.chair),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    proposal = read_proposal(api, proposal_id)
    assert_status(proposal, ProposalStatus.UNDER_REVIEW)
    assert proposal["approving_motion_id"] is None
    run_now = read_run(api, run["id"])
    assert_status(run_now, LevelizationStatus.DRAFT)
    assert run_now["posted_at"] is None
    assert read_plan(api, ctx.plan_id)["version"] == before["version"]


def test_the_role_rung_answers_before_existence_and_member_state_gates(
    api: ApiClient, cross_role_targets
):
    """A sponsor scoring a review that does not exist, and a chair activating a
    member who is already active, are both refused for the role.

    Design: Corner/rbac/every_cross_role_write_is_refused_at_the_role_rung_before_any_state_or_business_check_runs
    """
    ctx, _run, _motion = cross_role_targets

    # Scorecards belong to the consultant (PRD 4).  The review reference here is
    # a proposal id, so PRD 2.12 priority 30 would also reject it — priority 20
    # is the earlier rung and must be the one that answers.
    bogus_review_id = ctx.proposals["proposal"]["id"]
    validate_error(
        api.post(
            Paths.SCORECARDS,
            scorecard_payload(bogus_review_id, ctx.fund("lc_a")["id"], 1),
            sponsor_headers(),
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    # Activation belongs to the sponsor.  This member is already ACTIVE, which
    # PRD 3.2 rejects at the state rung, and the role rung comes first.
    hr_id = ctx.members["hr"]["id"]
    validate_error(
        api.post(Paths.activate(hr_id), {}, ctx.chair),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    assert_status(read_member(api, hr_id), MemberStatus.ACTIVE)


def test_moving_a_motion_is_shared_but_closing_seating_and_engaging_are_not(
    api: ApiClient, cross_role_targets
):
    """The member who moved a motion may not close it, the auditor may not seat
    a fund and the recordkeeper may not engage a provider.

    Design: Corner/rbac/every_cross_role_write_is_refused_at_the_role_rung_before_any_state_or_business_check_runs
    """
    ctx, _run, motion = cross_role_targets
    finance_id = ctx.members["finance"]["id"]

    # PRD 3.4 gives closing to the chair only, even to the mover of the motion.
    validate_error(
        api.post(Paths.motion_close(motion["id"]), {}, member_headers(finance_id)),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    assert_status(read_motion(api, motion["id"]), MotionStatus.OPEN)

    # Seating belongs to the consultant.  The large-cap slot is already ACTIVE,
    # so PRD 3.3 would refuse the seating later anyway.
    lc_slot = ctx.slot("lc")
    validate_error(
        api.post(
            Paths.seat_fund(lc_slot["id"]),
            seat_fund_payload(ctx.fund("lc_b")["id"]),
            auditor_headers(),
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    slot = read_slot(api, lc_slot["id"])
    assert_status(slot, SlotStatus.ACTIVE)
    assert slot["current_fund_id"] == ctx.fund("lc_a")["id"]

    # PRD 4 gives provider engagement to the sponsor, not the recordkeeper whose
    # own contract it records.
    validate_error(
        api.post(Paths.ENGAGEMENTS, engagement_payload(ctx.plan_id), recordkeeper_headers()),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )


@pytest.fixture
def approved_with_open_side_work(api: ApiClient, approved_replacement: Ctx):
    """An APPROVED mapping plus a DRAFT levelization run and a DRAFT quarterly
    review, both of which the chair is barred from compensating."""
    ctx = approved_replacement
    run = create_levelization_run(ctx, 0, LevelizationMethod.PRO_RATA)
    review = open_review(ctx, 0)
    return ctx, run, review


def test_the_approving_chair_may_not_serve_the_participant_notice(
    api: ApiClient, approved_replacement: Ctx
):
    """PRD 2.1 reserves notice issuance to the recordkeeper; the chair who
    approved the mapping cannot also announce it.

    Design: Corner/rbac/the_chair_who_approves_a_mapping_can_neither_notice_it_nor_execute_it_nor_undo_it
    """
    ctx = approved_replacement
    proposal_id = ctx.proposals["proposal"]["id"]

    refused = api.post(
        Paths.proposal_notice_issue(proposal_id), notice_issue_payload(), ctx.chair
    )
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)
    still_approved = read_proposal(api, proposal_id)
    assert_status(still_approved, ProposalStatus.APPROVED)
    assert still_approved["notice_delivered_at"] is None

    noticed = validate_success(
        api.post(
            Paths.proposal_notice_issue(proposal_id),
            notice_issue_payload(),
            recordkeeper_headers(),
        )
    )
    assert_status(noticed, ProposalStatus.NOTICE_ISSUED)
    assert noticed["notice_delivered_at"] is not None
    assert noticed["notice_delivered_at"].startswith("2026-08-01")


def test_the_recordkeeper_may_not_rescind_the_chairs_approval(
    api: ApiClient, approved_replacement: Ctx
):
    """Rescission is the chair's own undo (PRD 2.1) and the recordkeeper who
    will execute the mapping cannot reach for it.

    Design: Corner/rbac/the_chair_who_approves_a_mapping_can_neither_notice_it_nor_execute_it_nor_undo_it
    """
    ctx = approved_replacement
    proposal_id = ctx.proposals["proposal"]["id"]

    validate_error(
        api.post(
            Paths.proposal_rescind(proposal_id),
            {"reason": "The recordkeeper would rather not run the mapping."},
            recordkeeper_headers(),
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    proposal = read_proposal(api, proposal_id)
    assert_status(proposal, ProposalStatus.APPROVED)
    assert proposal["approving_motion_id"] is not None
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=1, available=0)


def test_the_chair_may_neither_reverse_a_run_nor_reopen_a_review(
    api: ApiClient, approved_with_open_side_work
):
    """PRD 2.1 says the chair may not reverse or unwind anything, and the
    refusal lands before the state gates those two calls would also fail.

    Design: Corner/rbac/the_chair_who_approves_a_mapping_can_neither_notice_it_nor_execute_it_nor_undo_it
    """
    ctx, run, review = approved_with_open_side_work

    # Reversal is the sponsor's compensating power, and a DRAFT run is not
    # reversible at all (PRD 3.8).
    validate_error(
        api.post(
            Paths.run_reverse(run["id"]),
            {"reason": "The chair disputes the per-account split."},
            ctx.chair,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    assert_status(read_run(api, run["id"]), LevelizationStatus.DRAFT)

    # Reopening is likewise the sponsor's, and only a FINALIZED review can be
    # reopened (PRD 3.5).
    validate_error(
        api.post(
            Paths.review_reopen(review["id"]),
            {"reason": "The chair wants another look at the small-cap sleeve."},
            ctx.chair,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    reread = read_review(api, review["id"])
    assert_status(reread, ReviewStatus.DRAFT)
    assert reread["reopen_count"] == 0


def test_only_the_recordkeeper_executes_the_mapping_and_only_the_sponsor_unwinds_it(
    api: ApiClient, approved_replacement: Ctx
):
    """The chair is shut out of both ends of the mapping: the recordkeeper moves
    the assets and the sponsor is the only actor who can move them back.

    Design: Corner/rbac/the_chair_who_approves_a_mapping_can_neither_notice_it_nor_execute_it_nor_undo_it
    """
    ctx = approved_replacement
    proposal_id = ctx.proposals["proposal"]["id"]
    outgoing_id = ctx.fund("lc_a")["id"]
    incoming_id = ctx.fund("lc_b")["id"]
    slot_id = ctx.slot("lc")["id"]

    validate_success(
        api.post(
            Paths.proposal_notice_issue(proposal_id),
            notice_issue_payload(),
            recordkeeper_headers(),
        )
    )
    set_clock(api, INSIDE_BLACKOUT)

    validate_error(
        api.post(Paths.proposal_execute(proposal_id), {}, ctx.chair),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    assert_status(read_proposal(api, proposal_id), ProposalStatus.NOTICE_ISSUED)

    executed = validate_success(
        api.post(Paths.proposal_execute(proposal_id), {}, recordkeeper_headers())
    )
    assert_status(executed, ProposalStatus.EXECUTED)
    # PRD 3.7 hop 3: the credit-pool basis is stale, so the disclosure needs a
    # restatement.
    assert_status(
        read_plan(api, ctx.plan_id),
        FeeDisclosureStatus.RESTATEMENT_REQUIRED,
        field="fee_disclosure_status",
    )
    assert read_slot(api, slot_id)["current_fund_id"] == incoming_id

    validate_error(
        api.post(
            Paths.proposal_unwind(proposal_id),
            {"reason": "The chair changed their mind after the mapping ran."},
            ctx.chair,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    assert_status(read_proposal(api, proposal_id), ProposalStatus.EXECUTED)

    unwound = validate_success(
        api.post(
            Paths.proposal_unwind(proposal_id),
            {"reason": "Participant communications went out with the wrong ticker."},
            sponsor_headers(),
        )
    )
    assert_status(unwound, ProposalStatus.UNWOUND)
    restored_slot = read_slot(api, slot_id)
    assert_status(restored_slot, SlotStatus.ACTIVE)
    assert restored_slot["current_fund_id"] == outgoing_id
    assert_status(read_fund(api, outgoing_id), FundMenuStatus.ACTIVE, field="menu_status")
    assert_status(read_fund(api, incoming_id), FundMenuStatus.CANDIDATE, field="menu_status")
    plan = read_plan(api, ctx.plan_id)
    assert_status(plan, FeeDisclosureStatus.COMPLIANT, field="fee_disclosure_status")
    assert_capacity_triple(plan, reserved=0)


def test_the_auditor_may_read_every_entity_in_the_fiduciary_record(
    api: ApiClient, finalized_quarter: Ctx
):
    """PRD 2.1 gives the auditor an unrestricted read of the whole record, filters
    and pagination included.

    Design: Corner/rbac/the_auditor_can_read_the_entire_fiduciary_record_and_move_the_clock_but_can_write_nothing
    """
    ctx = finalized_quarter
    aud = auditor_headers()

    plan = validate_success(api.get(Paths.plan(ctx.plan_id), aud))
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)

    meetings, meta = validate_paginated(
        api.get(
            Paths.MEETINGS,
            aud,
            {"plan_id": ctx.plan_id, "status": MeetingStatus.MINUTES_APPROVED},
        )
    )
    assert meta["total_count"] == len(meetings) >= 2
    for row in meetings:
        assert_status(row, MeetingStatus.MINUTES_APPROVED)
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"list meta is missing {key!r}"

    ips_meeting_id = ctx.meetings["ips_meeting"]["id"]
    motions, _ = validate_paginated(api.get(Paths.MOTIONS, aud, {"meeting_id": ips_meeting_id}))
    adoption = find_by(motions, subject_type=MotionSubjectType.IPS_ADOPTION)
    assert_status(adoption, MotionStatus.CARRIED)
    assert len(adoption["votes"]) == 3

    review_id = ctx.review["id"]
    scorecards, sc_meta = validate_paginated(
        api.get(Paths.SCORECARDS, aud, {"review_id": review_id, "status": ScorecardStatus.SUBMITTED})
    )
    assert sc_meta["total_count"] == 5, "one submitted scorecard per seated fund"
    for row in scorecards:
        assert row["composite_score"] is not None, "the auditor sees the scoring detail"

    review = validate_success(api.get(Paths.review(review_id), aud))
    assert_status(review, ReviewStatus.FINALIZED)

    funds, _ = validate_paginated(
        api.get(Paths.FUNDS, aud, {"plan_id": ctx.plan_id, "watch_status": WatchStatus.CLEAR})
    )
    assert ctx.fund("lc_a")["id"] in [row["id"] for row in funds]

    slots, slot_meta = validate_paginated(
        api.get(Paths.SLOTS, aud, {"plan_id": ctx.plan_id, "status": SlotStatus.ACTIVE})
    )
    assert slot_meta["total_count"] == 5

    members, _ = validate_paginated(
        api.get(Paths.MEMBERS, aud, {"seat_id": ctx.seats["chair"]["id"]})
    )
    assert [row["id"] for row in members] == [ctx.chair_id]

    records, rec_meta = validate_paginated(
        api.get(
            Paths.TRAINING_RECORDS,
            aud,
            {"member_id": ctx.chair_id, "status": TrainingStatus.COMPLETED},
        )
    )
    assert rec_meta["total_count"] == 2, "both required modules were completed"


def test_the_auditor_is_refused_on_every_write_and_leaves_no_trace(
    api: ApiClient, finalized_quarter: Ctx
):
    """The read-only posture is what makes the audit trail credible (PRD 2.1), so
    not one auditor write lands and no row's version moves.

    Design: Corner/rbac/the_auditor_can_read_the_entire_fiduciary_record_and_move_the_clock_but_can_write_nothing
    """
    ctx = finalized_quarter
    aud = auditor_headers()
    plan_before = read_plan(api, ctx.plan_id)
    review_before = read_review(api, ctx.review["id"])
    small_fund_id = ctx.fund("small")["id"]

    validate_error(
        api.post(Paths.PLANS, plan_payload(plan_name="Auditor's Own Plan"), aud),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.post(Paths.MEETINGS, meeting_payload(ctx.plan_id, "2026-08-24", 0), aud),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.post(
            Paths.review_reopen(ctx.review["id"]),
            {"reason": "The auditor would like the quarter reopened."},
            aud,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.patch(Paths.fund(small_fund_id), {"style_drift_r2": 0.9900}, aud),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    assert_ratio(read_fund(api, small_fund_id)["style_drift_r2"], "0.8800", "style_drift_r2")
    assert read_plan(api, ctx.plan_id)["version"] == plan_before["version"]
    review_after = read_review(api, ctx.review["id"])
    assert review_after["version"] == review_before["version"]
    assert_status(review_after, ReviewStatus.FINALIZED)
    assert review_after["reopen_count"] == 0


@pytest.fixture
def seated_committee(api: ApiClient, adopted_ips: Ctx):
    """Three activated voting members, a candidate fund to move motions about,
    and one meeting still SCHEDULED."""
    ctx = adopted_ips
    create_fund(ctx, "lc_a")
    meeting = schedule_meeting(ctx, "2026-08-21", 0, key="seated")
    return ctx, meeting


def test_the_role_rung_answers_before_the_committee_identity_rung(
    api: ApiClient, seated_committee
):
    """The chair's own member id under the wrong role name is refused for the
    role (PRD 2.12 priority 20), not for the identity behind it.

    Design: Corner/rbac/the_entity_backed_roles_are_resolved_against_real_seats_and_no_member_may_act_for_another
    """
    ctx, meeting = seated_committee

    refused = api.post(
        Paths.convene(meeting["id"]),
        convene_payload(ctx.member_ids),
        build_user_headers(ctx.chair_id, Role.RECORDKEEPER),
    )
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)
    assert_status(read_meeting(api, meeting["id"]), MeetingStatus.SCHEDULED)


def test_the_chair_role_must_resolve_to_a_chair_class_seat(api: ApiClient, seated_committee):
    """PRD 2.1 resolves CommitteeChair against a real member row whose seat class
    is CHAIR; an HR member and an opaque identifier both fail that resolution.

    Design: Corner/rbac/the_entity_backed_roles_are_resolved_against_real_seats_and_no_member_may_act_for_another
    """
    ctx, meeting = seated_committee
    roster = convene_payload(ctx.member_ids)

    # A real, active, voting member — but seated in the HR seat, not the chair's.
    validate_error(
        api.post(Paths.convene(meeting["id"]), roster, chair_headers(ctx.members["hr"]["id"])),
        ApiErrorId.ACTOR_NOT_COMMITTEE_MEMBER,
    )

    # An identifier that belongs to one of the opaque roles resolves to no
    # committee member at all.
    validate_error(
        api.post(
            Paths.convene(meeting["id"]),
            roster,
            chair_headers(TestUsers.INVESTMENT_CONSULTANT),
        ),
        ApiErrorId.ACTOR_NOT_COMMITTEE_MEMBER,
    )
    assert_status(read_meeting(api, meeting["id"]), MeetingStatus.SCHEDULED)

    pinned_version = read_plan(api, ctx.plan_id)["version"]
    convened = validate_success(api.post(Paths.convene(meeting["id"]), roster, ctx.chair))
    assert_status(convened, MeetingStatus.IN_SESSION)
    assert_fields(
        convened,
        eligible_voting_seat_count=3,
        voting_attendee_count=3,
        quorum_met=True,
        charter_version_pinned=pinned_version,
    )


def test_an_opaque_identity_may_not_vote_on_a_motion_a_member_moved(
    api: ApiClient, seated_committee
):
    """PRD 3.4 requires the voter to be a committee member on this plan, so the
    recordkeeper's identifier cannot vote even wearing the member role.

    Design: Corner/rbac/the_entity_backed_roles_are_resolved_against_real_seats_and_no_member_may_act_for_another
    """
    ctx, meeting = seated_committee
    validate_success(api.post(Paths.convene(meeting["id"]), convene_payload(ctx.member_ids), ctx.chair))

    finance_id = ctx.members["finance"]["id"]
    motion = validate_success(
        api.post(
            Paths.MOTIONS,
            motion_payload(
                meeting["id"], MotionSubjectType.WATCH_LIST_ACTION, ctx.fund("lc_a")["id"]
            ),
            member_headers(finance_id),
        ),
        201,
    )
    assert_status(motion, MotionStatus.OPEN)
    assert motion["votes"] == []
    assert_fields(motion, for_count=0, against_count=0, abstain_count=0, recuse_count=0)

    validate_error(
        api.post(
            Paths.votes(motion["id"]),
            vote_payload(TestUsers.RECORDKEEPER),
            member_headers(TestUsers.RECORDKEEPER),
        ),
        ApiErrorId.ACTOR_NOT_COMMITTEE_MEMBER,
    )
    assert read_motion(api, motion["id"])["votes"] == []


def test_no_member_may_cast_a_vote_or_sign_an_acceptance_for_another(
    api: ApiClient, seated_committee
):
    """The chair may not vote for an absentee (PRD 3.4) nor sign another member's
    fiduciary acceptance (PRD 3.2) — and the self check answers before the
    already-signed check.

    Design: Corner/rbac/the_entity_backed_roles_are_resolved_against_real_seats_and_no_member_may_act_for_another
    """
    ctx, meeting = seated_committee
    validate_success(api.post(Paths.convene(meeting["id"]), convene_payload(ctx.member_ids), ctx.chair))
    finance_id = ctx.members["finance"]["id"]
    hr_id = ctx.members["hr"]["id"]
    motion = validate_success(
        api.post(
            Paths.MOTIONS,
            motion_payload(
                meeting["id"], MotionSubjectType.WATCH_LIST_ACTION, ctx.fund("lc_a")["id"]
            ),
            member_headers(finance_id),
        ),
        201,
    )

    # Both members already carried one FOR vote on the statement-adoption motion
    # that governs this plan, so PRD 3.4's "a FOR, AGAINST or ABSTAIN also
    # increments the member's votes_cast_count" is measured as a delta here.
    finance_before = read_member(api, finance_id)["votes_cast_count"]
    chair_before = read_member(api, ctx.chair_id)["votes_cast_count"]

    validate_error(
        api.post(Paths.votes(motion["id"]), vote_payload(finance_id), ctx.chair),
        ApiErrorId.ACTOR_NOT_SELF,
    )
    assert read_motion(api, motion["id"])["votes"] == []
    assert read_member(api, finance_id)["votes_cast_count"] == finance_before

    # The HR member signed their own acceptance during activation, so the
    # already-signed gate is also armed; the self check is the earlier one.
    hr_before = read_member(api, hr_id)
    validate_error(
        api.post(Paths.acceptance(hr_id), acceptance_payload(), ctx.chair),
        ApiErrorId.ACTOR_NOT_SELF,
    )
    hr_after = read_member(api, hr_id)
    assert hr_after["acceptance_doc_ref"] == hr_before["acceptance_doc_ref"]
    assert hr_after["version"] == hr_before["version"]

    own_vote = validate_success(
        api.post(Paths.votes(motion["id"]), vote_payload(ctx.chair_id), ctx.chair)
    )
    assert_fields(own_vote, for_count=1, against_count=0, abstain_count=0, recuse_count=0)
    assert [entry["member_id"] for entry in own_vote["votes"]] == [ctx.chair_id]
    assert read_member(api, ctx.chair_id)["votes_cast_count"] == chair_before + 1
    assert read_plan(api, ctx.plan_id)["documented_acceptance_count"] == 3
