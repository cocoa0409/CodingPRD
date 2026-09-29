"""Move cancellation as one global compensating unwind of every open leg.

A single concierge move fans out into service orders, a bureau handoff, a
postal filing and partner referrals, each advancing at its own pace.  One
cancellation call has to close all of them in one pass, and it has to reach
each family with that family's own compensated state rather than stamping one
terminal label everywhere.  The move built here holds a scheduled water order,
a draft electric order with a live bureau handoff, a submitted postal filing
and an accepted referral, plus one referral that had already reached its own
terminal state and must therefore be left exactly as it was.
"""

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_cents,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
    assert_readiness_breakdown,
    assert_window_released,
)
from test_helpers.test_users import make_partner_agent_headers
from test_helpers.types import (
    BlockedReason,
    BureauName,
    ConsentGate,
    CreditStatus,
    FilingStatus,
    HandoffStatus,
    MoveLifecycleStatus,
    OrderCancellationReason,
    PlacementStatus,
    ProvisionStatus,
    ReadinessVariant,
    UtilityType,
)


def _saga_move_with_every_leg_open(api):
    """A SCHEDULING move whose five open legs each sit in a different position."""
    bundle = fixtures.full_consent_move(api)
    move_id = bundle["move"]["id"]
    fixtures.pass_identity_by_kba(api, move_id)

    filing = fixtures.draft_filing(api, move_id, forward_start_date="2026-08-10")
    filing = fixtures.submit_filing(api, filing["id"])

    internet_partner = fixtures.add_internet_partner(api)
    insurance_partner = fixtures.add_insurance_partner(api)

    accepted = fixtures.place_referral(
        api, move_id, internet_partner["id"], fixtures.read_move(api, move_id)["version"]
    )
    accepted = assert_ok(
        api.accept_placement(accepted["id"], {}, make_partner_agent_headers(internet_partner["id"]))
    )

    insurance_headers = make_partner_agent_headers(insurance_partner["id"])
    declined = fixtures.place_referral(
        api, move_id, insurance_partner["id"], fixtures.read_move(api, move_id)["version"]
    )
    assert_ok(api.accept_placement(declined["id"], {}, insurance_headers))
    declined = assert_ok(
        api.decline_placement(declined["id"], factories.decline_payload(), insurance_headers)
    )

    fixtures.run_mapping(
        api,
        move_id,
        utility_types=[UtilityType.ELECTRIC.value, UtilityType.WATER.value],
    )
    water_order = fixtures.order_of_type(api, move_id, UtilityType.WATER.value)
    electric_order = fixtures.order_of_type(api, move_id, UtilityType.ELECTRIC.value)
    water_order = fixtures.schedule_order(api, water_order["id"])
    handoff = fixtures.dispatch_credit_check(
        api, electric_order["id"], bureau=BureauName.EQUIFAX.value
    )

    return {
        "feed_source": bundle["feed_source"],
        "resident": bundle["resident"],
        "move": fixtures.read_move(api, move_id),
        "filing": filing,
        "accepted_placement": accepted,
        "declined_placement": declined,
        "water_order": water_order,
        "electric_order": fixtures.read_order(api, electric_order["id"]),
        "handoff": handoff,
    }


def test_01_one_cancellation_call_terminates_the_move_and_clears_its_block(api, ops_headers):
    """The move leaves SCHEDULING for CANCELLED, unblocked and rescored at 50.

    PRD: "is the compensating unwind, available to a `MoveOpsAgent`, a
    `PlatformAdmin` or the originating `FeedIntegrator` from any of the seven
    non-terminal lifecycle states"
    PRD: "Finally `blocked_reason` is reset to `NONE` and `readiness_score` is
    recomputed under the post-verification form."
    PRD: "mapped counts the move's service orders whose `provision_status` is
    anything other than `CANCELLED`"
    PRD: "it applies all four weights — identity 0.30, utility 0.30, filing
    0.20, consent 0.20 — with no renormalisation"

    Design: Corner/consistency_model/saga_move_cancellation_compensates_every_completed_leg_in_one_call
    """
    world = _saga_move_with_every_leg_open(api)
    assert_move_state(world["move"], lifecycle_status=MoveLifecycleStatus.SCHEDULING.value)

    cancelled = assert_ok(
        api.cancel_move(
            world["move"]["id"],
            factories.cancellation_payload("Resident's lease fell through"),
            ops_headers,
        )
    )

    assert_move_state(
        cancelled,
        lifecycle_status=MoveLifecycleStatus.CANCELLED.value,
        blocked_reason=BlockedReason.NONE.value,
        consent_gate=ConsentGate.OPEN.value,
        readiness_score=50,
    )
    assert cancelled["cancellation_reason"] == "Resident's lease fell through", (
        f"the cancellation reason must be recorded on the move, got {cancelled['cancellation_reason']}"
    )

    breakdown = fixtures.read_readiness(api, world["move"]["id"])
    assert_readiness_breakdown(
        breakdown,
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=0,
        filing_component=0,
        consent_component=100,
        readiness_score=50,
    )


def test_02_both_orders_are_cancelled_and_the_credit_leg_is_voided_alongside(api, ops_headers, admin_headers):
    """The scheduled water order releases its window; the electric order's credit voids.

    PRD: "Every service order in `DRAFT`, `SCHEDULED`, `ACTIVE_SERVICE` or
    `SUSPENDED` moves to `CANCELLED` with `cancellation_reason` `MOVE_CANCELLED`
    and both window fields cleared, which releases each occupied service
    window."
    PRD: "Each such cancelled order whose `credit_status` was `PENDING_CHECK` or
    `DEPOSIT_DUE` moves to `VOIDED`, and any of its handoffs in `SUBMITTED` or
    `RESPONDED` moves to `VOIDED`, so the move's open deposit liability returns
    to zero."

    Design: Corner/consistency_model/saga_move_cancellation_compensates_every_completed_leg_in_one_call
    """
    world = _saga_move_with_every_leg_open(api)
    assert_order_dimensions(
        world["water_order"],
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.NOT_REQUIRED.value,
    )
    assert_order_dimensions(
        world["electric_order"],
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.PENDING_CHECK.value,
    )
    assert world["handoff"]["handoff_status"] == HandoffStatus.SUBMITTED.value, (
        f"the bureau handoff must still be open, got {world['handoff']['handoff_status']}"
    )

    assert_ok(api.cancel_move(world["move"]["id"], factories.cancellation_payload(), ops_headers))

    water_after = fixtures.read_order(api, world["water_order"]["id"])
    assert_order_dimensions(
        water_after,
        provision_status=ProvisionStatus.CANCELLED.value,
        credit_status=CreditStatus.NOT_REQUIRED.value,
    )
    assert water_after["cancellation_reason"] == OrderCancellationReason.MOVE_CANCELLED.value, (
        f"expected MOVE_CANCELLED, got {water_after['cancellation_reason']}"
    )
    assert_window_released(water_after)

    electric_after = fixtures.read_order(api, world["electric_order"]["id"])
    assert_order_dimensions(
        electric_after,
        provision_status=ProvisionStatus.CANCELLED.value,
        credit_status=CreditStatus.VOIDED.value,
    )
    assert electric_after["cancellation_reason"] == OrderCancellationReason.MOVE_CANCELLED.value, (
        f"expected MOVE_CANCELLED, got {electric_after['cancellation_reason']}"
    )

    handoff_after = assert_ok(api.get_credit_check_handoff(world["handoff"]["id"], admin_headers))
    assert handoff_after["handoff_status"] == HandoffStatus.VOIDED.value, (
        f"an abandoned bureau handoff must be VOIDED, got {handoff_after['handoff_status']}"
    )
    assert handoff_after["score"] is None, "a handoff the bureau never answered must carry no score"
    assert handoff_after["result"] is None, "a handoff the bureau never answered must carry no result"


def test_03_the_submitted_postal_filing_is_withdrawn_and_forwarding_is_not_confirmed(api, ops_headers, admin_headers):
    """A filing that had reached SUBMITTED is cancelled with no forwarding confirmation.

    PRD: "Every filing in `DRAFT`, `SUBMITTED` or `REJECTED` moves to
    `CANCELLED` with `mail_forwarding_confirmed_at` cleared, releasing the
    resident's forwarding slot."
    PRD: "Successful submission moves `status` to `SUBMITTED`, writes
    `submitted_by_user_id` with the acting `X-User-ID`, and lifts the move's
    readiness filing component to 60."

    Design: Corner/consistency_model/saga_move_cancellation_compensates_every_completed_leg_in_one_call
    """
    world = _saga_move_with_every_leg_open(api)
    assert world["filing"]["status"] == FilingStatus.SUBMITTED.value, (
        f"the filing leg must start out SUBMITTED, got {world['filing']['status']}"
    )

    assert_ok(api.cancel_move(world["move"]["id"], factories.cancellation_payload(), ops_headers))

    filing_after = assert_ok(api.get_filing(world["filing"]["id"], admin_headers))
    assert filing_after["status"] == FilingStatus.CANCELLED.value, (
        f"expected the filing to be CANCELLED, got {filing_after['status']}"
    )
    assert filing_after["mail_forwarding_confirmed_at"] is None, (
        "mail_forwarding_confirmed_at must be clear, releasing the resident's forwarding slot"
    )
    assert filing_after["submitted_by_user_id"] is not None, (
        "the submitting actor stays on the row for audit even after withdrawal"
    )
    assert_page(
        api.list_filings(admin_headers, move_id=world["move"]["id"], status=FilingStatus.SUBMITTED.value),
        total_count=0,
        has_more=False,
    )


def test_04_the_accepted_referral_voids_while_the_declined_one_is_left_untouched(api, ops_headers, admin_headers, compliance_headers):
    """One placement is compensated to VOIDED, the terminal one keeps DECLINED, no ledger.

    PRD: "Every placement in `PLACED` or `ACCEPTED` moves to `VOIDED`, posting no
    ledger entry."
    PRD: "a placement that has reached `DECLINED` is terminal and cannot later
    convert"
    PRD: "`accrued_share_cents` on a `FeedSource` is the sum of the
    already-rounded per-placement `feed_source_share_cents` over that source's
    placements in `CONVERTED` or `SETTLED`"

    Design: Corner/consistency_model/saga_move_cancellation_compensates_every_completed_leg_in_one_call
    """
    world = _saga_move_with_every_leg_open(api)
    assert world["accepted_placement"]["placement_status"] == PlacementStatus.ACCEPTED.value, (
        f"the referral leg must start out ACCEPTED, got {world['accepted_placement']['placement_status']}"
    )
    declined_before = world["declined_placement"]
    assert declined_before["placement_status"] == PlacementStatus.DECLINED.value, (
        f"the sixth leg must already be terminal, got {declined_before['placement_status']}"
    )

    assert_ok(api.cancel_move(world["move"]["id"], factories.cancellation_payload(), ops_headers))

    placements = assert_page(
        api.list_placements(admin_headers, move_id=world["move"]["id"]),
        total_count=2,
        has_more=False,
    )
    by_status = {row["placement_status"]: row for row in placements}
    assert set(by_status) == {PlacementStatus.VOIDED.value, PlacementStatus.DECLINED.value}, (
        f"expected one VOIDED and one DECLINED placement, got {sorted(by_status)}"
    )
    assert by_status[PlacementStatus.VOIDED.value]["id"] == world["accepted_placement"]["id"], (
        "the accepted referral is the leg the compensation had to unwind"
    )

    still_declined = by_status[PlacementStatus.DECLINED.value]
    assert still_declined["id"] == declined_before["id"], (
        "the already-terminal referral must be the row left alone"
    )
    assert still_declined["decline_reason"] == declined_before["decline_reason"], (
        "the compensation must not rewrite a leg that had reached its own terminal state"
    )
    assert still_declined["version"] == declined_before["version"], (
        f"the declined placement must not be rewritten, version moved to {still_declined['version']}"
    )

    assert_page(
        api.list_ledger_entries(compliance_headers, move_id=world["move"]["id"]),
        total_count=0,
        has_more=False,
    )
    assert_cents(fixtures.read_feed_source(api, world["feed_source"]["id"]), "accrued_share_cents", 0)
