"""Lifecycles that are not a straight line.

Two shapes live here.  The first is the fork/join that stands between a freshly
appointed committee member and an `ACTIVE` one (PRD 3.2): a training branch and
an acceptance branch that may be cleared in either order, joined by an
activation call that refuses to fire until both are done.  The second is the
revision cycle of a fund replacement proposal (PRD 3.7), which may re-enter
`UNDER_REVIEW` three times and then must refuse a fourth lap.
"""

from typing import Dict

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_fields,
    assert_status,
    assert_version_unchanged,
    get_success_data,
    validate_error,
)
from test_helpers.factories import Paths, revise_payload
from test_helpers.fixtures import (
    Ctx,
    appoint_member,
    assign_training,
    complete_training,
    create_seat,
    read_fund,
    read_member,
    read_plan,
    read_proposal,
    read_slot,
    register_plan,
    sign_acceptance,
)
from test_helpers.test_users import consultant_headers, sponsor_headers
from test_helpers.types import (
    FiduciaryTrainingStatus,
    FundMenuStatus,
    MappingStrategy,
    MemberStatus,
    MenuPosture,
    ProposalStatus,
    SeatClass,
    SeatStatus,
    SlotDesignation,
    SlotStatus,
    TrainingModule,
    TrainingStatus,
)

#: The clock every test runs on, so the acceptance stamp is predictable.
CLOCK_DATE = "2026-08-01"

#: The lowest passing training score PRD 3.2 allows: 80 exactly still passes.
PASS_FLOOR_SCORE = 80.00


@pytest.fixture
def two_appointed_members(api: ApiClient) -> Dict[str, str]:
    """A plan with two members sitting in filled voting seats, both `APPOINTED`
    and neither branch of the onboarding fork started yet."""
    plan = register_plan(api)
    seat_a = create_seat(
        api, plan["id"], seat_code="S-CHAIR", seat_class=SeatClass.CHAIR, seat_index=1, voting=True
    )
    seat_b = create_seat(
        api, plan["id"], seat_code="S-FIN", seat_class=SeatClass.FINANCE, seat_index=2, voting=True
    )
    member_a = appoint_member(
        api,
        seat_a["id"],
        member_name="Alina Ferro",
        person_email="alina.ferro@example.com",
    )
    member_b = appoint_member(
        api,
        seat_b["id"],
        member_name="Bruno Kaine",
        person_email="bruno.kaine@example.com",
    )
    return {
        "plan_id": plan["id"],
        "seat_a": seat_a["id"],
        "seat_b": seat_b["id"],
        "member_a": member_a["id"],
        "member_b": member_b["id"],
    }


def _clear_training_branch(
    api: ApiClient, member_id: str, score_pct: float = 95.00
) -> None:
    """Create and complete a record for each of the two required modules."""
    for module in TrainingModule.REQUIRED:
        record = assign_training(api, member_id, module_code=module)
        complete_training(api, record["id"], member_id, score_pct)


def _attempt_activation(api: ApiClient, member_id: str):
    """The sponsor's join call, returned raw so a refusal can be inspected."""
    return api.post(Paths.activate(member_id), {}, sponsor_headers())


# --------------------------------------------------------------------------
# The onboarding fork: the training branch on its own
# --------------------------------------------------------------------------


def test_training_branch_moves_appointed_member_without_touching_acceptance(
    api: ApiClient, two_appointed_members: Dict[str, str]
):
    """The first training record moves an APPOINTED member to TRAINING_ASSIGNED
    and leaves the plan's documented acceptance tally alone.

    Design: Difficulty/non_linear_state_machine/member_fork_join_training_and_acceptance_branches_order_independent
    """
    member_id = two_appointed_members["member_a"]
    plan_id = two_appointed_members["plan_id"]
    before = read_member(api, member_id)
    assert_fields(
        before,
        status=MemberStatus.APPOINTED,
        fiduciary_training_status=FiduciaryTrainingStatus.PENDING,
        acceptance_signed_at=None,
        votes_cast_count=0,
    )

    record = assign_training(api, member_id, module_code=TrainingModule.FIDUCIARY_DUTIES)

    assert_fields(
        record,
        member_id=member_id,
        module_code=TrainingModule.FIDUCIARY_DUTIES,
        status=TrainingStatus.ASSIGNED,
        assigned_quarter_index=0,
    )
    member = read_member(api, member_id)
    assert_fields(
        member,
        status=MemberStatus.TRAINING_ASSIGNED,
        fiduciary_training_status=FiduciaryTrainingStatus.PENDING,
        acceptance_signed_at=None,
    )
    # PRD 3.2: the training branch deliberately does not touch the acceptance
    # counter, which is the other branch's distinguishing side effect.
    assert read_plan(api, plan_id)["documented_acceptance_count"] == 0


def test_second_training_record_does_not_move_the_member_again(
    api: ApiClient, two_appointed_members: Dict[str, str]
):
    """A further training record is still created once the member has left
    APPOINTED, but it triggers no member transition.

    Design: Difficulty/non_linear_state_machine/member_fork_join_training_and_acceptance_branches_order_independent
    """
    member_id = two_appointed_members["member_a"]
    assign_training(api, member_id, module_code=TrainingModule.FIDUCIARY_DUTIES)

    second = assign_training(api, member_id, module_code=TrainingModule.IPS_MECHANICS)

    assert_fields(
        second,
        module_code=TrainingModule.IPS_MECHANICS,
        status=TrainingStatus.ASSIGNED,
        assigned_quarter_index=0,
    )
    member = read_member(api, member_id)
    assert_status(member, MemberStatus.TRAINING_ASSIGNED)
    assert member["fiduciary_training_status"] == FiduciaryTrainingStatus.PENDING
    assert read_plan(api, two_appointed_members["plan_id"])["documented_acceptance_count"] == 0


def test_training_branch_alone_never_reaches_active(
    api: ApiClient, two_appointed_members: Dict[str, str]
):
    """Both required modules current is still not enough: without a signed
    acceptance the join refuses and the member stays TRAINING_ASSIGNED.

    Design: Difficulty/non_linear_state_machine/member_fork_join_training_and_acceptance_branches_order_independent
    """
    member_id = two_appointed_members["member_a"]
    _clear_training_branch(api, member_id)

    ready = read_member(api, member_id)
    assert_fields(
        ready,
        status=MemberStatus.TRAINING_ASSIGNED,
        fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
        acceptance_signed_at=None,
    )

    refused = _attempt_activation(api, member_id)
    validate_error(refused, ApiErrorId.FIDUCIARY_ACCEPTANCE_MISSING)

    after = read_member(api, member_id)
    assert_status(after, MemberStatus.TRAINING_ASSIGNED)
    assert after["status"] in MemberStatus.LIVE
    assert_version_unchanged(ready, after)
    assert read_plan(api, two_appointed_members["plan_id"])["documented_acceptance_count"] == 0


# --------------------------------------------------------------------------
# The onboarding fork: the acceptance branch on its own
# --------------------------------------------------------------------------


def test_acceptance_branch_alone_never_reaches_active(
    api: ApiClient, two_appointed_members: Dict[str, str]
):
    """Signing the acceptance moves an APPOINTED member straight to
    ACCEPTANCE_PENDING and counts once, but the join still refuses while the
    training branch is unfinished.

    Design: Difficulty/non_linear_state_machine/member_fork_join_training_and_acceptance_branches_order_independent
    """
    member_id = two_appointed_members["member_b"]
    plan_id = two_appointed_members["plan_id"]

    signed = sign_acceptance(api, member_id, acceptance_doc_ref="ACC-2026-B")

    assert_fields(
        signed,
        status=MemberStatus.ACCEPTANCE_PENDING,
        fiduciary_training_status=FiduciaryTrainingStatus.PENDING,
        acceptance_doc_ref="ACC-2026-B",
    )
    assert signed["acceptance_signed_at"] is not None
    assert str(signed["acceptance_signed_at"]).startswith(CLOCK_DATE)
    # PRD 3.2: the acceptance branch is the only writer of this counter.
    assert read_plan(api, plan_id)["documented_acceptance_count"] == 1

    refused = _attempt_activation(api, member_id)
    validate_error(refused, ApiErrorId.TRAINING_NOT_CURRENT)

    after = read_member(api, member_id)
    assert_status(after, MemberStatus.ACCEPTANCE_PENDING)
    assert after["status"] in MemberStatus.LIVE
    assert read_plan(api, plan_id)["documented_acceptance_count"] == 1


def test_signing_from_training_assigned_keeps_the_training_verdict(
    api: ApiClient, two_appointed_members: Dict[str, str]
):
    """A member already in TRAINING_ASSIGNED also lands in ACCEPTANCE_PENDING on
    signing, retaining whatever training verdict it had.

    Design: Difficulty/non_linear_state_machine/member_fork_join_training_and_acceptance_branches_order_independent
    """
    member_id = two_appointed_members["member_a"]
    _clear_training_branch(api, member_id)
    assert (
        read_member(api, member_id)["fiduciary_training_status"]
        == FiduciaryTrainingStatus.CURRENT
    )

    signed = sign_acceptance(api, member_id)

    assert_fields(
        signed,
        status=MemberStatus.ACCEPTANCE_PENDING,
        fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
    )
    assert read_plan(api, two_appointed_members["plan_id"])["documented_acceptance_count"] == 1


# --------------------------------------------------------------------------
# The join, reached from either arm
# --------------------------------------------------------------------------


def test_training_first_then_acceptance_reaches_active(
    api: ApiClient, two_appointed_members: Dict[str, str]
):
    """Clearing the training branch before the acceptance branch reaches ACTIVE.

    Design: Difficulty/non_linear_state_machine/member_fork_join_training_and_acceptance_branches_order_independent
    """
    member_id = two_appointed_members["member_a"]
    _clear_training_branch(api, member_id)
    sign_acceptance(api, member_id)

    activated = get_success_data(api.post(Paths.activate(member_id), {}, sponsor_headers()))
    assert_status(activated, MemberStatus.ACTIVE)

    member = read_member(api, member_id)
    assert_fields(
        member,
        status=MemberStatus.ACTIVE,
        fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
        votes_cast_count=0,
    )
    assert member["acceptance_signed_at"] is not None
    seat = get_success_data(api.get(Paths.seat(two_appointed_members["seat_a"]), sponsor_headers()))
    assert_status(seat, SeatStatus.FILLED)


def test_acceptance_first_then_training_reaches_active_at_the_score_floor(
    api: ApiClient, two_appointed_members: Dict[str, str]
):
    """Clearing the acceptance branch first reaches the same ACTIVE state, and a
    training score of exactly 80 still counts as a pass.

    Design: Difficulty/non_linear_state_machine/member_fork_join_training_and_acceptance_branches_order_independent
    """
    member_id = two_appointed_members["member_b"]
    sign_acceptance(api, member_id)
    assert_status(read_member(api, member_id), MemberStatus.ACCEPTANCE_PENDING)

    # The member never passes through TRAINING_ASSIGNED on this arm: the records
    # are created while the member sits in ACCEPTANCE_PENDING, so PRD 3.2's "no
    # member transition occurs" clause applies to each of them.
    for module in TrainingModule.REQUIRED:
        record = assign_training(api, member_id, module_code=module)
        assert_status(read_member(api, member_id), MemberStatus.ACCEPTANCE_PENDING)
        complete_training(api, record["id"], member_id, PASS_FLOOR_SCORE)
        assert_status(read_member(api, member_id), MemberStatus.ACCEPTANCE_PENDING)

    ready = read_member(api, member_id)
    assert ready["fiduciary_training_status"] == FiduciaryTrainingStatus.CURRENT

    activated = get_success_data(api.post(Paths.activate(member_id), {}, sponsor_headers()))
    assert_status(activated, MemberStatus.ACTIVE)

    member = read_member(api, member_id)
    assert_fields(
        member,
        status=MemberStatus.ACTIVE,
        fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
        votes_cast_count=0,
    )


def test_both_branch_orders_land_on_the_same_state_and_count_once_each(
    api: ApiClient, two_appointed_members: Dict[str, str]
):
    """Two members onboarded through opposite branch orders end in identical
    terminal states, and each signature is counted exactly once.

    Design: Difficulty/non_linear_state_machine/member_fork_join_training_and_acceptance_branches_order_independent
    """
    plan_id = two_appointed_members["plan_id"]
    first = two_appointed_members["member_a"]
    second = two_appointed_members["member_b"]

    # Member A: training branch, then acceptance branch.
    _clear_training_branch(api, first)
    sign_acceptance(api, first, acceptance_doc_ref="ACC-2026-A")
    # Member B: acceptance branch, then training branch.
    sign_acceptance(api, second, acceptance_doc_ref="ACC-2026-B")
    _clear_training_branch(api, second, PASS_FLOOR_SCORE)

    for member_id in (first, second):
        activated = get_success_data(
            api.post(Paths.activate(member_id), {}, sponsor_headers())
        )
        assert_status(activated, MemberStatus.ACTIVE)

    row_a = read_member(api, first)
    row_b = read_member(api, second)
    for row in (row_a, row_b):
        assert_fields(
            row,
            status=MemberStatus.ACTIVE,
            fiduciary_training_status=FiduciaryTrainingStatus.CURRENT,
            votes_cast_count=0,
        )
    assert row_a["status"] == row_b["status"]
    assert row_a["fiduciary_training_status"] == row_b["fiduciary_training_status"]

    plan = read_plan(api, plan_id)
    assert plan["documented_acceptance_count"] == 2
    for seat_key in ("seat_a", "seat_b"):
        seat = get_success_data(api.get(Paths.seat(two_appointed_members[seat_key]), sponsor_headers()))
        assert_status(seat, SeatStatus.FILLED)


# --------------------------------------------------------------------------
# The revision cycle of a replacement proposal (PRD 3.7)
# --------------------------------------------------------------------------


def _request_revision(ctx: Ctx, proposal_id: str):
    """The chair sends the proposal back; returned raw so refusals can be read.

    PRD 2.8: the revision-request action carries the chair's `revision_note`.
    """
    return ctx.client.post(
        Paths.proposal_request_revision(proposal_id),
        {"revision_note": "Refresh the peer group and restate the mapping cost."},
        ctx.chair,
    )


def _revise(ctx: Ctx, proposal_id: str, **overrides):
    """The consultant resubmits, optionally changing the mapping strategy."""
    return ctx.client.post(
        Paths.proposal_revise(proposal_id), revise_payload(**overrides), consultant_headers()
    )


def _lap(ctx: Ctx, proposal_id: str, **overrides) -> Dict[str, object]:
    """One full lap of the cycle: back to the consultant and out again."""
    get_success_data(_request_revision(ctx, proposal_id))
    return get_success_data(_revise(ctx, proposal_id, **overrides))


def test_a_submitted_proposal_starts_the_cycle_with_no_laps_spent(
    api: ApiClient, submitted_replacement: Ctx
):
    """A freshly submitted proposal sits in UNDER_REVIEW with a zero lap count
    and the plan's own notice lead time.

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_three_laps_then_limit
    """
    ctx = submitted_replacement
    proposal = read_proposal(api, ctx.proposals["proposal"]["id"])

    assert_fields(
        proposal,
        status=ProposalStatus.UNDER_REVIEW,
        revision_round=0,
        mapping_strategy=MappingStrategy.DIRECT_MAP,
        notice_lead_days_required=30,
        pinned_ips_id=ctx.ips_id,
        pre_block_status=None,
    )
    assert proposal["pinned_plan_version"] == ctx.plan_version


def test_the_first_revision_request_sends_the_proposal_back_and_counts_the_lap(
    api: ApiClient, submitted_replacement: Ctx
):
    """A revision request moves UNDER_REVIEW to REVISION_REQUESTED and raises the
    lap count by one without recomputing the notice lead time.

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_three_laps_then_limit
    """
    ctx = submitted_replacement
    proposal_id = ctx.proposals["proposal"]["id"]

    sent_back = get_success_data(_request_revision(ctx, proposal_id))

    assert_fields(
        sent_back,
        status=ProposalStatus.REVISION_REQUESTED,
        revision_round=1,
        notice_lead_days_required=30,
    )
    # The slot is still merely occupied: nothing is reserved until approval.
    assert_status(read_slot(api, ctx.slot("lc")["id"]), SlotStatus.ACTIVE)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=0, available=1)


def test_the_first_revision_re_enters_under_review_and_refreshes_the_pinned_version(
    api: ApiClient, submitted_replacement: Ctx
):
    """Revising with no change returns the proposal to UNDER_REVIEW on the same
    lap count, keeps its own pinned policy statement and refreshes the pinned
    plan version.

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_three_laps_then_limit
    """
    ctx = submitted_replacement
    proposal_id = ctx.proposals["proposal"]["id"]

    revised = _lap(ctx, proposal_id)

    assert_fields(
        revised,
        status=ProposalStatus.UNDER_REVIEW,
        revision_round=1,
        mapping_strategy=MappingStrategy.DIRECT_MAP,
        notice_lead_days_required=30,
        pinned_ips_id=ctx.ips_id,
    )
    assert revised["pinned_plan_version"] == read_plan(api, ctx.plan_id)["version"]


def test_the_second_lap_recomputes_the_notice_lead_time_for_a_reenrolment(
    api: ApiClient, submitted_replacement: Ctx
):
    """Revising into a re-enrolment adds the further thirty days PRD 3.7 charges
    for that strategy.

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_three_laps_then_limit
    """
    ctx = submitted_replacement
    proposal_id = ctx.proposals["proposal"]["id"]
    _lap(ctx, proposal_id)

    revised = _lap(ctx, proposal_id, mapping_strategy=MappingStrategy.REENROLLMENT)

    assert_fields(
        revised,
        status=ProposalStatus.UNDER_REVIEW,
        revision_round=2,
        mapping_strategy=MappingStrategy.REENROLLMENT,
        notice_lead_days_required=60,
    )


def test_the_third_lap_recomputes_the_notice_lead_time_for_a_map_to_qdia(
    api: ApiClient, submitted_replacement: Ctx
):
    """Mapping to the qualified default out of a CORE slot costs fifteen further
    days and never the re-enrolment thirty as well.

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_three_laps_then_limit
    """
    ctx = submitted_replacement
    proposal_id = ctx.proposals["proposal"]["id"]
    _lap(ctx, proposal_id)
    _lap(ctx, proposal_id, mapping_strategy=MappingStrategy.REENROLLMENT)

    revised = _lap(ctx, proposal_id, mapping_strategy=MappingStrategy.MAP_TO_QDIA)

    assert_fields(
        revised,
        status=ProposalStatus.UNDER_REVIEW,
        revision_round=3,
        mapping_strategy=MappingStrategy.MAP_TO_QDIA,
        notice_lead_days_required=45,
    )
    assert read_slot(api, ctx.slot("lc")["id"])["designation"] == SlotDesignation.CORE


def test_a_fourth_revision_request_is_refused_once_three_laps_are_spent(
    api: ApiClient, submitted_replacement: Ctx
):
    """The cycle is bounded: with three laps on the clock a further revision
    request is refused and changes nothing.

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_three_laps_then_limit
    """
    ctx = submitted_replacement
    proposal_id = ctx.proposals["proposal"]["id"]
    _lap(ctx, proposal_id)
    _lap(ctx, proposal_id, mapping_strategy=MappingStrategy.REENROLLMENT)
    third = _lap(ctx, proposal_id, mapping_strategy=MappingStrategy.MAP_TO_QDIA)
    assert third["revision_round"] == 3

    refused = _request_revision(ctx, proposal_id)
    validate_error(refused, ApiErrorId.REVISION_LIMIT_REACHED)

    after = read_proposal(api, proposal_id)
    assert_fields(
        after,
        status=ProposalStatus.UNDER_REVIEW,
        revision_round=3,
        mapping_strategy=MappingStrategy.MAP_TO_QDIA,
        notice_lead_days_required=45,
    )
    assert_version_unchanged(third, after)


def test_the_whole_cycle_leaves_the_slot_the_funds_and_the_capacity_untouched(
    api: ApiClient, submitted_replacement: Ctx
):
    """Three laps and a refused fourth move no menu state: the slot stays ACTIVE
    on its incumbent, the successor stays a candidate and nothing is reserved.

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_three_laps_then_limit
    """
    ctx = submitted_replacement
    proposal_id = ctx.proposals["proposal"]["id"]
    _lap(ctx, proposal_id)
    _lap(ctx, proposal_id, mapping_strategy=MappingStrategy.REENROLLMENT)
    _lap(ctx, proposal_id, mapping_strategy=MappingStrategy.MAP_TO_QDIA)
    validate_error(_request_revision(ctx, proposal_id), ApiErrorId.REVISION_LIMIT_REACHED)

    slot = read_slot(api, ctx.slot("lc")["id"])
    assert_fields(slot, status=SlotStatus.ACTIVE, current_fund_id=ctx.fund("lc_a")["id"])
    assert_status(read_fund(api, ctx.fund("lc_a")["id"]), FundMenuStatus.ACTIVE, "menu_status")
    assert_status(read_fund(api, ctx.fund("lc_b")["id"]), FundMenuStatus.CANDIDATE, "menu_status")

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)
    assert_status(plan, MenuPosture.OPEN, "menu_posture")
