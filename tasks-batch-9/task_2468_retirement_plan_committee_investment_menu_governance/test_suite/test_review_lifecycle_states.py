"""Quarterly-review lifecycle behaviour (PRD 3.5 and 3.6).

A review never leaves DRAFT by a client call: the first scorecard drives it into
SCORING, presentation locks it, and finalization runs the four-hop watch, slot,
posture and proposal cascade.  Reopening a finalized review is the exact
compensating inverse of that cascade, and it is only available for one quarter.
"""

import pytest

from test_helpers.api_client import ApiClient
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
from test_helpers.factories import Paths
from test_helpers.fixtures import (
    CLEAN_SCORECARDS,
    Ctx,
    adjourn,
    advance_quarter,
    appoint_member,
    approve_minutes,
    assign_training,
    complete_training,
    create_fund,
    create_seat,
    draft_proposal,
    finalize_review,
    open_meeting,
    open_review,
    present_review,
    read_fund,
    read_member,
    read_plan,
    read_proposal,
    read_review,
    read_slot,
    register_plan,
    setup_breach_quarter,
    sign_acceptance,
    submit_scorecard,
)
from test_helpers.test_users import auditor_headers, sponsor_headers
from test_helpers.types import (
    AssetClass,
    MemberStatus,
    MenuPosture,
    ProposalStatus,
    ReviewStatus,
    ScorecardStatus,
    ScoringVariant,
    SeatClass,
    SlotStatus,
    TrainingModule,
    WatchRecommendation,
    WatchStatus,
)


#: The spare small-cap candidate the blocked-proposal scenarios replace with.
SMALL_CAP_SUCCESSOR = {
    "ticker": "SMLGX",
    "fund_name": "Summit Small Cap Growth R6",
    "asset_class_code": AssetClass.US_SMALL_CAP,
    "share_class_code": "R6",
    "gross_expense_ratio_bps": 55,
    "net_expense_ratio_bps": 55,
    "revenue_share_bps": 0,
    "peer_median_expense_bps": 55,
    "track_record_quarters": 24,
    "manager_tenure_quarters": 18,
    "manager_change_flag": False,
    "style_drift_r2": 0.9300,
    "plan_assets_cents": 0,
}


def read_scorecard(client: ApiClient, scorecard_id: str):
    """Read one fund scorecard as the read-only auditor."""
    return get_success_data(
        client.get(Paths.scorecard(scorecard_id), auditor_headers())
    )


@pytest.fixture
def breach_quarter_with_draft_proposal(api: ApiClient) -> Ctx:
    """Quarter 0 scored with the small-cap fund at exactly 40.00 and the
    international fund at exactly 25.00, presented and minuted, plus a DRAFT
    replacement proposal sitting on the small-cap slot.  One finalize call away
    from the full breach cascade."""
    ctx = setup_breach_quarter(api)
    create_fund(ctx, "small_b", **SMALL_CAP_SUCCESSOR)
    draft_proposal(ctx, "small", "small", "small_b", key="small")
    ctx.refresh_plan()
    return ctx


# --------------------------------------------------------------------------
# The clean walk: DRAFT -> SCORING -> PENDING_MINUTES -> FINALIZED
# --------------------------------------------------------------------------


def test_review_walks_draft_scoring_pending_minutes_finalized(api, full_menu):
    """A review opens DRAFT, is driven to SCORING by its first scorecard, to
    PENDING_MINUTES by presentation and to FINALIZED by the chair.

    Design: Corner/state_machines/quarterly_review_walks_draft_scoring_pending_minutes_finalized
    """
    ctx = full_menu
    review = open_review(ctx, 0)
    assert_status(review, ReviewStatus.DRAFT)
    assert_fields(
        review,
        ips_id=ctx.ips_id,
        scoring_variant=ScoringVariant.TRAILING_PERIOD,
        scorecard_count=0,
        submitted_scorecard_count=0,
        reopen_count=0,
        finalized_at=None,
        finalized_quarter_index=None,
    )

    # The first scorecard is what moves the review out of DRAFT; no client call
    # can do it (PRD 3.5 scorecard submission).
    submit_scorecard(ctx, "lc_a", CLEAN_SCORECARDS["lc_a"])
    assert_status(read_review(api, review["id"]), ReviewStatus.SCORING)

    for fund_key in ("bond", "small", "intl", "tips"):
        submit_scorecard(ctx, fund_key, CLEAN_SCORECARDS[fund_key])

    meeting = open_meeting(ctx, "2026-08-10", 0, key="review")
    presented = present_review(ctx, meeting["id"])
    assert_status(presented, ReviewStatus.PENDING_MINUTES)

    adjourn(ctx, meeting["id"])
    approve_minutes(ctx, meeting["id"], "MIN-2026-Q0-002")

    finalized = finalize_review(ctx)
    assert_status(finalized, ReviewStatus.FINALIZED)
    assert_fields(
        finalized,
        finalized_quarter_index=0,
        meeting_id=meeting["id"],
        ips_id=ctx.ips_id,
        scoring_variant=ScoringVariant.TRAILING_PERIOD,
        reopen_count=0,
        scorecard_count=5,
        submitted_scorecard_count=5,
    )
    assert finalized["finalized_at"] is not None


def test_finalizing_a_clean_quarter_scores_every_fund_and_moves_no_watch_status(
    api, finalized_quarter
):
    """Finalization writes each scorecard's composite score onto its fund, but a
    quarter with no breach leaves every fund CLEAR and the posture OPEN.

    Design: Corner/state_machines/quarterly_review_walks_draft_scoring_pending_minutes_finalized
    """
    ctx = finalized_quarter
    expected = {
        "lc_a": "76.20",
        "bond": "75.52",
        "small": "59.88",
        "intl": "72.00",
        "tips": "70.00",
    }
    for fund_key, score in expected.items():
        fund = read_fund(api, ctx.fund(fund_key)["id"])
        assert_score(fund["latest_composite_score"], score, f"{fund_key} composite")
        assert_fields(
            fund,
            last_scored_quarter_index=0,
            watch_status=WatchStatus.CLEAR,
            consecutive_breach_quarters=0,
            watch_started_quarter_index=None,
        )

    plan = read_plan(api, ctx.plan_id)
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000")
    assert_status(plan, MenuPosture.OPEN, field="menu_posture")


# --------------------------------------------------------------------------
# The breach cascade and its inverse
# --------------------------------------------------------------------------


def test_finalize_drives_the_four_hop_breach_cascade_to_a_restricted_posture(
    api, breach_quarter_with_draft_proposal
):
    """One finalize ripples in order: scores land, two funds leave CLEAR at the
    40.00 and 25.00 ladder boundaries, their slots go AT_RISK, the ratio of
    0.4000 makes the posture RESTRICTED, and the proposal on an at-risk slot is
    BLOCKED.

    Design: Corner/state_machines/finalize_drives_the_four_hop_breach_cascade_to_a_restricted_posture
    """
    ctx = breach_quarter_with_draft_proposal
    finalized = finalize_review(ctx)
    assert_status(finalized, ReviewStatus.FINALIZED)
    assert finalized["finalized_at"] is not None
    assert_fields(finalized, watch_additions_count=2)

    # The two breaching measurements land exactly on the ladder boundaries
    # (PRD 3.5 composite score, PRD 3.6 watch ladder).
    small_card = read_scorecard(api, ctx.scorecards["small"]["id"])
    for field, value in (
        ("performance_component", "20.00"),
        ("peer_component", "9.00"),
        ("expense_component", "60.00"),
        ("style_component", "100.00"),
        ("manager_component", "82.00"),
        ("composite_score", "40.00"),
    ):
        assert_score(small_card[field], value, f"small {field}")
    assert_status(small_card, WatchRecommendation.WATCH, field="watch_recommendation")

    intl_card = read_scorecard(api, ctx.scorecards["intl"]["id"])
    for field, value in (
        ("performance_component", "0.00"),
        ("peer_component", "0.00"),
        ("expense_component", "70.00"),
        ("style_component", "100.00"),
        ("manager_component", "10.00"),
        ("composite_score", "25.00"),
    ):
        assert_score(intl_card[field], value, f"intl {field}")
    assert_status(
        intl_card, WatchRecommendation.REMEDIATION, field="watch_recommendation"
    )

    # Hop 1: the watch dimension moves, snapshotting the prior value.
    small_fund = read_fund(api, ctx.fund("small")["id"])
    assert_fields(
        small_fund,
        watch_status=WatchStatus.WATCH,
        watch_started_quarter_index=0,
        consecutive_breach_quarters=1,
        watch_status_before_last_review=WatchStatus.CLEAR,
        last_scored_quarter_index=0,
    )
    intl_fund = read_fund(api, ctx.fund("intl")["id"])
    assert_fields(
        intl_fund,
        watch_status=WatchStatus.REMEDIATION,
        last_scored_quarter_index=0,
    )
    for fund_key in ("lc_a", "bond", "tips"):
        healthy = read_fund(api, ctx.fund(fund_key)["id"])
        assert_fields(
            healthy, watch_status=WatchStatus.CLEAR, consecutive_breach_quarters=0
        )

    # Hop 2: the two slots holding those funds go ACTIVE -> AT_RISK.
    for slot_key in ("small", "intl"):
        slot = read_slot(api, ctx.slot(slot_key)["id"])
        assert_fields(
            slot,
            status=SlotStatus.AT_RISK,
            status_before_last_review=SlotStatus.ACTIVE,
            at_risk_since_quarter_index=0,
        )
    for slot_key in ("lc", "bond", "tips"):
        assert_status(read_slot(api, ctx.slot(slot_key)["id"]), SlotStatus.ACTIVE)

    # Hop 3: 2 of 5 counted slots is exactly 0.4000, which is RESTRICTED and
    # not FROZEN (PRD 2.9 posture ladder).
    plan = read_plan(api, ctx.plan_id)
    assert_ratio(plan["at_risk_slot_ratio"], "0.4000")
    assert_status(plan, MenuPosture.RESTRICTED, field="menu_posture")

    # Hop 4: only the proposal whose incoming fund matches an at-risk slot's
    # asset class is blocked, and the cascade moves no capacity.
    proposal = read_proposal(api, ctx.proposals["small"]["id"])
    assert_fields(
        proposal,
        status=ProposalStatus.BLOCKED,
        pre_block_status=ProposalStatus.DRAFT,
        revision_round=0,
    )
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)


def test_review_reopen_inverts_the_whole_breach_cascade(
    api, breach_quarter_with_draft_proposal
):
    """Reopening restores both funds and both slots from their snapshots, relaxes
    the posture back to OPEN, releases the blocked proposal to exactly its
    pre-block status and reverts every scored fund's composite to null.

    Design: Corner/state_machines/review_reopen_inverts_the_whole_breach_cascade_with_no_drift
    """
    ctx = breach_quarter_with_draft_proposal
    finalize_review(ctx)

    reopened = get_success_data(
        api.post(
            Paths.review_reopen(ctx.review["id"]),
            {
                "reason": "The consultant restated the small cap and international "
                "expense inputs after finalize."
            },
            sponsor_headers(),
        )
    )
    assert_status(reopened, ReviewStatus.REOPENED)
    assert_fields(reopened, reopen_count=1, finalized_at=None)

    for fund_key in ("small", "intl"):
        fund = read_fund(api, ctx.fund(fund_key)["id"])
        assert_fields(
            fund,
            watch_status=WatchStatus.CLEAR,
            consecutive_breach_quarters=0,
            latest_composite_score=None,
        )

    # Every fund the reopened quarter scored reverts, not just the breaching two.
    for fund_key in ("lc_a", "bond", "tips"):
        fund = read_fund(api, ctx.fund(fund_key)["id"])
        assert fund["latest_composite_score"] is None, (
            f"{fund_key} kept a score from the reopened quarter: "
            f"{fund['latest_composite_score']!r}"
        )

    for slot_key in ("small", "intl"):
        assert_status(read_slot(api, ctx.slot(slot_key)["id"]), SlotStatus.ACTIVE)

    plan = read_plan(api, ctx.plan_id)
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000")
    assert_status(plan, MenuPosture.OPEN, field="menu_posture")

    proposal = read_proposal(api, ctx.proposals["small"]["id"])
    assert_fields(
        proposal,
        status=ProposalStatus.DRAFT,
        pre_block_status=None,
        revision_round=0,
    )

    # The reopen reverts entity state, never the measurements themselves.
    small_card = read_scorecard(api, ctx.scorecards["small"]["id"])
    assert_status(small_card, ScorecardStatus.SUBMITTED)
    assert_score(small_card["composite_score"], "40.00")


def test_reopening_a_review_two_quarters_stale_is_rejected(
    api, breach_quarter_with_draft_proposal
):
    """The reopen window is one quarter wide: with the fiscal quarter advanced
    twice past the review's own quarter the call is refused and the whole breach
    cascade is left standing.

    Design: Corner/state_machines/reopening_a_review_two_quarters_stale_is_rejected
    """
    ctx = breach_quarter_with_draft_proposal
    finalize_review(ctx)
    advance_quarter(ctx)
    advance_quarter(ctx)

    response = api.post(
        Paths.review_reopen(ctx.review["id"]),
        {"reason": "Late attempt to restate a quarter that has already closed twice."},
        sponsor_headers(),
    )
    validate_error(response, ApiErrorId.QUARTER_CLOSED)

    review = read_review(api, ctx.review["id"])
    assert_fields(review, status=ReviewStatus.FINALIZED, reopen_count=0)

    plan = read_plan(api, ctx.plan_id)
    assert_fields(plan, fiscal_quarter_index=2)
    assert_status(plan, MenuPosture.RESTRICTED, field="menu_posture")

    assert_status(read_fund(api, ctx.fund("small")["id"]), WatchStatus.WATCH, field="watch_status")
    assert_status(read_slot(api, ctx.slot("small")["id"]), SlotStatus.AT_RISK)
    proposal = read_proposal(api, ctx.proposals["small"]["id"])
    assert_fields(
        proposal,
        status=ProposalStatus.BLOCKED,
        pre_block_status=ProposalStatus.DRAFT,
    )


# --------------------------------------------------------------------------
# The member fork-join: the training branch alone is a dead end
# --------------------------------------------------------------------------


def test_the_training_branch_alone_can_never_activate_a_member(api):
    """A member sitting in TRAINING_ASSIGNED with both required modules complete
    still cannot be activated, because the acceptance branch has never run; once
    the acceptance is signed the same call succeeds.

    Design: Corner/state_machines/the_training_branch_alone_can_never_activate_a_member
    """
    plan = register_plan(api)
    seat = create_seat(
        api,
        plan["id"],
        seat_code="S-CHAIR",
        seat_class=SeatClass.CHAIR,
        voting=True,
        seat_index=1,
    )
    member = appoint_member(api, seat["id"])
    for module in TrainingModule.REQUIRED:
        record = assign_training(api, member["id"], module_code=module)
        complete_training(api, record["id"], member["id"], 92.00)

    ready = read_member(api, member["id"])
    assert_fields(
        ready,
        status=MemberStatus.TRAINING_ASSIGNED,
        acceptance_signed_at=None,
    )

    response = api.post(Paths.activate(member["id"]), {}, sponsor_headers())
    validate_error(response, ApiErrorId.FIDUCIARY_ACCEPTANCE_MISSING)

    still_waiting = read_member(api, member["id"])
    assert_fields(
        still_waiting,
        status=MemberStatus.TRAINING_ASSIGNED,
        acceptance_signed_at=None,
    )
    plan_now = read_plan(api, plan["id"])
    assert_fields(plan_now, documented_acceptance_count=0)
    assert_status(plan_now, MenuPosture.FROZEN, field="menu_posture")

    # Closing the other branch of the join unblocks the very same call.
    sign_acceptance(api, member["id"])
    activated = get_success_data(
        api.post(Paths.activate(member["id"]), {}, sponsor_headers())
    )
    assert_status(activated, MemberStatus.ACTIVE)
