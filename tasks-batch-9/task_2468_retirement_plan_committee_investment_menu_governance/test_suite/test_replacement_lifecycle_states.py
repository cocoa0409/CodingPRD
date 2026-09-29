"""Fund-replacement lifecycle behaviour (PRD 3.7).

The replacement machine is the longest one in the system and every hop is
guarded: the revision loop runs at most three laps, the participant notice can
only name a blackout that starts after the lead period, execution only happens
inside that window, rescission only before the notice, and the unwind only
before the window closes.  Once a mapping is unwound the proposal is terminal.
"""

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_capacity_triple,
    assert_cents,
    assert_fields,
    assert_plan_assets_conserved,
    assert_ratio,
    assert_status,
    assert_version_unchanged,
    get_success_data,
    ids_of,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    Paths,
    notice_issue_payload,
)
from test_helpers.fixtures import (
    read_fund,
    read_motion,
    read_plan,
    read_proposal,
    read_slot,
    set_clock,
)
from test_helpers.test_users import (
    auditor_headers,
    consultant_headers,
    recordkeeper_headers,
    sponsor_headers,
)
from test_helpers.types import (
    CreditAccrualStatus,
    FeeDisclosureStatus,
    FundMenuStatus,
    MappingStrategy,
    MenuPosture,
    MotionStatus,
    ProposalStatus,
    SlotStatus,
)


def revision_note(lap: int) -> dict:
    """The chair's instruction back to the consultant (PRD 2.5 narrative)."""
    return {
        "revision_note": (
            f"Lap {lap}: restate the mapping cost estimate and confirm the "
            "share-class breakpoint before this comes back to the committee."
        )
    }


def revised_rationale(lap: int) -> dict:
    return {
        "rationale": (
            f"Revision {lap}: the cheaper share class still clears every policy "
            "criterion and the mapping cost estimate is now documented."
        )
    }


# --------------------------------------------------------------------------
# Guards on the early hops
# --------------------------------------------------------------------------


def test_submitting_a_proposal_twice_is_refused(api, submitted_replacement):
    """A proposal already in UNDER_REVIEW has no declared submit transition, so a
    second submission is refused and nothing about the row moves.

    Design: Corner/state_machines/submitting_a_proposal_twice_fails_and_the_draft_count_stays_definitional
    """
    ctx = submitted_replacement
    proposal_id = ctx.proposals["proposal"]["id"]

    response = api.post(Paths.proposal_submit(proposal_id), {}, consultant_headers())
    validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION)

    proposal = read_proposal(api, proposal_id)
    assert_fields(
        proposal,
        status=ProposalStatus.UNDER_REVIEW,
        pinned_ips_id=ctx.ips_id,
        revision_round=0,
    )

    # The rejected call created no second row: exactly one proposal is under
    # review on this plan.
    rows, meta = validate_paginated(
        api.get(
            Paths.REPLACEMENTS,
            auditor_headers(),
            {"plan_id": ctx.plan_id, "status": ProposalStatus.UNDER_REVIEW},
        )
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one UNDER_REVIEW proposal, got {meta['total_count']}"
    )
    assert ids_of(rows) == [proposal_id]


def test_the_revision_cycle_runs_three_laps_and_then_locks(api, submitted_replacement):
    """The chair may send a proposal back three times; the fourth request is
    refused with the proposal parked in UNDER_REVIEW at round 3.

    Design: Corner/state_machines/the_revision_cycle_runs_three_laps_and_then_locks
    """
    ctx = submitted_replacement
    proposal_id = ctx.proposals["proposal"]["id"]

    for lap in (1, 2, 3):
        sent_back = get_success_data(
            api.post(
                Paths.proposal_request_revision(proposal_id),
                revision_note(lap),
                ctx.chair,
            )
        )
        assert_fields(
            sent_back,
            status=ProposalStatus.REVISION_REQUESTED,
            revision_round=lap,
        )
        revised = get_success_data(
            api.post(
                Paths.proposal_revise(proposal_id),
                revised_rationale(lap),
                consultant_headers(),
            )
        )
        assert_fields(
            revised,
            status=ProposalStatus.UNDER_REVIEW,
            revision_round=lap,
        )

    # The fourth lap is refused, not silently capped.
    response = api.post(
        Paths.proposal_request_revision(proposal_id), revision_note(4), ctx.chair
    )
    validate_error(response, ApiErrorId.REVISION_LIMIT_REACHED)

    proposal = read_proposal(api, proposal_id)
    assert_fields(
        proposal,
        status=ProposalStatus.UNDER_REVIEW,
        revision_round=3,
        pinned_ips_id=ctx.ips_id,
        mapping_strategy=MappingStrategy.DIRECT_MAP,
    )
    assert_status(read_slot(api, ctx.slot("lc")["id"]), SlotStatus.ACTIVE)


# --------------------------------------------------------------------------
# The participant-notice lead period
# --------------------------------------------------------------------------


def test_notice_issue_one_second_before_the_lead_time_expires_is_rejected(
    api, approved_replacement
):
    """A blackout starting at 2026-08-30T23:59:59Z is one second short of the
    30-day lead period, so the notice is refused and no notice field is written.

    Design: Corner/state_machines/notice_issue_one_second_before_the_lead_time_expires_is_rejected
    """
    ctx = approved_replacement
    proposal_id = ctx.proposals["proposal"]["id"]

    response = api.post(
        Paths.proposal_notice_issue(proposal_id),
        notice_issue_payload(blackout_start_at="2026-08-30T23:59:59Z"),
        recordkeeper_headers(),
    )
    validate_error(response, ApiErrorId.NOTICE_PERIOD_NOT_ELAPSED)

    proposal = read_proposal(api, proposal_id)
    assert_fields(
        proposal,
        status=ProposalStatus.APPROVED,
        notice_delivered_at=None,
        blackout_start_at=None,
        blackout_end_at=None,
        notice_lead_days_required=30,
    )

    slot = read_slot(api, ctx.slot("lc")["id"])
    assert_fields(
        slot,
        status=SlotStatus.PENDING_REPLACEMENT,
        current_fund_id=ctx.fund("lc_a")["id"],
    )
    assert_capacity_triple(read_plan(api, ctx.plan_id), reserved=1, available=0)


def test_notice_issue_exactly_at_the_lead_boundary_is_accepted(
    api, approved_replacement
):
    """The lead-period comparison is inclusive: a blackout starting exactly 30
    days after delivery at 2026-08-31T00:00:00Z is accepted.

    Design: Corner/state_machines/notice_issue_one_second_before_the_lead_time_expires_is_rejected
    """
    ctx = approved_replacement
    proposal_id = ctx.proposals["proposal"]["id"]

    noticed = get_success_data(
        api.post(
            Paths.proposal_notice_issue(proposal_id),
            notice_issue_payload(blackout_start_at="2026-08-31T00:00:00Z"),
            recordkeeper_headers(),
        )
    )
    assert_status(noticed, ProposalStatus.NOTICE_ISSUED)
    assert noticed["notice_delivered_at"] is not None
    assert_fields(noticed, notice_lead_days_required=30)

    # Reserving the incoming position is unchanged by the notice.
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=5, reserved=1, available=0)


# --------------------------------------------------------------------------
# Rescission
# --------------------------------------------------------------------------


def test_rescind_approval_restores_the_slot_and_the_capacity_triple_exactly(
    api, approved_replacement
):
    """Rescinding before any notice returns the proposal to UNDER_REVIEW, puts the
    slot back to ACTIVE over its unchanged occupant, spends the carried motion and
    restores the capacity triple to its pre-approval values.

    Design: Corner/state_machines/rescind_approval_restores_the_slot_and_the_capacity_triple_exactly
    """
    ctx = approved_replacement
    proposal_id = ctx.proposals["proposal"]["id"]
    motion_id = ctx.motions["replacement"]["id"]

    rescinded = get_success_data(
        api.post(
            Paths.proposal_rescind(proposal_id),
            {
                "reason": "The committee wants the mapping cost estimate refreshed "
                "before the notice goes out."
            },
            ctx.chair,
        )
    )
    assert_fields(
        rescinded,
        status=ProposalStatus.UNDER_REVIEW,
        approving_motion_id=None,
        revision_round=0,
    )

    # The incumbent is CLEAR, so the slot's deterministic return state is ACTIVE.
    slot = read_slot(api, ctx.slot("lc")["id"])
    assert_fields(
        slot,
        status=SlotStatus.ACTIVE,
        current_fund_id=ctx.fund("lc_a")["id"],
        at_risk_since_quarter_index=None,
    )

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000")
    assert_status(plan, MenuPosture.OPEN, field="menu_posture")

    # The motion itself is a historical record and is never rewritten.
    assert_status(read_motion(api, motion_id), MotionStatus.CARRIED)


def test_rescinding_after_the_participant_notice_is_rejected(api, noticed_replacement):
    """Once participants have been told, the approval can no longer be rescinded
    and the reserved position stays held.

    Design: Corner/state_machines/rescinding_after_the_participant_notice_is_rejected
    """
    ctx = noticed_replacement
    proposal_id = ctx.proposals["proposal"]["id"]

    response = api.post(
        Paths.proposal_rescind(proposal_id),
        {"reason": "Late change of heart after the participant notice went out."},
        ctx.chair,
    )
    validate_error(response, ApiErrorId.NOTICE_ALREADY_ISSUED)

    proposal = read_proposal(api, proposal_id)
    assert_fields(
        proposal,
        status=ProposalStatus.NOTICE_ISSUED,
        approving_motion_id=ctx.motions["replacement"]["id"],
    )
    assert proposal["notice_delivered_at"] is not None

    slot = read_slot(api, ctx.slot("lc")["id"])
    assert_fields(
        slot,
        status=SlotStatus.PENDING_REPLACEMENT,
        current_fund_id=ctx.fund("lc_a")["id"],
    )
    assert_capacity_triple(read_plan(api, ctx.plan_id), reserved=1, available=0)


# --------------------------------------------------------------------------
# The blackout window is half-open
# --------------------------------------------------------------------------


def test_execute_before_the_window_opens_is_a_blackout_conflict(
    api, noticed_replacement
):
    """At 2026-08-31 the 30-day lead period has just elapsed but the blackout has
    not opened, so the mapping is refused as a window conflict and no cascade hop
    runs.

    Design: Corner/state_machines/execute_between_the_lead_expiry_and_the_window_opening_is_a_blackout_conflict
    """
    ctx = noticed_replacement
    proposal_id = ctx.proposals["proposal"]["id"]
    set_clock(api, "2026-08-31T00:00:00Z")

    response = api.post(
        Paths.proposal_execute(proposal_id), {}, recordkeeper_headers()
    )
    validate_error(response, ApiErrorId.BLACKOUT_WINDOW_CONFLICT)

    proposal = read_proposal(api, proposal_id)
    assert_status(proposal, ProposalStatus.NOTICE_ISSUED)
    assert_cents(proposal["mapped_assets_cents"], 0, "mapped_assets_cents")

    outgoing = read_fund(api, ctx.fund("lc_a")["id"])
    assert_cents(outgoing["plan_assets_cents"], 800000000, "outgoing assets")
    assert_status(outgoing, FundMenuStatus.ACTIVE, field="menu_status")
    incoming = read_fund(api, ctx.fund("lc_b")["id"])
    assert_cents(incoming["plan_assets_cents"], 0, "incoming assets")
    assert_status(incoming, FundMenuStatus.CANDIDATE, field="menu_status")

    plan = read_plan(api, ctx.plan_id)
    assert_status(plan, FeeDisclosureStatus.COMPLIANT, field="fee_disclosure_status")


def test_execute_at_the_exclusive_window_end_is_a_blackout_conflict(
    api, noticed_replacement
):
    """The blackout runs from its start inclusive to its end exclusive, so at
    2026-09-15 exactly the mapping is refused for the same reason.

    Design: Corner/state_machines/execute_between_the_lead_expiry_and_the_window_opening_is_a_blackout_conflict
    """
    ctx = noticed_replacement
    proposal_id = ctx.proposals["proposal"]["id"]
    set_clock(api, "2026-09-15T00:00:00Z")

    response = api.post(
        Paths.proposal_execute(proposal_id), {}, recordkeeper_headers()
    )
    validate_error(response, ApiErrorId.BLACKOUT_WINDOW_CONFLICT)

    proposal = read_proposal(api, proposal_id)
    assert_status(proposal, ProposalStatus.NOTICE_ISSUED)
    assert_cents(proposal["mapped_assets_cents"], 0, "mapped_assets_cents")
    assert_cents(
        read_fund(api, ctx.fund("lc_a")["id"])["plan_assets_cents"],
        800000000,
        "outgoing assets",
    )


# --------------------------------------------------------------------------
# The full walk and the compensating unwind
# --------------------------------------------------------------------------


def test_fund_replacement_walks_draft_through_to_executed(api, executed_replacement):
    """The whole chain — draft, submit, motion, approve, notice, execute — lands the
    proposal in EXECUTED with the assets moved to the cent and the slot reseated.

    Design: Corner/state_machines/fund_replacement_walks_draft_under_review_approved_notice_issued_executed
    """
    ctx = executed_replacement
    proposal = read_proposal(api, ctx.proposals["proposal"]["id"])
    assert_fields(
        proposal,
        status=ProposalStatus.EXECUTED,
        revision_round=0,
        pre_block_status=None,
        superseded_by_proposal_id=None,
        notice_lead_days_required=30,
        pinned_ips_id=ctx.ips_id,
        approving_motion_id=ctx.motions["replacement"]["id"],
        mapping_strategy=MappingStrategy.DIRECT_MAP,
    )
    assert proposal["notice_delivered_at"] is not None
    assert_cents(proposal["mapped_assets_cents"], 800000000, "mapped_assets_cents")

    incoming = read_fund(api, ctx.fund("lc_b")["id"])
    assert_cents(incoming["plan_assets_cents"], 800000000, "incoming assets")
    assert_status(incoming, FundMenuStatus.ACTIVE, field="menu_status")

    outgoing = read_fund(api, ctx.fund("lc_a")["id"])
    assert_cents(outgoing["plan_assets_cents"], 0, "outgoing assets")
    assert_status(outgoing, FundMenuStatus.REMOVED, field="menu_status")

    slot = read_slot(api, ctx.slot("lc")["id"])
    assert_fields(
        slot,
        status=SlotStatus.ACTIVE,
        current_fund_id=ctx.fund("lc_b")["id"],
    )

    plan = read_plan(api, ctx.plan_id)
    assert_plan_assets_conserved(plan, 1200000000)
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000")
    # Hop 3 of the execution cascade stales the fee disclosure.
    assert_status(
        plan, FeeDisclosureStatus.RESTATEMENT_REQUIRED, field="fee_disclosure_status"
    )


def test_unwind_inside_the_window_reverses_every_execute_side_effect(
    api, executed_replacement
):
    """Unwinding restores the outgoing fund, its accrual status, the incoming
    fund, the slot, the plan-wide asset total and the fee disclosure exactly,
    while keeping the captured mapped amount as the audit record.

    Design: Corner/state_machines/unwind_inside_the_window_reverses_every_execute_side_effect_to_the_cent
    """
    ctx = executed_replacement
    unwound = get_success_data(
        api.post(
            Paths.proposal_unwind(ctx.proposals["proposal"]["id"]),
            {
                "reason": "The recordkeeper mapped the wrong share class, so the "
                "committee is reversing the transfer inside the window."
            },
            sponsor_headers(),
        )
    )
    assert_status(unwound, ProposalStatus.UNWOUND)
    assert_cents(unwound["mapped_assets_cents"], 800000000, "mapped_assets_cents")

    outgoing = read_fund(api, ctx.fund("lc_a")["id"])
    assert_cents(outgoing["plan_assets_cents"], 800000000, "outgoing assets restored")
    assert_fields(
        outgoing,
        menu_status=FundMenuStatus.ACTIVE,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
    )
    incoming = read_fund(api, ctx.fund("lc_b")["id"])
    assert_cents(incoming["plan_assets_cents"], 0, "incoming assets returned")
    assert_status(incoming, FundMenuStatus.CANDIDATE, field="menu_status")

    slot = read_slot(api, ctx.slot("lc")["id"])
    assert_fields(
        slot,
        status=SlotStatus.ACTIVE,
        current_fund_id=ctx.fund("lc_a")["id"],
    )

    plan = read_plan(api, ctx.plan_id)
    assert_plan_assets_conserved(plan, 1200000000)
    assert_status(plan, FeeDisclosureStatus.COMPLIANT, field="fee_disclosure_status")
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)


def test_unwind_at_the_exclusive_window_end_is_rejected(api, executed_replacement):
    """The unwind power expires with the blackout window: at 2026-09-15 exactly it
    is refused and every execution side effect stands.

    Design: Corner/state_machines/unwind_at_the_exclusive_window_end_is_rejected
    """
    ctx = executed_replacement
    set_clock(api, "2026-09-15T00:00:00Z")

    response = api.post(
        Paths.proposal_unwind(ctx.proposals["proposal"]["id"]),
        {"reason": "Attempting to reverse the mapping after the window has closed."},
        sponsor_headers(),
    )
    validate_error(response, ApiErrorId.UNWIND_WINDOW_CLOSED)

    proposal = read_proposal(api, ctx.proposals["proposal"]["id"])
    assert_status(proposal, ProposalStatus.EXECUTED)

    outgoing = read_fund(api, ctx.fund("lc_a")["id"])
    assert_cents(outgoing["plan_assets_cents"], 0, "outgoing assets")
    assert_status(outgoing, FundMenuStatus.REMOVED, field="menu_status")
    assert_cents(
        read_fund(api, ctx.fund("lc_b")["id"])["plan_assets_cents"],
        800000000,
        "incoming assets",
    )

    plan = read_plan(api, ctx.plan_id)
    assert_status(
        plan, FeeDisclosureStatus.RESTATEMENT_REQUIRED, field="fee_disclosure_status"
    )


def test_an_unwound_proposal_accepts_no_further_transition(api, executed_replacement):
    """UNWOUND is terminal: re-executing, resubmitting, re-approving with the same
    carried motion and re-noticing are all refused as undeclared transitions.

    Design: Corner/state_machines/an_unwound_proposal_accepts_no_further_transition
    """
    ctx = executed_replacement
    proposal_id = ctx.proposals["proposal"]["id"]
    get_success_data(
        api.post(
            Paths.proposal_unwind(proposal_id),
            {"reason": "Reversing the mapping while the blackout window is open."},
            sponsor_headers(),
        )
    )
    plan_before = read_plan(api, ctx.plan_id)

    attempts = (
        (Paths.proposal_execute(proposal_id), {}, recordkeeper_headers()),
        (Paths.proposal_submit(proposal_id), {}, consultant_headers()),
        (
            Paths.proposal_approve(proposal_id),
            {"approving_motion_id": ctx.motions["replacement"]["id"]},
            ctx.chair,
        ),
        (
            Paths.proposal_notice_issue(proposal_id),
            notice_issue_payload(),
            recordkeeper_headers(),
        ),
    )
    for path, payload, headers in attempts:
        response = api.post(path, payload, headers)
        validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION)

    proposal = read_proposal(api, proposal_id)
    assert_status(proposal, ProposalStatus.UNWOUND)
    assert_cents(proposal["mapped_assets_cents"], 800000000, "mapped_assets_cents")

    slot = read_slot(api, ctx.slot("lc")["id"])
    assert_fields(slot, current_fund_id=ctx.fund("lc_a")["id"], status=SlotStatus.ACTIVE)

    plan_after = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan_after, occupied=5, reserved=0, available=1)
    assert_version_unchanged(plan_before, plan_after)
