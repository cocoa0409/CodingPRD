"""Menu-slot and meeting state guards (PRD 3.3, 3.4 and 2.12).

A slot retirement touches only the menu dimension of its occupant, leaving the
watch dimension alone and shrinking the at-risk ratio's denominator.  Adjourning
a meeting closes its open motions for good.  And every machine in the system
starts in its declared initial state and refuses undeclared transitions before
any business precondition is even consulted.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_fields,
    assert_ratio,
    assert_status,
    get_success_data,
    validate_error,
)
from test_helpers.factories import (
    Paths,
    levelization_payload,
    meeting_payload,
    motion_payload,
    notice_issue_payload,
    review_payload,
    slot_payload,
)
from test_helpers.fixtures import (
    Ctx,
    adjourn,
    carry_motion_unanimously,
    create_fund,
    draft_proposal,
    finalize_review,
    open_meeting,
    read_fund,
    read_meeting,
    read_motion,
    read_plan,
    read_proposal,
    read_slot,
    setup_breach_quarter,
)
from test_helpers.test_users import (
    consultant_headers,
    member_headers,
    recordkeeper_headers,
    sponsor_headers,
)
from test_helpers.types import (
    AssetClass,
    CreditAccrualStatus,
    FundMenuStatus,
    LevelizationMethod,
    LevelizationStatus,
    MeetingStatus,
    MenuPosture,
    MotionStatus,
    MotionSubjectType,
    ProposalStatus,
    ReviewStatus,
    ScoringVariant,
    SlotDesignation,
    SlotStatus,
    TallyBasis,
    WatchStatus,
)


#: A spare small-cap candidate so the small-cap slot can carry a live proposal.
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


@pytest.fixture
def restricted_menu(api: ApiClient) -> Ctx:
    """A finalized breach quarter: the small-cap and international slots are
    AT_RISK, the ratio is 0.4000, the posture is RESTRICTED, and a replacement
    proposal on the small-cap slot has been swept into BLOCKED."""
    ctx = setup_breach_quarter(api)
    create_fund(ctx, "small_b", **SMALL_CAP_SUCCESSOR)
    draft_proposal(ctx, "small", "small", "small_b", key="small")
    finalize_review(ctx)
    ctx.refresh_plan()
    return ctx


# --------------------------------------------------------------------------
# Retiring a slot
# --------------------------------------------------------------------------


def test_retiring_a_slot_moves_only_the_menu_dimension(api, restricted_menu):
    """Retirement marks the occupant for removal on the menu dimension only — its
    watch status and credit accrual are untouched — and drops the slot out of the
    at-risk ratio's denominator, which here still leaves the posture RESTRICTED.

    Design: Corner/state_machines/retiring_a_slot_moves_only_the_menu_dimension_and_shrinks_the_ratio_denominator
    """
    ctx = restricted_menu
    slot_id = ctx.slot("intl")["id"]

    retired = get_success_data(
        api.post(
            Paths.slot_retire(slot_id),
            {"reason": "The committee is consolidating the international sleeve."},
            sponsor_headers(),
        )
    )
    assert_status(retired, SlotStatus.RETIRED)
    assert_fields(retired, current_fund_id=ctx.fund("intl")["id"])

    occupant = read_fund(api, ctx.fund("intl")["id"])
    assert_fields(
        occupant,
        menu_status=FundMenuStatus.PENDING_REMOVAL,
        watch_status=WatchStatus.REMEDIATION,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
        qdia_flag=False,
    )

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=4, reserved=0, available=2)
    # One of four remaining counted slots is at risk: exactly 0.2500, which is
    # still RESTRICTED because the lower boundary is inclusive.
    assert_ratio(plan["at_risk_slot_ratio"], "0.2500")
    assert_status(plan, MenuPosture.RESTRICTED, field="menu_posture")

    # The posture never relaxed, so the blocked proposal stays blocked.
    assert_status(
        read_proposal(api, ctx.proposals["small"]["id"]), ProposalStatus.BLOCKED
    )


def test_retiring_a_slot_with_a_blocked_proposal_on_it_is_rejected(
    api, restricted_menu
):
    """A slot carrying a proposal in the open pipeline cannot be retired, and a
    BLOCKED proposal counts as open.

    Design: Corner/state_machines/retiring_a_slot_with_a_blocked_proposal_on_it_is_rejected
    """
    ctx = restricted_menu
    slot_id = ctx.slot("small")["id"]

    response = api.post(
        Paths.slot_retire(slot_id),
        {"reason": "Trying to drop the small cap sleeve while a replacement is live."},
        sponsor_headers(),
    )
    validate_error(response, ApiErrorId.SLOT_HAS_OPEN_PROPOSAL)

    slot = read_slot(api, slot_id)
    assert_fields(
        slot,
        status=SlotStatus.AT_RISK,
        current_fund_id=ctx.fund("small")["id"],
    )
    occupant = read_fund(api, ctx.fund("small")["id"])
    assert_fields(
        occupant,
        menu_status=FundMenuStatus.ACTIVE,
        watch_status=WatchStatus.WATCH,
    )
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, available=1)


# --------------------------------------------------------------------------
# Adjourning a meeting
# --------------------------------------------------------------------------


def test_adjourning_a_meeting_withdraws_its_open_motions(api, adopted_ips):
    """Adjournment withdraws every motion still open, stamping closed_at and
    leaving the tally fields as they were, and a withdrawn motion can no longer be
    closed because its meeting is no longer in session.

    Design: Corner/state_machines/adjourning_a_meeting_withdraws_its_open_motions_and_closes_them_to_voting
    """
    ctx = adopted_ips
    create_fund(ctx, "lc_a")
    create_fund(ctx, "bond")
    meeting = open_meeting(ctx, "2026-08-24", 0, key="watch")

    # One motion is carried unanimously, the other is left open.
    carried = carry_motion_unanimously(
        ctx,
        meeting["id"],
        MotionSubjectType.WATCH_LIST_ACTION,
        ctx.fund("lc_a")["id"],
        key="watch_lc",
    )
    finance_id = ctx.members["finance"]["id"]
    left_open = get_success_data(
        api.post(
            Paths.MOTIONS,
            motion_payload(
                meeting["id"],
                MotionSubjectType.WATCH_LIST_ACTION,
                ctx.fund("bond")["id"],
                TallyBasis.ELIGIBLE_VOTERS,
            ),
            member_headers(finance_id),
        ),
        201,
    )
    assert_status(left_open, MotionStatus.OPEN)

    adjourned = adjourn(ctx, meeting["id"])
    assert_fields(
        adjourned,
        status=MeetingStatus.ADJOURNED,
        quorum_met=True,
        carried_motion_count=1,
    )

    withdrawn = read_motion(api, left_open["id"])
    assert_fields(
        withdrawn,
        status=MotionStatus.WITHDRAWN,
        support_pct=None,
        for_count=0,
        against_count=0,
        abstain_count=0,
        recuse_count=0,
    )
    assert withdrawn["closed_at"] is not None

    # The carried motion is a historical record and adjournment does not touch it.
    still_carried = read_motion(api, carried["id"])
    assert_fields(
        still_carried,
        status=MotionStatus.CARRIED,
        for_count=3,
        against_count=0,
        abstain_count=0,
        recuse_count=0,
        eligible_voter_count=3,
    )
    assert_ratio(still_carried["support_pct"], "100.0000", "support_pct")

    # Closing is only available while the meeting is in session.
    response = api.post(Paths.motion_close(left_open["id"]), {}, ctx.chair)
    validate_error(response, ApiErrorId.MEETING_NOT_IN_SESSION)
    assert_status(read_meeting(api, meeting["id"]), MeetingStatus.ADJOURNED)


# --------------------------------------------------------------------------
# Declared initial states and undeclared transitions
# --------------------------------------------------------------------------


def test_every_machine_starts_in_its_declared_initial_state(api, full_menu):
    """A freshly created meeting, quarterly review, asset-class slot and fee
    levelization run each land in the initial state the documentation declares,
    with every derived counter at its documented zero.

    Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
    """
    ctx = full_menu

    meeting = get_success_data(
        api.post(
            Paths.MEETINGS,
            meeting_payload(ctx.plan_id, "2026-08-31", 0),
            sponsor_headers(),
        ),
        201,
    )
    assert_fields(
        meeting,
        status=MeetingStatus.SCHEDULED,
        quorum_met=False,
        voting_attendee_count=0,
        eligible_voting_seat_count=0,
        carried_motion_count=0,
        charter_version_pinned=None,
        minutes_doc_ref=None,
        minutes_approved_at=None,
    )

    review = get_success_data(
        api.post(Paths.REVIEWS, review_payload(ctx.plan_id, 0), consultant_headers()),
        201,
    )
    assert_fields(
        review,
        status=ReviewStatus.DRAFT,
        ips_id=ctx.ips_id,
        scoring_variant=ScoringVariant.TRAILING_PERIOD,
        scorecard_count=0,
        submitted_scorecard_count=0,
        watch_additions_count=0,
        reopen_count=0,
        finalized_at=None,
        finalized_quarter_index=None,
    )

    slot = get_success_data(
        api.post(
            Paths.SLOTS,
            slot_payload(
                ctx.plan_id,
                ctx.ips_id,
                asset_class_code=AssetClass.EMERGING_MKTS,
                designation=SlotDesignation.SPECIALTY,
                slot_index=6,
            ),
            consultant_headers(),
        ),
        201,
    )
    assert_fields(
        slot,
        status=SlotStatus.EMPTY,
        current_fund_id=None,
        ips_id=ctx.ips_id,
        at_risk_since_quarter_index=None,
        status_before_last_review=None,
    )

    run = get_success_data(
        api.post(
            Paths.LEVELIZATION_RUNS,
            levelization_payload(ctx.plan_id, 0, LevelizationMethod.PER_CAPITA),
            consultant_headers(),
        ),
        201,
    )
    assert_fields(
        run,
        status=LevelizationStatus.DRAFT,
        allocated_total_cents=0,
        remainder_cents=0,
        per_account_cents=None,
        approving_motion_id=None,
        posted_at=None,
        reversed_at=None,
    )
    assert run["allocation_lines"] == [], (
        f"a new run should carry no allocation lines, got {run['allocation_lines']!r}"
    )

    # An EMPTY slot reserves nothing, so the capacity partition is unmoved.
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=0, available=1)


def test_approving_a_draft_proposal_is_a_state_error_not_a_motion_error(api, full_menu):
    """A DRAFT proposal has no approve transition at all, so the state check fires
    ahead of the authorising-motion check even when the motion named is genuinely
    carried but belongs to another subject.

    Design: Corner/state_machines/undeclared_transitions_are_refused_before_any_business_check_runs
    """
    ctx = full_menu
    proposal = draft_proposal(ctx, "lc", "lc_a", "lc_b")

    response = api.post(
        Paths.proposal_approve(proposal["id"]),
        {"approving_motion_id": ctx.motions["ips"]["id"]},
        ctx.chair,
    )
    validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION)

    unchanged = read_proposal(api, proposal["id"])
    assert_fields(
        unchanged,
        status=ProposalStatus.DRAFT,
        approving_motion_id=None,
    )
    assert_status(read_slot(api, ctx.slot("lc")["id"]), SlotStatus.ACTIVE)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=0, available=1)


def test_a_draft_proposal_refuses_every_later_stage_action(api, full_menu):
    """Executing, noticing or revising a proposal that has never left DRAFT are all
    undeclared transitions and are refused with the same state error.

    Design: Corner/state_machines/undeclared_transitions_are_refused_before_any_business_check_runs
    """
    ctx = full_menu
    proposal = draft_proposal(ctx, "lc", "lc_a", "lc_b")

    attempts = (
        (Paths.proposal_execute(proposal["id"]), {}, recordkeeper_headers()),
        (
            Paths.proposal_notice_issue(proposal["id"]),
            notice_issue_payload(),
            recordkeeper_headers(),
        ),
        (
            Paths.proposal_revise(proposal["id"]),
            {
                "rationale": "Restating the case before the committee has even seen "
                "this proposal once."
            },
            consultant_headers(),
        ),
    )
    for path, payload, headers in attempts:
        response = api.post(path, payload, headers)
        validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION)

    unchanged = read_proposal(api, proposal["id"])
    assert_fields(
        unchanged,
        status=ProposalStatus.DRAFT,
        revision_round=0,
        notice_delivered_at=None,
        blackout_start_at=None,
        blackout_end_at=None,
        mapped_assets_cents=0,
    )
    assert_status(read_slot(api, ctx.slot("lc")["id"]), SlotStatus.ACTIVE)
