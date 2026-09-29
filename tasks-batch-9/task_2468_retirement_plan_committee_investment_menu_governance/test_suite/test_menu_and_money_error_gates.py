"""Rejection gates on the menu, the fee motions and the provider engagements.

These tests exercise the seating gates of PRD 3.4, the replacement submission and
approval gates of PRD 3.7, the recusal duty on fee motions from PRD 3.5 and the
termination guards of PRD 3.9, always asserting the exact error identifier that
the precedence ladder of PRD 2.12 selects.
"""

import pytest

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_fields,
    assert_ratio,
    assert_score,
    assert_status,
    get_success_data,
    validate_error,
)
from test_helpers.factories import Paths, seat_fund_payload, vote_payload
from test_helpers.fixtures import (
    benchmark_engagement,
    cast_vote,
    close_motion,
    create_engagement,
    create_fund,
    create_levelization_run,
    create_slot,
    draft_proposal,
    execute_proposal,
    hold_meeting_and_carry_motion,
    move_motion,
    open_meeting,
    read_engagement,
    read_fund,
    read_member,
    read_motion,
    read_plan,
    read_proposal,
    read_slot,
    seat_fund,
    set_clock,
    setup_full_menu,
    setup_noticed_replacement,
    submit_proposal,
)
from test_helpers.test_users import consultant_headers, member_headers, sponsor_headers
from test_helpers.types import (
    AssetClass,
    EngagementStatus,
    FeeCreditTier,
    FundMenuStatus,
    MotionStatus,
    MotionSubjectType,
    ProposalStatus,
    ProviderRole,
    SlotStatus,
    Vote,
)


@pytest.fixture
def saturated_menu(api):
    """A six-slot menu with every position occupied.

    The emerging-markets sleeve was seated and then retired, so its fund sits in
    PENDING_REMOVAL and its asset class is free for a second slot (PRD 3.4:
    ``asset_class_code`` is unique only among non-retired slots).  A stable-value
    sleeve then takes the position the retirement released, leaving the plan with
    six occupied positions, no available capacity and one EMPTY slot waiting in
    the emerging-markets asset class.
    """
    ctx = setup_full_menu(api)
    create_fund(
        ctx,
        "em_old",
        ticker="EMOLD",
        fund_name="Cordillera Emerging Markets R6",
        asset_class_code=AssetClass.EMERGING_MKTS,
    )
    create_slot(ctx, "em_old", AssetClass.EMERGING_MKTS, 6)
    seat_fund(ctx, "em_old", "em_old")
    retired = get_success_data(
        ctx.client.post(
            Paths.slot_retire(ctx.slots["em_old"]["id"]),
            {"reason": "the emerging markets sleeve is folded into the international slot"},
            sponsor_headers(),
        )
    )
    assert_status(retired, SlotStatus.RETIRED)
    create_fund(
        ctx,
        "stable",
        ticker="STVAL",
        fund_name="Keystone Stable Value Institutional",
        asset_class_code=AssetClass.STABLE_VALUE,
    )
    create_slot(ctx, "stable", AssetClass.STABLE_VALUE, 7)
    seat_fund(ctx, "stable", "stable")
    create_slot(ctx, "em_open", AssetClass.EMERGING_MKTS, 8)
    ctx.refresh_plan()
    return ctx


def test_seating_a_fund_marked_for_removal_is_refused_before_the_capacity_check(
    api, saturated_menu
):
    """A fund left in PENDING_REMOVAL cannot be re-seated, and that referential
    failure answers ahead of the exhausted capacity of the same request.

    Design: Corner/errors/the_seating_and_submission_gates_separate_referential_failures_from_capacity_failures_on_a_full_menu
    """
    ctx = saturated_menu
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=6, reserved=0, available=0)
    marked = read_fund(api, ctx.funds["em_old"]["id"])
    assert_status(marked, FundMenuStatus.PENDING_REMOVAL, field="menu_status")

    response = api.post(
        Paths.seat_fund(ctx.slots["em_open"]["id"]),
        seat_fund_payload(marked["id"]),
        consultant_headers(),
    )
    validate_error(response, ApiErrorId.FUND_NOT_CANDIDATE)

    slot = read_slot(api, ctx.slots["em_open"]["id"])
    assert_status(slot, SlotStatus.EMPTY)
    assert slot["current_fund_id"] is None
    assert_status(
        read_fund(api, marked["id"]), FundMenuStatus.PENDING_REMOVAL, field="menu_status"
    )
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=6, reserved=0, available=0)


def test_seating_a_faultless_candidate_on_a_full_menu_is_refused_for_capacity(
    api, saturated_menu
):
    """With every referential and policy gate satisfied, the only remaining
    obstacle on a menu with no available position is the capacity gate.

    Design: Corner/errors/the_seating_and_submission_gates_separate_referential_failures_from_capacity_failures_on_a_full_menu
    """
    ctx = saturated_menu
    fresh = create_fund(
        ctx,
        "em_fresh",
        ticker="EMNEW",
        fund_name="Cordillera Emerging Markets Institutional",
        asset_class_code=AssetClass.EMERGING_MKTS,
    )
    assert_status(fresh, FundMenuStatus.CANDIDATE, field="menu_status")

    response = api.post(
        Paths.seat_fund(ctx.slots["em_open"]["id"]),
        seat_fund_payload(fresh["id"]),
        consultant_headers(),
    )
    validate_error(response, ApiErrorId.MENU_CAPACITY_EXHAUSTED)

    assert_status(read_slot(api, ctx.slots["em_open"]["id"]), SlotStatus.EMPTY)
    assert_status(read_fund(api, fresh["id"]), FundMenuStatus.CANDIDATE, field="menu_status")
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=6, reserved=0, available=0)


def test_submitting_a_proposal_whose_outgoing_fund_is_not_seated_in_the_slot_is_refused(
    api, full_menu
):
    """Creation only checks the incoming fund's asset class, so the mismatched
    outgoing fund is caught at submission, and a corrected proposal supersedes
    the draft it replaces.

    Design: Corner/errors/the_seating_and_submission_gates_separate_referential_failures_from_capacity_failures_on_a_full_menu
    """
    ctx = full_menu
    create_fund(
        ctx,
        "bond_b",
        ticker="BNDBX",
        fund_name="Harbourline Core Bond Institutional",
        asset_class_code=AssetClass.CORE_BOND,
    )
    wrong = draft_proposal(ctx, "bond", "intl", "bond_b", key="wrong")
    assert_status(wrong, ProposalStatus.DRAFT)

    response = api.post(Paths.proposal_submit(wrong["id"]), {}, consultant_headers())
    validate_error(response, ApiErrorId.OUTGOING_FUND_MISMATCH)
    assert_status(read_proposal(api, wrong["id"]), ProposalStatus.DRAFT)

    corrected = draft_proposal(ctx, "bond", "bond", "bond_b", key="corrected")
    assert_status(corrected, ProposalStatus.DRAFT)
    superseded = read_proposal(api, wrong["id"])
    assert_status(superseded, ProposalStatus.WITHDRAWN)
    assert superseded["superseded_by_proposal_id"] == corrected["id"]

    accepted = submit_proposal(ctx, corrected["id"], key="corrected")
    assert_status(accepted, ProposalStatus.UNDER_REVIEW)
    assert_status(read_slot(api, ctx.slots["bond"]["id"]), SlotStatus.ACTIVE)


def test_a_provider_affiliated_member_may_not_vote_for_on_a_fee_motion(api, full_menu):
    """A member whose independence is compromised must recuse on fee business;
    his two independent colleagues then carry the motion without him.

    Design: Corner/errors/the_levelization_and_ips_money_gates_reject_a_closed_out_pool_a_conflicted_vote_an_unfunded_pool_and_equal_thresholds
    """
    ctx = full_menu
    run = create_levelization_run(ctx, quarter_index=0, method="PER_CAPITA")
    meeting = open_meeting(ctx, "2026-08-19", key="fees")
    motion = move_motion(
        ctx, meeting["id"], MotionSubjectType.FEE_LEVELIZATION, run["id"], key="fees"
    )
    conflicted = read_member(api, ctx.members["hr"]["id"])
    assert conflicted["independence_flag"] is False
    assert conflicted["affiliated_provider_role"] == ProviderRole.RECORDKEEPER

    response = api.post(
        Paths.votes(motion["id"]),
        vote_payload(conflicted["id"], Vote.FOR),
        member_headers(conflicted["id"]),
    )
    validate_error(response, ApiErrorId.RECUSAL_REQUIRED)
    rejected = read_motion(api, motion["id"])
    assert_status(rejected, MotionStatus.OPEN)
    assert_fields(rejected, for_count=0, against_count=0, abstain_count=0, recuse_count=0)

    cast_vote(
        ctx,
        motion["id"],
        conflicted["id"],
        Vote.RECUSE,
        recusal_basis="recordkeeper affiliation on fee levelization business",
    )
    cast_vote(ctx, motion["id"], ctx.chair_id, Vote.FOR)
    cast_vote(ctx, motion["id"], ctx.members["finance"]["id"], Vote.FOR)
    closed = close_motion(ctx, motion["id"])
    assert_status(closed, MotionStatus.CARRIED)
    assert_fields(closed, for_count=2, against_count=0, abstain_count=0, recuse_count=1)
    assert_ratio(closed["support_pct"], "100.0000", "support_pct")


def test_neither_an_abstention_nor_a_vote_against_escapes_the_fee_recusal_duty(api, full_menu):
    """The recusal duty is not satisfied by staying neutral: an abstention and a
    vote against are refused exactly as a vote in favour is.

    Design: Corner/errors/the_levelization_and_ips_money_gates_reject_a_closed_out_pool_a_conflicted_vote_an_unfunded_pool_and_equal_thresholds
    """
    ctx = full_menu
    run = create_levelization_run(ctx, quarter_index=0, method="PRO_RATA")
    meeting = open_meeting(ctx, "2026-08-19", key="fees")
    motion = move_motion(
        ctx, meeting["id"], MotionSubjectType.FEE_LEVELIZATION, run["id"], key="fees"
    )
    conflicted_id = ctx.members["hr"]["id"]

    abstention = api.post(
        Paths.votes(motion["id"]),
        vote_payload(conflicted_id, Vote.ABSTAIN),
        member_headers(conflicted_id),
    )
    validate_error(abstention, ApiErrorId.RECUSAL_REQUIRED)

    against = api.post(
        Paths.votes(motion["id"]),
        vote_payload(conflicted_id, Vote.AGAINST),
        member_headers(conflicted_id),
    )
    validate_error(against, ApiErrorId.RECUSAL_REQUIRED)

    untouched = read_motion(api, motion["id"])
    assert_status(untouched, MotionStatus.OPEN)
    assert_fields(untouched, for_count=0, against_count=0, abstain_count=0, recuse_count=0)
    assert untouched["votes"] == []


@pytest.fixture
def noticed_with_providers(api):
    """A plan with a participant notice already out on a large-cap mapping and
    two benchmarked engagements: the incumbent recordkeeper and an advisor who
    has nothing to do with the mapping.

    Both engagements are priced purely on assets, so the benchmark arithmetic of
    PRD 3.9 lands on a gross cost of 8.00 basis points, TIER_A and no competition
    trigger, which leaves each of them ACTIVE.
    """
    ctx = setup_noticed_replacement(api)
    create_engagement(
        ctx,
        key="recordkeeper",
        provider_name="Meridian Retirement Services",
        provider_role=ProviderRole.RECORDKEEPER,
        per_head_fee_cents=0,
        asset_based_bps=8,
    )
    benchmark_engagement(ctx, ctx.engagements["recordkeeper"]["id"], key="recordkeeper")
    create_engagement(
        ctx,
        key="advisor",
        provider_name="Cardinal Fiduciary Advisors",
        provider_role=ProviderRole.ADVISOR,
        per_head_fee_cents=0,
        asset_based_bps=8,
    )
    benchmark_engagement(ctx, ctx.engagements["advisor"]["id"], key="advisor")
    return ctx


def test_an_unrelated_engagement_cannot_be_terminated_while_a_notice_is_outstanding(
    api, noticed_with_providers
):
    """The outstanding-mapping guard is plan-wide: the advisor is frozen out of
    termination until the announced mapping has actually been executed.

    Design: Corner/errors/an_engagement_cannot_be_terminated_mid_mapping_and_a_plan_can_never_be_left_without_a_recordkeeper
    """
    ctx = noticed_with_providers
    advisor = read_engagement(api, ctx.engagements["advisor"]["id"])
    assert_status(advisor, EngagementStatus.ACTIVE)
    assert_fields(
        advisor,
        last_benchmarked_quarter_index=0,
        fee_credit_tier=FeeCreditTier.TIER_A,
        rfp_required=False,
    )
    assert_score(advisor["gross_cost_bps"], "8.00", "gross_cost_bps")
    assert_score(advisor["total_cost_bps"], "8.00", "total_cost_bps")
    assert_status(read_proposal(api, ctx.proposals["proposal"]["id"]), ProposalStatus.NOTICE_ISSUED)

    refused = api.post(
        Paths.engagement_terminate(advisor["id"]),
        {"reason": "advisory mandate consolidated into the recordkeeper bundle"},
        sponsor_headers(),
    )
    validate_error(refused, ApiErrorId.ENGAGEMENT_HAS_PENDING_MAPPING)
    intact = read_engagement(api, advisor["id"])
    assert_status(intact, EngagementStatus.ACTIVE)
    assert intact["term_end_date"] == "2027-12-31"

    set_clock(api, "2026-09-02T00:00:00Z")
    executed = execute_proposal(ctx, ctx.proposals["proposal"]["id"])
    assert_status(executed, ProposalStatus.EXECUTED)

    accepted = get_success_data(
        api.post(
            Paths.engagement_terminate(advisor["id"]),
            {"reason": "advisory mandate consolidated into the recordkeeper bundle"},
            sponsor_headers(),
        )
    )
    assert_status(accepted, EngagementStatus.TERMINATED)
    assert accepted["term_end_date"] == "2026-09-02"


def test_the_sole_recordkeeper_guard_answers_before_the_outstanding_mapping_guard(
    api, noticed_with_providers
):
    """Terminating the only recordkeeper breaks two structural rules at once and
    the earlier one answers; registering a substitute leaves only the mapping
    guard, which proves the first answer was a precedence result.

    Design: Corner/errors/an_engagement_cannot_be_terminated_mid_mapping_and_a_plan_can_never_be_left_without_a_recordkeeper
    """
    ctx = noticed_with_providers
    incumbent = read_engagement(api, ctx.engagements["recordkeeper"]["id"])
    assert_status(incumbent, EngagementStatus.ACTIVE)

    both_broken = api.post(
        Paths.engagement_terminate(incumbent["id"]),
        {"reason": "recordkeeper conversion"},
        sponsor_headers(),
    )
    validate_error(both_broken, ApiErrorId.RECORDKEEPER_REQUIRED)
    assert_status(read_engagement(api, incumbent["id"]), EngagementStatus.ACTIVE)

    successor = create_engagement(
        ctx,
        key="recordkeeper_successor",
        provider_name="Northgate Plan Administration",
        provider_role=ProviderRole.RECORDKEEPER,
        term_start_date="2028-01-01",
        term_end_date="2030-12-31",
        per_head_fee_cents=0,
        asset_based_bps=8,
    )
    assert_status(successor, EngagementStatus.PENDING)
    assert successor["gross_cost_bps"] is None
    assert successor["fee_credit_tier"] is None
    assert successor["last_benchmarked_quarter_index"] is None

    mapping_only = api.post(
        Paths.engagement_terminate(incumbent["id"]),
        {"reason": "recordkeeper conversion"},
        sponsor_headers(),
    )
    validate_error(mapping_only, ApiErrorId.ENGAGEMENT_HAS_PENDING_MAPPING)
    survivor = read_engagement(api, incumbent["id"])
    assert_status(survivor, EngagementStatus.ACTIVE)
    assert survivor["term_end_date"] == "2027-12-31"


def test_a_reserved_slot_refuses_a_second_approval_until_the_first_is_rescinded(
    api, approved_replacement
):
    """A slot already reserved by an approved replacement rejects a rival
    approval on its own carried motion and minuted meeting, and accepts it only
    once the first approval has been rescinded.

    Design: Corner/errors/a_reserved_slot_refuses_a_second_approval_even_with_its_own_carried_motion_and_approved_minutes
    """
    ctx = approved_replacement
    incumbent_proposal = ctx.proposals["proposal"]["id"]
    slot_id = ctx.slots["lc"]["id"]
    assert_status(read_slot(api, slot_id), SlotStatus.PENDING_REPLACEMENT)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=1, available=0)

    create_fund(
        ctx,
        "lc_c",
        ticker="LCGRC",
        fund_name="Ridgeline Large Cap Growth Institutional",
        asset_class_code=AssetClass.US_LARGE_CAP,
    )
    rival = draft_proposal(ctx, "lc", "lc_a", "lc_c", key="rival")
    submit_proposal(ctx, rival["id"], key="rival")
    rival_motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.FUND_REPLACEMENT,
        rival["id"],
        meeting_date="2026-08-24",
        minutes_doc_ref="MIN-2026-Q0-004",
        key="rival",
    )
    assert_status(rival_motion, MotionStatus.CARRIED)

    refused = api.post(
        Paths.proposal_approve(rival["id"]),
        {"approving_motion_id": rival_motion["id"]},
        ctx.chair,
    )
    validate_error(refused, ApiErrorId.SLOT_NOT_REPLACEABLE)
    inert = read_proposal(api, rival["id"])
    assert_status(inert, ProposalStatus.UNDER_REVIEW)
    assert inert["approving_motion_id"] is None
    assert_status(read_motion(api, rival_motion["id"]), MotionStatus.CARRIED)
    assert_status(read_proposal(api, incumbent_proposal), ProposalStatus.APPROVED)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=1, available=0)

    rescinded = get_success_data(
        api.post(
            Paths.proposal_rescind(incumbent_proposal),
            {"reason": "the committee prefers the institutional share class of the rival fund"},
            ctx.chair,
        )
    )
    assert_status(rescinded, ProposalStatus.UNDER_REVIEW)
    assert rescinded["approving_motion_id"] is None
    assert_status(read_slot(api, slot_id), SlotStatus.ACTIVE)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=0, available=1)

    approved = get_success_data(
        api.post(
            Paths.proposal_approve(rival["id"]),
            {"approving_motion_id": rival_motion["id"]},
            ctx.chair,
        )
    )
    assert_status(approved, ProposalStatus.APPROVED)
    assert approved["approving_motion_id"] == rival_motion["id"]
    assert_status(read_slot(api, slot_id), SlotStatus.PENDING_REPLACEMENT)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=1, available=0)
    displaced = read_proposal(api, incumbent_proposal)
    assert_status(displaced, ProposalStatus.WITHDRAWN)
    assert displaced["superseded_by_proposal_id"] == rival["id"]
