"""Multi-hop cascades, checked hop by hop.

Two triggers in this system set off a chain that crosses several entities.
Finalizing a quarterly review (PRD 3.5) runs five ordered hops: the score write
lands on the funds, the score drives the watch dimension, the watch dimension
drives the slot, the slot drives the plan's at-risk ratio and menu posture, and
the posture blocks every live replacement proposal.  Retiring a menu slot
(PRD 3.3) runs the shorter chain: the slot goes, its seated fund is marked for
removal, the capacity partition and the ratio move, and the posture relaxes.

Both worlds below are built on a deliberately small two-slot menu, because one
at-risk slot out of two is exactly the 0.5000 ratio at which PRD 2.9 freezes the
menu.
"""

from typing import Any, Dict

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_at_risk_bookkeeping,
    assert_capacity_triple,
    assert_fields,
    assert_plan_assets_conserved,
    assert_posture_matches_ratio,
    assert_ratio,
    assert_score,
    assert_status,
    get_success_data,
)
from test_helpers.factories import Paths
from test_helpers.fixtures import (
    Ctx,
    create_fund,
    create_slot,
    draft_proposal,
    finalize_review,
    open_review,
    present_and_document,
    read_fund,
    read_plan,
    read_proposal,
    read_review,
    read_slot,
    seat_fund,
    setup_adopted_ips,
    submit_proposal,
    submit_scorecard,
)
from test_helpers.test_users import sponsor_headers
from test_helpers.types import (
    AssetClass,
    CreditAccrualStatus,
    FeeDisclosureStatus,
    FundMenuStatus,
    MenuPosture,
    ProposalStatus,
    ReviewStatus,
    ShareClass,
    SlotDesignation,
    SlotStatus,
    WatchRecommendation,
    WatchStatus,
)

#: A roomy capacity, so the partition arithmetic is visible rather than pinned
#: at zero available positions.
CAPACITY = 8

#: The two seated funds hold 8,000,000.00 and 4,000,000.00 of participant money.
TOTAL_ASSETS_CENTS = 1200000000

#: A core-bond successor to offer against the seated bond fund.  It clears every
#: default selection criterion of PRD 3.3.
BOND_SUCCESSOR: Dict[str, Any] = {
    "ticker": "BNDSX",
    "fund_name": "Beacon Core Bond Successor",
    "asset_class_code": AssetClass.CORE_BOND,
    "share_class_code": ShareClass.INSTITUTIONAL,
    "gross_expense_ratio_bps": 20,
    "net_expense_ratio_bps": 20,
    "revenue_share_bps": 4,
    "peer_median_expense_bps": 30,
    "track_record_quarters": 48,
    "manager_tenure_quarters": 24,
    "manager_change_flag": False,
    "style_drift_r2": 0.9600,
    "plan_assets_cents": 0,
}

#: Quarter-0 measurements for the large-cap incumbent.  Six hundred basis points
#: behind its benchmark on both trailing windows, bottom-vigintile peer rank and
#: five basis points over the peer median: a composite of 39.00, below the 40.00
#: watch trigger.
LARGE_CAP_BREACH: Dict[str, Any] = {
    "trailing_return_3y_bps": 100,
    "trailing_return_5y_bps": 200,
    "benchmark_return_3y_bps": 700,
    "benchmark_return_5y_bps": 800,
    "peer_rank_pct": 95,
    "style_drift_r2": 0.8500,
    "net_expense_ratio_bps": 45,
    "peer_median_expense_bps": 40,
    "manager_tenure_quarters": 20,
    "manager_change_flag": False,
}

#: Quarter-0 measurements for the bond incumbent: six hundred basis points ahead
#: on both windows, top-decile peer rank and cheaper than the median, giving a
#: composite of 98.00 and no recommendation at all.
BOND_CLEAN: Dict[str, Any] = {
    "trailing_return_3y_bps": 900,
    "trailing_return_5y_bps": 1000,
    "benchmark_return_3y_bps": 300,
    "benchmark_return_5y_bps": 400,
    "peer_rank_pct": 10,
    "style_drift_r2": 0.9500,
    "net_expense_ratio_bps": 25,
    "peer_median_expense_bps": 30,
    "manager_tenure_quarters": 30,
    "manager_change_flag": False,
}


@pytest.fixture
def two_slot_menu(api: ApiClient) -> Ctx:
    """An eight-position menu with exactly two seated CORE slots — large cap at
    index 1 and core bond at index 2 — plus a candidate successor for each."""
    ctx = setup_adopted_ips(api, menu_slot_capacity=CAPACITY)
    create_fund(ctx, "lc_a")
    create_fund(ctx, "bond")
    create_fund(ctx, "lc_b")
    create_fund(ctx, "bond_b", **BOND_SUCCESSOR)
    create_slot(ctx, "lc", AssetClass.US_LARGE_CAP, 1)
    create_slot(ctx, "bond", AssetClass.CORE_BOND, 2)
    seat_fund(ctx, "lc", "lc_a")
    seat_fund(ctx, "bond", "bond")
    ctx.refresh_plan()
    return ctx


def _score_the_quarter(ctx: Ctx) -> None:
    """Open quarter 0, score both incumbents, present into a quorate meeting and
    approve its minutes, leaving the review one call from finalization."""
    open_review(ctx, 0)
    submit_scorecard(ctx, "lc_a", LARGE_CAP_BREACH, key="lc")
    submit_scorecard(ctx, "bond", BOND_CLEAN, key="cb")
    present_and_document(ctx)
    ctx.refresh_plan()


@pytest.fixture
def finalize_cascade_world(api: ApiClient, two_slot_menu: Ctx) -> Ctx:
    """The scored two-slot menu plus two live replacement proposals: one already
    UNDER_REVIEW on the large-cap slot and one still DRAFT on the bond slot."""
    ctx = two_slot_menu
    first = draft_proposal(ctx, "lc", "lc_a", "lc_b", key="p1")
    submit_proposal(ctx, first["id"], key="p1")
    draft_proposal(ctx, "bond", "bond", "bond_b", key="p2")
    _score_the_quarter(ctx)
    return ctx


@pytest.fixture
def retire_cascade_world(api: ApiClient, two_slot_menu: Ctx) -> Ctx:
    """The same two-slot menu with quarter 0 already finalized and no proposals
    outstanding: one slot AT_RISK, a 0.5000 ratio and a FROZEN posture."""
    ctx = two_slot_menu
    _score_the_quarter(ctx)
    finalize_review(ctx)
    ctx.refresh_plan()
    return ctx


# --------------------------------------------------------------------------
# The finalize cascade, hop by hop (PRD 3.5)
# --------------------------------------------------------------------------

def test_the_quarter_scores_the_two_incumbents_apart(
    api: ApiClient, finalize_cascade_world: Ctx
):
    """The two scorecards resolve to 39.00 and 98.00, so only the large-cap fund
    carries a WATCH recommendation into the cascade.

    Design: Difficulty/transitive_cascade/finalize_score_to_watch_to_slot_to_posture_to_blocked_proposals_depth4
    """
    ctx = finalize_cascade_world
    large_cap = ctx.scorecards["lc"]
    bond = ctx.scorecards["cb"]

    assert_score(large_cap["performance_component"], "0.00")
    assert_score(large_cap["peer_component"], "5.00")
    assert_score(large_cap["expense_component"], "90.00")
    assert_score(large_cap["style_component"], "100.00")
    assert_score(large_cap["manager_component"], "100.00")
    assert_score(large_cap["composite_score"], "39.00")
    assert large_cap["watch_recommendation"] == WatchRecommendation.WATCH

    assert_score(bond["performance_component"], "100.00")
    assert_score(bond["peer_component"], "90.00")
    assert_score(bond["expense_component"], "100.00")
    assert_score(bond["style_component"], "100.00")
    assert_score(bond["manager_component"], "100.00")
    assert_score(bond["composite_score"], "98.00")
    assert bond["watch_recommendation"] == WatchRecommendation.NONE

    # Nothing has cascaded yet: the review is only awaiting the chair.
    assert_status(read_review(api, ctx.review["id"]), ReviewStatus.PENDING_MINUTES)
    plan = read_plan(api, ctx.plan_id)
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000")
    assert_status(plan, MenuPosture.OPEN, "menu_posture")


def test_hop_zero_writes_each_composite_score_onto_its_fund(
    api: ApiClient, finalize_cascade_world: Ctx
):
    """Finalization stamps the review and copies every submitted composite score
    onto the fund it measured.

    Design: Difficulty/transitive_cascade/finalize_score_to_watch_to_slot_to_posture_to_blocked_proposals_depth4
    """
    ctx = finalize_cascade_world

    review = finalize_review(ctx)

    assert_fields(review, status=ReviewStatus.FINALIZED, finalized_quarter_index=0)
    assert str(review["finalized_at"]).startswith("2026-08-01T00:00:00")

    large_cap = read_fund(api, ctx.fund("lc_a")["id"])
    assert_score(large_cap["latest_composite_score"], "39.00")
    assert large_cap["last_scored_quarter_index"] == 0

    bond = read_fund(api, ctx.fund("bond")["id"])
    assert_score(bond["latest_composite_score"], "98.00")
    assert bond["last_scored_quarter_index"] == 0


def test_hop_one_moves_the_breaching_fund_from_clear_to_watch(
    api: ApiClient, finalize_cascade_world: Ctx
):
    """The score write drives the watch dimension: the breaching fund leaves
    CLEAR with its prior value snapshotted, and the clean fund does not move.

    Design: Difficulty/transitive_cascade/finalize_score_to_watch_to_slot_to_posture_to_blocked_proposals_depth4
    """
    ctx = finalize_cascade_world

    review = finalize_review(ctx)

    large_cap = read_fund(api, ctx.fund("lc_a")["id"])
    assert_fields(
        large_cap,
        watch_status=WatchStatus.WATCH,
        watch_status_before_last_review=WatchStatus.CLEAR,
        watch_started_quarter_index=0,
        consecutive_breach_quarters=1,
        menu_status=FundMenuStatus.ACTIVE,
    )

    bond = read_fund(api, ctx.fund("bond")["id"])
    assert_fields(
        bond,
        watch_status=WatchStatus.CLEAR,
        watch_started_quarter_index=None,
        consecutive_breach_quarters=0,
        menu_status=FundMenuStatus.ACTIVE,
    )

    # Exactly one fund left CLEAR in this hop.
    assert review["watch_additions_count"] == 1


def test_hop_two_puts_the_watched_fund_s_slot_at_risk(
    api: ApiClient, finalize_cascade_world: Ctx
):
    """The watch move drives the slot: the slot holding the newly watched fund
    goes ACTIVE to AT_RISK with its prior status snapshotted, and the bond slot
    is left alone.

    Design: Difficulty/transitive_cascade/finalize_score_to_watch_to_slot_to_posture_to_blocked_proposals_depth4
    """
    ctx = finalize_cascade_world

    finalize_review(ctx)

    large_cap_slot = read_slot(api, ctx.slot("lc")["id"])
    assert_fields(
        large_cap_slot,
        status=SlotStatus.AT_RISK,
        status_before_last_review=SlotStatus.ACTIVE,
        at_risk_since_quarter_index=0,
        current_fund_id=ctx.fund("lc_a")["id"],
        designation=SlotDesignation.CORE,
    )

    bond_slot = read_slot(api, ctx.slot("bond")["id"])
    assert_fields(
        bond_slot,
        status=SlotStatus.ACTIVE,
        status_before_last_review=None,
        at_risk_since_quarter_index=None,
        current_fund_id=ctx.fund("bond")["id"],
    )


def test_hop_three_lifts_the_ratio_and_freezes_the_menu(
    api: ApiClient, finalize_cascade_world: Ctx
):
    """One at-risk slot out of two occupied is a ratio of 0.5000, which is the
    inclusive boundary at which the posture reaches FROZEN.

    Design: Difficulty/transitive_cascade/finalize_score_to_watch_to_slot_to_posture_to_blocked_proposals_depth4
    """
    ctx = finalize_cascade_world
    before = read_plan(api, ctx.plan_id)
    assert_status(before, MenuPosture.OPEN, "menu_posture")

    finalize_review(ctx)

    plan = read_plan(api, ctx.plan_id)
    assert_ratio(plan["at_risk_slot_ratio"], "0.5000")
    assert_status(plan, MenuPosture.FROZEN, "menu_posture")
    assert_posture_matches_ratio(plan)
    assert_at_risk_bookkeeping(
        plan,
        [read_slot(api, ctx.slot("lc")["id"]), read_slot(api, ctx.slot("bond")["id"])],
    )


def test_hop_four_blocks_every_live_proposal_keeping_its_prior_status(
    api: ApiClient, finalize_cascade_world: Ctx
):
    """A FROZEN posture blocks both live proposals regardless of which slot they
    sit on, each recording the exact status it was blocked out of.

    Design: Difficulty/transitive_cascade/finalize_score_to_watch_to_slot_to_posture_to_blocked_proposals_depth4
    """
    ctx = finalize_cascade_world
    under_review_id = ctx.proposals["p1"]["id"]
    draft_id = ctx.proposals["p2"]["id"]
    assert_status(read_proposal(api, under_review_id), ProposalStatus.UNDER_REVIEW)
    assert_status(read_proposal(api, draft_id), ProposalStatus.DRAFT)

    finalize_review(ctx)

    blocked_from_review = read_proposal(api, under_review_id)
    assert_fields(
        blocked_from_review,
        status=ProposalStatus.BLOCKED,
        pre_block_status=ProposalStatus.UNDER_REVIEW,
        revision_round=0,
    )
    blocked_from_draft = read_proposal(api, draft_id)
    assert_fields(
        blocked_from_draft,
        status=ProposalStatus.BLOCKED,
        pre_block_status=ProposalStatus.DRAFT,
        revision_round=0,
    )


def test_the_finalize_cascade_halts_at_the_dimensions_it_does_not_own(
    api: ApiClient, finalize_cascade_world: Ctx
):
    """A WATCH move never reaches the menu dimension, never touches the clean
    fund's slot and never moves a single menu position.

    Design: Difficulty/transitive_cascade/finalize_score_to_watch_to_slot_to_posture_to_blocked_proposals_depth4
    """
    ctx = finalize_cascade_world

    finalize_review(ctx)

    # Only a TERMINATION_PENDING escalation may cross into the menu dimension.
    large_cap = read_fund(api, ctx.fund("lc_a")["id"])
    assert_fields(
        large_cap,
        menu_status=FundMenuStatus.ACTIVE,
        menu_status_before_last_review=None,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
    )
    # The two candidates were never scored, so nothing landed on them.
    for key in ("lc_b", "bond_b"):
        candidate = read_fund(api, ctx.fund(key)["id"])
        assert_fields(
            candidate,
            menu_status=FundMenuStatus.CANDIDATE,
            watch_status=WatchStatus.CLEAR,
            latest_composite_score=None,
            last_scored_quarter_index=None,
            consecutive_breach_quarters=0,
        )

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=2, reserved=0, available=6)
    assert_plan_assets_conserved(plan, TOTAL_ASSETS_CENTS)
    assert_status(plan, FeeDisclosureStatus.COMPLIANT, "fee_disclosure_status")


# --------------------------------------------------------------------------
# The slot-retirement cascade, hop by hop (PRD 3.3)
# --------------------------------------------------------------------------


def _retire(ctx: Ctx, slot_id: str):
    """Retirement is the plan sponsor's act."""
    return ctx.client.post(Paths.slot_retire(slot_id), {}, sponsor_headers())


def test_the_finalized_quarter_leaves_the_menu_frozen_before_the_retirement(
    api: ApiClient, retire_cascade_world: Ctx
):
    """The world the retirement starts from: one AT_RISK slot out of two, a
    0.5000 ratio and a FROZEN posture, which PRD 2.9 does not use to gate slot
    retirement.

    Design: Difficulty/transitive_cascade/slot_retire_to_fund_pending_removal_to_ratio_to_posture_depth3
    """
    ctx = retire_cascade_world

    assert_fields(
        read_slot(api, ctx.slot("lc")["id"]),
        status=SlotStatus.AT_RISK,
        designation=SlotDesignation.CORE,
        current_fund_id=ctx.fund("lc_a")["id"],
    )
    assert_fields(
        read_fund(api, ctx.fund("lc_a")["id"]),
        menu_status=FundMenuStatus.ACTIVE,
        watch_status=WatchStatus.WATCH,
        consecutive_breach_quarters=1,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
    )

    plan = read_plan(api, ctx.plan_id)
    assert_ratio(plan["at_risk_slot_ratio"], "0.5000")
    assert_status(plan, MenuPosture.FROZEN, "menu_posture")
    assert_capacity_triple(plan, occupied=2, reserved=0, available=6)
    assert_plan_assets_conserved(plan, TOTAL_ASSETS_CENTS)


def test_hop_zero_retirement_keeps_the_seated_fund_on_the_slot_row(
    api: ApiClient, retire_cascade_world: Ctx
):
    """Retiring the at-risk slot moves it to the terminal RETIRED status while
    keeping its seated fund reference for the audit trail.

    Design: Difficulty/transitive_cascade/slot_retire_to_fund_pending_removal_to_ratio_to_posture_depth3
    """
    ctx = retire_cascade_world
    slot_id = ctx.slot("lc")["id"]

    retired = get_success_data(_retire(ctx, slot_id))

    assert_fields(
        retired,
        status=SlotStatus.RETIRED,
        current_fund_id=ctx.fund("lc_a")["id"],
    )
    assert_status(read_slot(api, slot_id), SlotStatus.RETIRED)


def test_hop_one_marks_the_seated_fund_pending_removal_only_on_the_menu(
    api: ApiClient, retire_cascade_world: Ctx
):
    """The slot's departure drives the fund's menu dimension to PENDING_REMOVAL
    and leaves its watch dimension and its credit accrual exactly as they were.

    Design: Difficulty/transitive_cascade/slot_retire_to_fund_pending_removal_to_ratio_to_posture_depth3
    """
    ctx = retire_cascade_world

    get_success_data(_retire(ctx, ctx.slot("lc")["id"]))

    fund = read_fund(api, ctx.fund("lc_a")["id"])
    assert_fields(
        fund,
        menu_status=FundMenuStatus.PENDING_REMOVAL,
        watch_status=WatchStatus.WATCH,
        watch_started_quarter_index=0,
        consecutive_breach_quarters=1,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
        last_scored_quarter_index=0,
    )
    assert_score(fund["latest_composite_score"], "39.00")


def test_hop_two_returns_the_position_to_available_and_clears_the_ratio(
    api: ApiClient, retire_cascade_world: Ctx
):
    """The fund's departure drives the plan's conserved partition — one occupied
    position becomes available — and empties the at-risk numerator.

    Design: Difficulty/transitive_cascade/slot_retire_to_fund_pending_removal_to_ratio_to_posture_depth3
    """
    ctx = retire_cascade_world

    get_success_data(_retire(ctx, ctx.slot("lc")["id"]))

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=1, reserved=0, available=7)
    assert plan["menu_slot_capacity"] == CAPACITY
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000")
    assert_at_risk_bookkeeping(
        plan,
        [read_slot(api, ctx.slot("lc")["id"]), read_slot(api, ctx.slot("bond")["id"])],
    )


def test_hop_three_relaxes_the_posture_back_to_open(
    api: ApiClient, retire_cascade_world: Ctx
):
    """The ratio drop drives the posture back down the ladder from FROZEN to
    OPEN, even though the retired slot's fund is still on watch.

    Design: Difficulty/transitive_cascade/slot_retire_to_fund_pending_removal_to_ratio_to_posture_depth3
    """
    ctx = retire_cascade_world
    assert_status(read_plan(api, ctx.plan_id), MenuPosture.FROZEN, "menu_posture")

    get_success_data(_retire(ctx, ctx.slot("lc")["id"]))

    plan = read_plan(api, ctx.plan_id)
    assert_status(plan, MenuPosture.OPEN, "menu_posture")
    assert_posture_matches_ratio(plan)
    assert read_fund(api, ctx.fund("lc_a")["id"])["watch_status"] == WatchStatus.WATCH


def test_the_retire_cascade_halts_at_the_other_slot_the_assets_and_the_review(
    api: ApiClient, retire_cascade_world: Ctx
):
    """Retiring one slot leaves the other slot, the plan's asset total and the
    finalized review untouched.

    Design: Difficulty/transitive_cascade/slot_retire_to_fund_pending_removal_to_ratio_to_posture_depth3
    """
    ctx = retire_cascade_world

    get_success_data(_retire(ctx, ctx.slot("lc")["id"]))

    assert_fields(
        read_slot(api, ctx.slot("bond")["id"]),
        status=SlotStatus.ACTIVE,
        current_fund_id=ctx.fund("bond")["id"],
        at_risk_since_quarter_index=None,
    )
    assert_fields(
        read_fund(api, ctx.fund("bond")["id"]),
        menu_status=FundMenuStatus.ACTIVE,
        watch_status=WatchStatus.CLEAR,
        consecutive_breach_quarters=0,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
    )

    # A fund marked PENDING_REMOVAL still counts toward the plan's asset total
    # under PRD 2.10, so retirement conserves it exactly.
    plan = read_plan(api, ctx.plan_id)
    assert_plan_assets_conserved(plan, TOTAL_ASSETS_CENTS)
    assert_status(plan, FeeDisclosureStatus.COMPLIANT, "fee_disclosure_status")

    review = read_review(api, ctx.review["id"])
    assert_fields(
        review,
        status=ReviewStatus.FINALIZED,
        finalized_quarter_index=0,
        watch_additions_count=1,
    )
