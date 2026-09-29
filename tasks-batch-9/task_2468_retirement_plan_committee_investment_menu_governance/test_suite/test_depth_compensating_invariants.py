"""Compensating actions that have to undo their forward action exactly.

Two compensations are exercised.  Rescinding a replacement approval (PRD 3.7)
must put the plan's capacity triple back to the values it held before the
approval reserved a position, send the slot back to the state its seated fund's
watch status dictates, and clear the spent authorising motion off the proposal.
Reopening a finalized review (PRD 3.6) must invert every hop of the finalization
cascade of PRD 3.5 from the stored snapshots — the watch dimension, the breach
counter, the composite score, the slot state, the at-risk ratio, the posture and
the blocked proposals — while the two ratchets it is documented to keep, the
review's `reopen_count` and each fund's `last_scored_quarter_index`, stay put.

Every test captures the whole before-state first, so the restoration is compared
field by field rather than spot-checked.
"""

from typing import Any, Dict

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_credit_balance_identity,
    assert_fields,
    assert_ratio,
    assert_score,
    assert_snapshot_restored,
    assert_status,
    get_success_data,
    validate_error,
)
from test_helpers.factories import Paths, seat_fund_payload
from test_helpers.fixtures import (
    BREACH_SCORECARDS,
    CLEAN_SCORECARDS,
    Ctx,
    approve_proposal,
    create_fund,
    create_slot,
    draft_proposal,
    finalize_review,
    hold_meeting_and_carry_motion,
    open_review,
    present_and_document,
    read_fund,
    read_proposal,
    read_slot,
    seat_fund,
    setup_adopted_ips,
    setup_scored_quarter,
    submit_proposal,
    submit_scorecard,
)
from test_helpers.test_users import consultant_headers, sponsor_headers
from test_helpers.types import (
    AssetClass,
    FundMenuStatus,
    MenuPosture,
    MotionSubjectType,
    ProposalStatus,
    ReviewStatus,
    SlotStatus,
    WatchStatus,
)

#: Quarter 0 is the only quarter these scenarios live in.
QUARTER_ZERO = 0

#: The five CORE slots of the narrow menu used for the capacity work, on a plan
#: whose capacity is deliberately one seat short of five occupants.
NARROW_SLOTS = (
    ("lc", AssetClass.US_LARGE_CAP, 1),
    ("bond", AssetClass.CORE_BOND, 2),
    ("small", AssetClass.US_SMALL_CAP, 3),
    ("intl", AssetClass.INTL_DEVELOPED, 4),
    ("tips", AssetClass.TIPS, 5),
)

#: The four funds seated on that narrow menu, leaving the TIPS slot empty.
NARROW_SEATING = (("lc", "lc_a"), ("bond", "bond"), ("small", "small"), ("intl", "intl"))

#: 8,000,000.00 from the large-cap fund plus 4,000,000.00 from the bond fund;
#: every other catalogue fund carries nothing.
CATALOGUE_ASSETS_CENTS = 1200000000


def _attempt_seating(ctx: Ctx, slot_id: str, fund_id: str):
    return ctx.client.post(
        Paths.seat_fund(slot_id), seat_fund_payload(fund_id), consultant_headers()
    )


def _rescind(ctx: Ctx, proposal_id: str):
    """The chair's rescission call, before any participant notice exists.

    PRD 2.8 makes the narrative `reason` mandatory on this compensating act.
    """
    return ctx.client.post(
        Paths.proposal_rescind(proposal_id),
        {"reason": "The committee wants the mapping cost estimate refreshed."},
        ctx.chair,
    )


def _reopen(ctx: Ctx, review_id: str):
    """The sponsor's compensating power over a finalized review.

    PRD 2.8 makes the narrative `reason` mandatory on this compensating act.
    """
    return ctx.client.post(
        Paths.review_reopen(review_id),
        {"reason": "Recordkeeper restated the quarter's expense feed."},
        sponsor_headers(),
    )


def _four_of_five_menu(api: ApiClient) -> Ctx:
    """Four seated CORE slots on a five-seat menu, so the capacity triple reads
    4 occupied, 0 reserved and 1 available with the TIPS slot still empty."""
    ctx = setup_adopted_ips(api, menu_slot_capacity=5)
    for key in ("lc_a", "bond", "small", "intl", "tips", "lc_b"):
        create_fund(ctx, key)
    for key, asset_class, index in NARROW_SLOTS:
        create_slot(ctx, key, asset_class, index)
    for slot_key, fund_key in NARROW_SEATING:
        seat_fund(ctx, slot_key, fund_key)
    ctx.refresh_plan()
    return ctx


def _approve_large_cap_replacement(
    ctx: Ctx, meeting_date: str = "2026-08-17", minutes_doc_ref: str = "MIN-2026-Q0-003"
) -> Dict[str, Any]:
    """Draft, submit, authorise and approve a replacement of the large-cap fund,
    returning the approved proposal."""
    proposal = draft_proposal(ctx, "lc", "lc_a", "lc_b")
    submit_proposal(ctx, proposal["id"])
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.FUND_REPLACEMENT,
        proposal["id"],
        meeting_date=meeting_date,
        minutes_doc_ref=minutes_doc_ref,
        key="replacement",
    )
    approved = approve_proposal(ctx, proposal["id"], motion["id"])
    assert_fields(approved, approving_motion_id=motion["id"])
    return approved


def test_rescinding_an_approval_puts_the_capacity_triple_back_exactly(api):
    """Rescission returns every capacity counter, the slot and the proposal's
    authorising motion to their exact pre-approval values.

    Design: Difficulty/compensating_invariant/rescind_approval_restores_capacity_triple_exactly
    """
    ctx = _four_of_five_menu(api)
    slot_id = ctx.slot("lc")["id"]
    seated_fund_id = ctx.fund("lc_a")["id"]

    before = ctx.refresh_plan()
    assert_capacity_triple(before, occupied=4, reserved=0, available=1)
    assert_ratio(before["at_risk_slot_ratio"], "0.0000")
    assert_fields(before, menu_posture=MenuPosture.OPEN, menu_slot_capacity=5)
    assert_credit_balance_identity(before)
    slot_before = read_slot(api, slot_id)
    assert_status(slot_before, SlotStatus.ACTIVE)
    assert_fields(slot_before, current_fund_id=seated_fund_id)
    fund_before = read_fund(api, seated_fund_id)
    assert_fields(
        fund_before, watch_status=WatchStatus.CLEAR, menu_status=FundMenuStatus.ACTIVE
    )

    approved = _approve_large_cap_replacement(ctx)
    assert_status(approved, ProposalStatus.APPROVED)
    during = ctx.refresh_plan()
    assert_capacity_triple(during, occupied=4, reserved=1, available=0)
    assert_ratio(during["at_risk_slot_ratio"], "0.2500")
    assert_fields(during, menu_posture=MenuPosture.RESTRICTED)
    assert_credit_balance_identity(during)
    assert_status(read_slot(api, slot_id), SlotStatus.PENDING_REPLACEMENT)

    rescinded = get_success_data(_rescind(ctx, approved["id"]))
    assert_status(rescinded, ProposalStatus.UNDER_REVIEW)
    assert_fields(rescinded, approving_motion_id=None)

    after = ctx.refresh_plan()
    assert_capacity_triple(after, occupied=4, reserved=0, available=1)
    for counter in (
        "occupied_menu_slots",
        "reserved_menu_slots",
        "available_menu_slots",
        "menu_slot_capacity",
        "revenue_credit_accrued_cents",
        "revenue_credit_allocated_cents",
        "revenue_credit_balance_cents",
        "total_plan_assets_cents",
    ):
        assert after[counter] == before[counter], (
            f"{counter} was {before[counter]} before the approval and is "
            f"{after[counter]} after the rescission"
        )
    assert_credit_balance_identity(after)
    assert_ratio(after["at_risk_slot_ratio"], "0.0000")
    assert_fields(after, menu_posture=MenuPosture.OPEN)

    slot_after = read_slot(api, slot_id)
    assert_status(slot_after, SlotStatus.ACTIVE)
    assert_fields(slot_after, current_fund_id=seated_fund_id)
    fund_after = read_fund(api, seated_fund_id)
    assert_fields(
        fund_after, watch_status=WatchStatus.CLEAR, menu_status=FundMenuStatus.ACTIVE
    )


def test_the_position_reserved_by_an_approval_is_released_for_reuse(api):
    """While an approval holds the last menu position no other fund can be
    seated; the rescission hands that same position back.

    Design: Difficulty/compensating_invariant/rescind_approval_restores_capacity_triple_exactly
    """
    ctx = _four_of_five_menu(api)
    empty_slot_id = ctx.slot("tips")["id"]
    waiting_fund_id = ctx.fund("tips")["id"]
    assert_capacity_triple(ctx.refresh_plan(), occupied=4, reserved=0, available=1)

    approved = _approve_large_cap_replacement(ctx)
    reserved_state = ctx.refresh_plan()
    assert_capacity_triple(reserved_state, occupied=4, reserved=1, available=0)
    assert_fields(reserved_state, menu_posture=MenuPosture.RESTRICTED)

    # The empty TIPS slot is neither at risk nor pending replacement, so the
    # restricted posture of PRD 2.9 leaves it writable and the refusal is the
    # capacity refusal of PRD 3.3.
    blocked = _attempt_seating(ctx, empty_slot_id, waiting_fund_id)
    validate_error(blocked, ApiErrorId.MENU_CAPACITY_EXHAUSTED)
    assert_status(read_slot(api, empty_slot_id), SlotStatus.EMPTY)
    assert_capacity_triple(ctx.refresh_plan(), occupied=4, reserved=1, available=0)

    get_success_data(_rescind(ctx, approved["id"]))
    released = ctx.refresh_plan()
    assert_capacity_triple(released, occupied=4, reserved=0, available=1)
    assert_fields(released, menu_posture=MenuPosture.OPEN)

    # Seating mutates an existing slot rather than minting a row, and PRD 4 says
    # "A successful resource creation returns HTTP 201; every other successful
    # call -- reads, lifecycle actions, state changes and data updates -- returns
    # HTTP 200."
    seated = get_success_data(_attempt_seating(ctx, empty_slot_id, waiting_fund_id), 200)
    assert_status(seated, SlotStatus.ACTIVE)
    assert_fields(seated, current_fund_id=waiting_fund_id)
    filled = ctx.refresh_plan()
    assert_capacity_triple(filled, occupied=5, reserved=0, available=0)
    assert_ratio(filled["at_risk_slot_ratio"], "0.0000")
    assert_fields(
        filled,
        menu_posture=MenuPosture.OPEN,
        total_plan_assets_cents=CATALOGUE_ASSETS_CENTS,
    )


def test_rescission_returns_a_watched_slot_to_at_risk_rather_than_active(api):
    """The state a rescinded slot returns to is dictated by its seated fund's
    watch status, so a slot that was at risk before the approval is at risk
    again afterwards.

    Design: Difficulty/compensating_invariant/rescind_approval_restores_capacity_triple_exactly
    """
    ctx = setup_scored_quarter(
        api, scorecard_overrides={"small": BREACH_SCORECARDS["small"]}, finalize=True
    )
    slot_id = ctx.slot("small")["id"]
    watched_fund_id = ctx.fund("small")["id"]
    create_fund(
        ctx,
        "small_b",
        ticker="SMLVB",
        fund_name="Beacon Small Cap Value Institutional",
        asset_class_code=AssetClass.US_SMALL_CAP,
        plan_assets_cents=0,
    )

    before = ctx.refresh_plan()
    assert_capacity_triple(before, occupied=5, reserved=0, available=1)
    assert_ratio(before["at_risk_slot_ratio"], "0.2000")
    assert_fields(before, menu_posture=MenuPosture.OPEN)
    slot_before = read_slot(api, slot_id)
    assert_status(slot_before, SlotStatus.AT_RISK)
    assert_fields(slot_before, at_risk_since_quarter_index=QUARTER_ZERO)
    assert_fields(read_fund(api, watched_fund_id), watch_status=WatchStatus.WATCH)

    proposal = draft_proposal(ctx, "small", "small", "small_b")
    submit_proposal(ctx, proposal["id"])
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.FUND_REPLACEMENT,
        proposal["id"],
        meeting_date="2026-08-17",
        minutes_doc_ref="MIN-2026-Q0-003",
        key="replacement",
    )
    approved = approve_proposal(ctx, proposal["id"], motion["id"])
    assert_status(approved, ProposalStatus.APPROVED)
    during = ctx.refresh_plan()
    assert_capacity_triple(during, occupied=5, reserved=1, available=0)
    assert_status(read_slot(api, slot_id), SlotStatus.PENDING_REPLACEMENT)
    assert_ratio(during["at_risk_slot_ratio"], "0.2000")

    rescinded = get_success_data(_rescind(ctx, approved["id"]))
    assert_status(rescinded, ProposalStatus.UNDER_REVIEW)
    assert_fields(rescinded, approving_motion_id=None)
    slot_after = read_slot(api, slot_id)
    assert_status(slot_after, SlotStatus.AT_RISK)
    assert_fields(
        slot_after,
        current_fund_id=watched_fund_id,
        at_risk_since_quarter_index=QUARTER_ZERO,
    )
    after = ctx.refresh_plan()
    assert_capacity_triple(after, occupied=5, reserved=0, available=1)
    assert_ratio(after["at_risk_slot_ratio"], "0.2000")
    assert_fields(after, menu_posture=MenuPosture.OPEN)


def _two_slot_menu_with_a_draft_proposal(api: ApiClient) -> Ctx:
    """A two-slot menu with both slots seated and one DRAFT replacement waiting
    on the large-cap slot, so a single at-risk slot is half the live menu."""
    ctx = setup_adopted_ips(api)
    for key in ("lc_a", "bond", "lc_b"):
        create_fund(ctx, key)
    create_slot(ctx, "lc", AssetClass.US_LARGE_CAP, 1)
    create_slot(ctx, "bond", AssetClass.CORE_BOND, 2)
    seat_fund(ctx, "lc", "lc_a")
    seat_fund(ctx, "bond", "bond")
    draft_proposal(ctx, "lc", "lc_a", "lc_b")
    ctx.refresh_plan()
    return ctx


def _score_and_finalize_a_large_cap_breach(ctx: Ctx) -> Dict[str, Any]:
    """Score quarter 0 with the large-cap fund exactly on the watch trigger and
    the bond fund clean, then finalize."""
    open_review(ctx, QUARTER_ZERO)
    submit_scorecard(ctx, "lc_a", dict(BREACH_SCORECARDS["small"]))
    submit_scorecard(ctx, "bond", dict(CLEAN_SCORECARDS["bond"]))
    present_and_document(ctx)
    return finalize_review(ctx)


def test_reopening_a_review_rolls_the_watch_dimension_back_from_its_snapshot(api):
    """The watch status, breach counter and composite score written by
    finalization come back to their pre-review values on reopen, while the
    quarter-index guard that stops a later review being clobbered does not.

    Design: Difficulty/compensating_invariant/review_reopen_inverts_finalize_cascade_except_reopen_count
    """
    ctx = _two_slot_menu_with_a_draft_proposal(api)
    breached_fund_id = ctx.fund("lc_a")["id"]
    clean_fund_id = ctx.fund("bond")["id"]

    fund_before = read_fund(api, breached_fund_id)
    assert_fields(
        fund_before,
        watch_status=WatchStatus.CLEAR,
        menu_status=FundMenuStatus.ACTIVE,
        consecutive_breach_quarters=0,
        latest_composite_score=None,
        last_scored_quarter_index=None,
    )

    review = _score_and_finalize_a_large_cap_breach(ctx)
    assert_status(review, ReviewStatus.FINALIZED)
    assert_fields(review, reopen_count=0, finalized_quarter_index=QUARTER_ZERO)
    assert review["finalized_at"] is not None, "finalization stamps finalized_at"

    watched = read_fund(api, breached_fund_id)
    assert_score(watched["latest_composite_score"], "40.00")
    assert_fields(
        watched,
        watch_status=WatchStatus.WATCH,
        watch_status_before_last_review=WatchStatus.CLEAR,
        menu_status=FundMenuStatus.ACTIVE,
        consecutive_breach_quarters=1,
        last_scored_quarter_index=QUARTER_ZERO,
    )
    scored_clean = read_fund(api, clean_fund_id)
    assert_score(scored_clean["latest_composite_score"], "75.52")
    assert_fields(scored_clean, watch_status=WatchStatus.CLEAR)

    reopened = get_success_data(_reopen(ctx, review["id"]))
    assert_status(reopened, ReviewStatus.REOPENED)
    assert_fields(reopened, finalized_at=None)

    restored = read_fund(api, breached_fund_id)
    assert_snapshot_restored(
        restored, "watch_status", "watch_status_before_last_review", WatchStatus.CLEAR
    )
    assert_fields(
        restored,
        menu_status=FundMenuStatus.ACTIVE,
        consecutive_breach_quarters=0,
        latest_composite_score=None,
    )
    assert_fields(read_fund(api, clean_fund_id), latest_composite_score=None)

    # Two counters deliberately survive the rollback: the review's reopen budget
    # and the fund's scored-quarter guard of PRD 2.10.
    assert_fields(reopened, reopen_count=1, finalized_quarter_index=QUARTER_ZERO)
    assert_fields(restored, last_scored_quarter_index=QUARTER_ZERO)


def test_reopening_a_review_restores_the_slot_state_and_the_menu_posture(api):
    """The slot returns to the status its snapshot recorded, which drops the
    at-risk ratio back to zero and relaxes the posture from FROZEN to OPEN.

    Design: Difficulty/compensating_invariant/review_reopen_inverts_finalize_cascade_except_reopen_count
    """
    ctx = _two_slot_menu_with_a_draft_proposal(api)
    breached_slot_id = ctx.slot("lc")["id"]
    seated_fund_id = ctx.fund("lc_a")["id"]
    clean_slot_id = ctx.slot("bond")["id"]

    slot_before = read_slot(api, breached_slot_id)
    assert_status(slot_before, SlotStatus.ACTIVE)
    assert_fields(slot_before, status_before_last_review=None)
    plan_before = ctx.refresh_plan()
    assert_ratio(plan_before["at_risk_slot_ratio"], "0.0000")
    assert_fields(plan_before, menu_posture=MenuPosture.OPEN)
    assert_capacity_triple(plan_before, occupied=2, reserved=0)

    review = _score_and_finalize_a_large_cap_breach(ctx)
    at_risk = read_slot(api, breached_slot_id)
    assert_status(at_risk, SlotStatus.AT_RISK)
    assert_fields(
        at_risk,
        status_before_last_review=SlotStatus.ACTIVE,
        at_risk_since_quarter_index=QUARTER_ZERO,
        current_fund_id=seated_fund_id,
    )
    assert_status(read_slot(api, clean_slot_id), SlotStatus.ACTIVE)
    frozen = ctx.refresh_plan()
    assert_ratio(frozen["at_risk_slot_ratio"], "0.5000")
    assert_fields(frozen, menu_posture=MenuPosture.FROZEN)
    assert_capacity_triple(frozen, occupied=2, reserved=0)

    reopened = get_success_data(_reopen(ctx, review["id"]))
    assert_status(reopened, ReviewStatus.REOPENED)
    assert_fields(reopened, reopen_count=1)

    slot_after = read_slot(api, breached_slot_id)
    assert_snapshot_restored(
        slot_after, "status", "status_before_last_review", SlotStatus.ACTIVE
    )
    assert_fields(slot_after, current_fund_id=seated_fund_id)
    assert_status(read_slot(api, clean_slot_id), SlotStatus.ACTIVE)
    plan_after = ctx.refresh_plan()
    assert_ratio(plan_after["at_risk_slot_ratio"], "0.0000")
    assert_fields(plan_after, menu_posture=MenuPosture.OPEN)
    assert_capacity_triple(plan_after, occupied=2, reserved=0)
    assert (
        plan_after["available_menu_slots"] == plan_before["available_menu_slots"]
    ), "the reopen moves no capacity counter"


def test_reopening_a_review_returns_a_blocked_proposal_to_its_pre_block_status(api):
    """A DRAFT proposal frozen out by finalization comes back to DRAFT exactly,
    with the snapshot cleared and the revision counter untouched.

    Design: Difficulty/compensating_invariant/review_reopen_inverts_finalize_cascade_except_reopen_count
    """
    ctx = _two_slot_menu_with_a_draft_proposal(api)
    proposal_id = ctx.proposals["proposal"]["id"]

    proposal_before = read_proposal(api, proposal_id)
    assert_status(proposal_before, ProposalStatus.DRAFT)
    assert_fields(proposal_before, pre_block_status=None, revision_round=0)

    review = _score_and_finalize_a_large_cap_breach(ctx)
    assert_fields(ctx.refresh_plan(), menu_posture=MenuPosture.FROZEN)
    blocked = read_proposal(api, proposal_id)
    assert_status(blocked, ProposalStatus.BLOCKED)
    assert_fields(blocked, pre_block_status=ProposalStatus.DRAFT, revision_round=0)

    reopened = get_success_data(_reopen(ctx, review["id"]))
    assert_status(reopened, ReviewStatus.REOPENED)
    assert_fields(reopened, reopen_count=1, finalized_at=None)
    assert_fields(ctx.refresh_plan(), menu_posture=MenuPosture.OPEN)

    released = read_proposal(api, proposal_id)
    assert_snapshot_restored(
        released, "status", "pre_block_status", ProposalStatus.DRAFT
    )
    assert_fields(released, pre_block_status=None, revision_round=0)
