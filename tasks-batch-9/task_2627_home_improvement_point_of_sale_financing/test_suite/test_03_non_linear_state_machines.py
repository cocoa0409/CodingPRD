"""State machines that do not advance in a straight line.

Three entities are exercised: a credit application whose decision axis and
disclosure axis move independently on one row, a project milestone whose
claim/reject/reclaim cycle repeats without limit while its rejection counter
rises, and a funding draw whose settle and deny arms leave disjoint side-effect
sets behind them.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_empty, assert_fields, assert_unchanged, ratio_bps
from test_helpers.test_users import ADMIN_HEADERS, AGENT_HEADERS, SERVICING_AGENT_ID

APPROVED_LIMIT_CENTS = 4320000
FIRST_DRAW_CENTS = 1000050
SECOND_DRAW_CENTS = 1400000
#: 3500000 * min(7000 verified, 7000 pre-completion cap) / 10000
RELEASABLE_CENTS = 2450000
#: 2450000 - 0 settled - (1000050 + 1400000) still REQUESTED
HEADROOM_WITH_BOTH_PENDING = 49950
#: 2450000 - 1000050 settled - 0 still REQUESTED, after the denial releases its reservation
HEADROOM_AFTER_DENIAL = 1449950
SETTLED_DISCOUNT_CENTS = 52402
SETTLED_HOLDBACK_CENTS = 40002
SETTLED_NET_CENTS = 907646


def _application_with_expired_disclosure(api):
    """Deliver at 2026-08-01, move to 2026-08-05 and sweep the unacknowledged disclosure."""
    scenario = S.disclosed_application(api, acknowledge=False)
    assert_fields(scenario.application, decision="APPROVED", disclosure_status="DELIVERED")
    assert scenario.application["disclosure_delivered_at"].startswith("2026-08-01T00:00:00")
    S.set_clock(api, "2026-08-05T00:00:00Z")
    counts = S.run_sweep(api)
    return scenario, counts


def _redelivered_application(api):
    """Take the swept disclosure back to `DELIVERED` at the new clock."""
    scenario, _counts = _application_with_expired_disclosure(api)
    scenario.application = get_success_data(
        api.deliver_disclosure(
            scenario.application_id, F.disclosure_delivery_payload(), scenario.as_merchant
        )
    )
    return scenario


def _milestone_after_two_rejection_rounds(api):
    """Claim, reject, claim, reject one milestone, leaving it standing at `REJECTED`."""
    scenario = S.project_with_milestones(api, releases=(3000,), verify=())
    S.claim_milestone(api, scenario, 0, evidence_ref="PHOTO-TEAROFF-ROUND-1")
    S.verify_milestone(api, scenario, 0, "REJECT")
    S.claim_milestone(api, scenario, 0, evidence_ref="PHOTO-TEAROFF-ROUND-2")
    return scenario, S.verify_milestone(api, scenario, 0, "REJECT")


def _two_requested_draws(api):
    """Two VERIFIED milestones and two live draws that together reserve nearly all headroom."""
    scenario = S.project_with_milestones(api, releases=(3000, 4000), verify=(0, 1))
    assert scenario.project["max_fundable_now_cents"] == RELEASABLE_CENTS
    settle_arm = S.request_draw(api, scenario, FIRST_DRAW_CENTS, 0, "NEXT_DAY")
    deny_arm = S.request_draw(api, scenario, SECOND_DRAW_CENTS, 1, "STANDARD_3DAY")
    return scenario, settle_arm, deny_arm


def _deny(api, draw_id):
    """Render a `DENY` decision on a requested draw as a `ServicingAgent`."""
    return get_success_data(
        api.settle_funding_draw(
            draw_id,
            F.settlement_payload("DENY", denial_reason_code="EVIDENCE_INSUFFICIENT"),
            AGENT_HEADERS,
        )
    )


def test_sweep_moves_the_disclosure_axis_backwards_while_the_decision_stays_approved(api):
    """The unacknowledged disclosure expires without disturbing the decision dimension.

    PRD: "A disclosure standing at `DELIVERED` moves `DELIVERED → EXPIRED_UNACKNOWLEDGED` once the clock is more than three days past `disclosure_delivered_at`."

    Design: Difficulty/non_linear_state_machine/application_decision_and_disclosure_dimensions_evolve_independently
    """
    scenario, counts = _application_with_expired_disclosure(api)

    assert_fields(counts, expired_disclosures=1, expired_offers=0, expired_licenses=0)
    application = S.read_application(api, scenario.application_id)
    assert_fields(
        application,
        disclosure_status="EXPIRED_UNACKNOWLEDGED",
        decision="APPROVED",
        approved_limit_cents=APPROVED_LIMIT_CENTS,
    )
    assert application["offer_expires_at"].startswith("2026-08-15T00:00:00")


def test_redelivery_restarts_the_disclosure_axis_and_leaves_the_decision_frozen(api):
    """The disclosure axis returns to `DELIVERED` on a fresh clock while the decision never moves.

    PRD: "Re-delivery is permitted and is the intended remedy: `EXPIRED_UNACKNOWLEDGED → DELIVERED` requires the application's `decision` to still be `APPROVED` or `COUNTER_OFFERED`, and resets `disclosure_delivered_at` to the current clock, restarting the three-day acknowledgement window from scratch."

    Design: Difficulty/non_linear_state_machine/application_decision_and_disclosure_dimensions_evolve_independently
    """
    scenario = _redelivered_application(api)

    application = scenario.application
    assert_fields(
        application,
        disclosure_status="DELIVERED",
        decision="APPROVED",
        approved_limit_cents=APPROVED_LIMIT_CENTS,
        decision_dti_bps=3646,
    )
    assert application["disclosure_delivered_at"].startswith("2026-08-05T00:00:00")
    assert_empty(application, "disclosure_acknowledged_at")


def test_acceptance_advances_the_decision_axis_leaving_the_disclosure_acknowledged(api):
    """Both axes hold independent terminal positions once the offer is accepted.

    PRD: "That obligation is tracked on the application's disclosure dimension, whose `disclosure_status` moves through `NOT_SENT`, `DELIVERED`, `ACKNOWLEDGED` and `EXPIRED_UNACKNOWLEDGED`, entirely independently of the decision dimension on the same row."

    Design: Difficulty/non_linear_state_machine/application_decision_and_disclosure_dimensions_evolve_independently
    """
    scenario = _redelivered_application(api)

    acknowledged = get_success_data(
        api.acknowledge_disclosure(
            scenario.application_id,
            F.disclosure_acknowledgement_payload(),
            scenario.as_consumer,
        )
    )
    assert acknowledged["disclosure_acknowledged_at"].startswith("2026-08-05T00:00:00")
    activated = get_success_data(
        api.accept_offer(scenario.application_id, F.acceptance_payload(), scenario.as_consumer)
    )

    assert_fields(activated, decision="ACTIVATED", disclosure_status="ACKNOWLEDGED")
    accounts = get_success_data(
        api.list_loan_accounts(ADMIN_HEADERS, {"application_id": scenario.application_id})
    )
    assert len(accounts) == 1, "Acceptance must originate exactly one loan account"
    assert_fields(
        accounts[0],
        promo_status="PROMO_ACTIVE",
        balance_status="CURRENT",
        promo_expires_on="2027-08-05",
        credit_limit_cents=APPROVED_LIMIT_CENTS,
    )


def test_claim_reject_reclaim_cycle_raises_the_rejection_count_on_every_round(api):
    """Two full rounds of the loop leave the counter at two and each claim's own evidence on file.

    PRD: "The `CLAIMED → REJECTED → CLAIMED` loop may repeat without limit, and `rejection_count` keeps rising through it."

    Design: Difficulty/non_linear_state_machine/milestone_claim_reject_reclaim_cycle_counts_rounds
    """
    scenario = S.project_with_milestones(api, releases=(3000,), verify=())

    first_claim = S.claim_milestone(api, scenario, 0, evidence_ref="PHOTO-TEAROFF-ROUND-1")
    assert_fields(
        first_claim, status="CLAIMED", evidence_ref="PHOTO-TEAROFF-ROUND-1", rejection_count=0
    )
    first_reject = S.verify_milestone(api, scenario, 0, "REJECT")
    assert_fields(first_reject, status="REJECTED", rejection_count=1)
    assert_empty(first_reject, "verified_at")

    second_claim = S.claim_milestone(api, scenario, 0, evidence_ref="PHOTO-TEAROFF-ROUND-2")
    assert_fields(
        second_claim, status="CLAIMED", evidence_ref="PHOTO-TEAROFF-ROUND-2", rejection_count=1
    )
    second_reject = S.verify_milestone(api, scenario, 0, "REJECT")
    assert_fields(second_reject, status="REJECTED", rejection_count=2)


def test_rejected_rounds_release_nothing_and_only_the_final_verify_moves_the_share(api):
    """A milestone at `CLAIMED` or `REJECTED` releases nothing; only `VERIFIED` adds its share.

    PRD: "First, the project's `verified_release_bps` is the sum of `release_pct_bps` over its milestones standing at `VERIFIED` only — a milestone at `PENDING`, `CLAIMED` or `REJECTED` releases nothing at all, no matter how convincing its evidence."

    Design: Difficulty/non_linear_state_machine/milestone_claim_reject_reclaim_cycle_counts_rounds
    """
    scenario, _rejected = _milestone_after_two_rejection_rounds(api)

    after_rejections = S.read_project(api, scenario.project_id)
    assert_fields(
        after_rejections,
        verified_release_bps=0,
        max_fundable_now_cents=0,
        completion_status="IN_PROGRESS",
    )

    S.claim_milestone(api, scenario, 0, evidence_ref="PHOTO-TEAROFF-ROUND-3")
    mid_cycle = S.read_project(api, scenario.project_id)
    assert_fields(mid_cycle, verified_release_bps=0, max_fundable_now_cents=0)
    S.verify_milestone(api, scenario, 0, "VERIFY")

    # 3500000 * min(3000 verified, 7000 pre-completion cap) / 10000 == 1050000
    after_verify = S.read_project(api, scenario.project_id)
    assert_fields(
        after_verify,
        verified_release_bps=3000,
        max_fundable_now_cents=1050000,
        completion_status="IN_PROGRESS",
    )


def test_rejection_count_survives_the_cycle_exit_into_verified(api):
    """The counter is not reset by the transition that finally leaves the loop.

    PRD: "The milestone state machine has no terminal state at all — every state is reachable again."

    Design: Difficulty/non_linear_state_machine/milestone_claim_reject_reclaim_cycle_counts_rounds
    """
    scenario, rejected = _milestone_after_two_rejection_rounds(api)
    assert rejected["rejection_count"] == 2

    S.claim_milestone(api, scenario, 0, evidence_ref="PHOTO-TEAROFF-ROUND-3")
    verified = S.verify_milestone(api, scenario, 0, "VERIFY")

    assert_fields(
        verified,
        status="VERIFIED",
        rejection_count=2,
        evidence_ref="PHOTO-TEAROFF-ROUND-3",
        is_funded=False,
    )
    assert verified["verified_at"], "A verified milestone must carry verified_at"


def test_two_live_draws_reserve_their_headroom_before_either_branch_is_taken(api):
    """Requested draws hold their amounts out of the project's headroom while undecided.

    PRD: "Fourth, `max_fundable_now_cents` is that releasable amount reduced by the project's `settled_funded_cents` and reduced again by the total `requested_amount_cents` of every draw on the project still standing at `REQUESTED`, with the result floored at zero so it never goes negative."

    Design: Difficulty/non_linear_state_machine/funding_draw_settle_versus_deny_fork_has_divergent_side_effect_sets
    """
    scenario, settle_arm, deny_arm = _two_requested_draws(api)

    assert_fields(settle_arm, status="REQUESTED", funded_amount_cents=FIRST_DRAW_CENTS)
    assert_fields(deny_arm, status="REQUESTED", funded_amount_cents=SECOND_DRAW_CENTS)
    project = S.read_project(api, scenario.project_id)
    assert (
        RELEASABLE_CENTS - 0 - FIRST_DRAW_CENTS - SECOND_DRAW_CENTS
        == HEADROOM_WITH_BOTH_PENDING
    )
    assert_fields(
        project,
        settled_funded_cents=0,
        verified_release_bps=7000,
        max_fundable_now_cents=HEADROOM_WITH_BOTH_PENDING,
    )


def test_settle_branch_rewrites_the_draw_loan_merchant_and_project_records(api):
    """The settling branch prices the final variant and moves money onto four rows.

    PRD: "The two branches are deliberately asymmetric: one moves money and rewrites six records, the other moves nothing at all."

    Design: Difficulty/non_linear_state_machine/funding_draw_settle_versus_deny_fork_has_divergent_side_effect_sets
    """
    scenario, settle_arm, _deny_arm = _two_requested_draws(api)

    settled = S.settle_draw(api, scenario, settle_arm["id"])
    assert_fields(
        settled,
        status="SETTLED",
        settled_on="2026-08-01",
        released_by_user_id=SERVICING_AGENT_ID,
        merchant_discount_cents=SETTLED_DISCOUNT_CENTS,
        holdback_withheld_cents=SETTLED_HOLDBACK_CENTS,
        net_settlement_cents=SETTLED_NET_CENTS,
    )
    assert_empty(settled, "denial_reason_code")

    loan = S.read_loan(api, scenario.loan_id)
    assert_fields(
        loan, principal_balance_cents=FIRST_DRAW_CENTS, total_funded_cents=FIRST_DRAW_CENTS
    )
    merchant = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        merchant,
        funded_volume_cents=FIRST_DRAW_CENTS,
        holdback_reserve_cents=SETTLED_HOLDBACK_CENTS,
    )
    project = S.read_project(api, scenario.project_id)
    # ratio_bps(1000050, 3500000) == 2857.28... -> 2857
    assert_fields(
        project,
        settled_funded_cents=FIRST_DRAW_CENTS,
        funded_pct_bps=ratio_bps(FIRST_DRAW_CENTS, 3500000),
    )
    assert project["funded_pct_bps"] == 2857


def test_deny_branch_records_only_the_reason_and_touches_no_money(api):
    """Denial leaves the final variant uncomputed and the ledger exactly where it stood.

    PRD: "The `REQUESTED → DENIED` branch is the mirror image and its restraint is the point: it records `denial_reason_code` and touches no money whatsoever."

    Design: Difficulty/non_linear_state_machine/funding_draw_settle_versus_deny_fork_has_divergent_side_effect_sets
    """
    scenario, settle_arm, deny_arm = _two_requested_draws(api)
    S.settle_draw(api, scenario, settle_arm["id"])
    loan_before = S.read_loan(api, scenario.loan_id)

    denied = _deny(api, deny_arm["id"])

    assert_fields(
        denied,
        status="DENIED",
        denial_reason_code="EVIDENCE_INSUFFICIENT",
        funded_amount_cents=SECOND_DRAW_CENTS,
    )
    assert_empty(
        denied,
        "merchant_discount_cents",
        "holdback_withheld_cents",
        "net_settlement_cents",
        "settled_on",
        "released_by_user_id",
    )
    assert_unchanged(
        loan_before,
        S.read_loan(api, scenario.loan_id),
        "version",
        "principal_balance_cents",
        "total_funded_cents",
    )


def test_denied_headroom_is_released_back_to_the_project_not_consumed(api):
    """After the fork only the settled draw has spent headroom; the denied one gave its back.

    PRD: "Fourth, `max_fundable_now_cents` is that releasable amount reduced by the project's `settled_funded_cents` and reduced again by the total `requested_amount_cents` of every draw on the project still standing at `REQUESTED`, with the result floored at zero so it never goes negative."

    Design: Difficulty/non_linear_state_machine/funding_draw_settle_versus_deny_fork_has_divergent_side_effect_sets
    """
    scenario, settle_arm, deny_arm = _two_requested_draws(api)
    S.settle_draw(api, scenario, settle_arm["id"])
    _deny(api, deny_arm["id"])

    project = S.read_project(api, scenario.project_id)
    assert RELEASABLE_CENTS - FIRST_DRAW_CENTS - 0 == HEADROOM_AFTER_DENIAL
    assert_fields(
        project,
        settled_funded_cents=FIRST_DRAW_CENTS,
        max_fundable_now_cents=HEADROOM_AFTER_DENIAL,
    )
    milestones = S.read_milestones(api, scenario.project_id)
    assert milestones[0]["is_funded"] is True, "The settled milestone must be marked funded"
    assert milestones[1]["is_funded"] is False, "The denied milestone must not be marked funded"
