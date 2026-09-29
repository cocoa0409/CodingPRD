"""State-machine surface: initial states, declared and undeclared transitions,
terminal lockdown, repeated actions, bounded cycles, side effects and the two
independent contribution dimensions.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    benefit_payload,
    acknowledge_contribution,
    define_tier,
    enrol_member,
    open_fiscal_period,
    proposal_pipeline_action,
    publish_tier,
    read_contribution,
    read_gift_offer,
    read_member,
    read_proposal,
    read_sustainability,
    record_contribution,
    record_gift_offer,
    refund_contribution,
    register_funder,
    review_gift_offer,
    review_proposal,
    run_daily_sweep,
    set_clock,
    setup_cleared_funder,
    settle_contribution,
    submit_offer_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DO_HEADERS, ED_HEADERS, FC_HEADERS, draft_proposal
from test_helpers.test_users import USER_IDS


def _read_tier(tier_id):
    return validate_success(api_client.get_membership_tier(tier_id, DO_HEADERS))


def _published_sustainer():
    """A PUBLISHED benefit-free MONTHLY tier at 2500 cents."""
    tier = define_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    return publish_tier(tier["id"])


class TestMemberInitialState:
    def test_enrolment_leaves_the_renewal_schedule_entirely_unseeded(self):
        """A new member is PENDING with all three date fields null, because the
        schedule is seeded by the settling contribution rather than by enrolment.

        PRD: "A new member is created in status `PENDING` with
        `lifetime_giving_cents` at 0, `is_major_donor` false, `cultivation_locked`
        false, `consecutive_renewals` at 0, and `cycle_start_date`,
        `next_renewal_date` and `grace_expires_at` all null."

        Design: Corner/State Machines/sm_member_initial_state_is_pending_with_no_renewal_dates
        """
        tier = _published_sustainer()

        member = validate_success(
            api_client.create_member(
                {
                    "tier_id": tier["id"],
                    "email": "ana@example.org",
                    "full_name": "Ana Ruiz",
                },
                DO_HEADERS,
            ),
            expected_status=201,
        )

        assert member["status"] == "PENDING"
        assert member["cycle_start_date"] is None
        assert member["next_renewal_date"] is None
        assert member["grace_expires_at"] is None
        assert member["lifetime_giving_cents"] == 0
        assert member["consecutive_renewals"] == 0
        assert member["is_major_donor"] is False
        assert member["cultivation_locked"] is False


class TestGiftOfferSubmissionSideEffects:
    def test_the_netting_outputs_are_written_by_the_submission(self):
        """A 1000000-cent gross sits exactly on the first fee floor, so the
        transition into review writes a 15000 fee and a 985000 net.

        PRD: "Second, `stewardship_fee_cents` is `offered_amount_cents` multiplied
        by the chosen rate in basis points, divided by 10000 and rounded half up to
        whole cents, and `net_acceptable_amount_cents` is `offered_amount_cents`
        minus that fee - the net is what will actually be posted as revenue."

        Design: Corner/State Machines/sm_gift_offer_submit_for_review_recomputes_netting_side_effects
        """
        period = open_fiscal_period()
        funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
        offer = record_gift_offer(
            funder["id"],
            period["id"],
            offered_amount_cents=1000000,
            designation="UNRESTRICTED",
        )

        submitted = submit_offer_for_review(offer["id"])
        assert submitted["status"] == "INDEPENDENCE_REVIEW"
        assert submitted["stewardship_fee_cents"] == 15000
        assert submitted["net_acceptable_amount_cents"] == 985000
        assert submitted["board_ratification_required"] is False
        assert submitted["solicited_by_user_id"] == USER_IDS["development_officer"]
        assert submitted["cleared_by_user_id"] is None
        assert submitted["conditions_round_count"] == 0


class TestMembershipTierPublishPrecondition:
    def test_a_benefit_worth_more_than_the_contribution_blocks_publication(self):
        """36000 a year is 3000 a period on a 2500 monthly tier, so the bundle is
        worth more than the gift and the tier is left in DRAFT.

        PRD: "A benefit bundle worth the entire contribution - or more - leaves
        nothing deductible and makes the tier unpublishable, which is reported as
        `ERR_BENEFIT_VALUE_EXCEEDS_CONTRIBUTION` (HTTP 409)."

        Design: Corner/State Machines/sm_membership_tier_publish_precondition_blocks_benefit_heavy_tier
        """
        tier = define_tier(
            benefits=[benefit_payload("GALA", "EVENT_ACCESS", 36000)],
            tier_code="OVERGIVE",
            name="Overgive",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=2500,
        )

        validate_error(
            api_client.publish_membership_tier(tier["id"], DO_HEADERS),
            ApiErrorId.ERR_BENEFIT_VALUE_EXCEEDS_CONTRIBUTION,
        )

        unchanged = _read_tier(tier["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["published_at"] is None
        assert unchanged["quid_pro_quo_per_period_cents"] == 3000
        assert unchanged["insubstantial_benefit_codes"] == []


class TestMemberUndeclaredTransitions:
    def test_neither_cancel_nor_renew_is_declared_out_of_pending(self):
        """CANCEL is declared from ACTIVE, GRACE and LAPSED and RENEW from ACTIVE
        and GRACE, so a member whose enrolment payment never settled can do neither.

        PRD: "Every one of these actions increments the member's `version` by 1, and
        requesting an action that is not a declared transition out of the member's
        current status is `ERR_INVALID_STATE`, while any action against a
        `CANCELLED` member is `ERR_TERMINAL_STATE`."

        Design: Corner/State Machines/sm_member_cancel_from_pending_is_not_a_declared_transition
        """
        tier = _published_sustainer()
        member = enrol_member(
            tier["id"], email="ana@example.org", full_name="Ana Ruiz"
        )

        validate_error(
            api_client.member_lifecycle_action(
                member["id"], {"action": "CANCEL"}, DO_HEADERS
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        assert read_member(member["id"])["status"] == "PENDING"

        validate_error(
            api_client.member_lifecycle_action(
                member["id"], {"action": "RENEW"}, DO_HEADERS
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        assert read_member(member["id"])["status"] == "PENDING"


class TestGiftOfferTerminalLockdown:
    def test_a_declined_offer_reports_terminal_state_rather_than_invalid_state(self):
        """DECLINED is terminal, so the priority-12 guard answers before the
        source-state guard ever runs, and no contribution was ever written.

        PRD: "`DECLINE` is legal from `INDEPENDENCE_REVIEW` and from
        `CONDITIONS_REQUESTED`, and lands the offer in the terminal status
        `DECLINED`. It records the deciding reviewer as `cleared_by_user_id` and
        creates no contribution - ever."

        Design: Corner/State Machines/sm_gift_offer_declined_is_terminal_and_locks_further_actions
        """
        period = open_fiscal_period()
        funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
        offer = record_gift_offer(
            funder["id"],
            period["id"],
            offered_amount_cents=200000,
            designation="UNRESTRICTED",
        )
        submit_offer_for_review(offer["id"])
        declined = review_gift_offer(
            offer["id"],
            "DECLINE",
            review_note="Donor intent conflicts with the housing desk agenda.",
        )
        assert declined["status"] == "DECLINED"
        assert declined["cleared_by_user_id"] == USER_IDS["editorial_director"]

        validate_error(
            api_client.submit_gift_offer_for_review(offer["id"], {}, DO_HEADERS),
            ApiErrorId.ERR_TERMINAL_STATE,
        )
        assert read_gift_offer(offer["id"])["status"] == "DECLINED"

        _, meta = validate_paginated(api_client.list_contributions(FC_HEADERS))
        assert meta["total_count"] == 0


class TestMembershipTierRepeatedPublish:
    def test_the_second_publish_is_refused_rather_than_silently_absorbed(self):
        """A repeated publish is not idempotent: it reports the source-state guard
        and leaves the original stamp intact.

        PRD: "Publishing an already-`PUBLISHED` tier reports `ERR_INVALID_STATE`."

        Design: Corner/State Machines/sm_membership_tier_publish_twice_reports_invalid_state_not_terminal_state
        """
        tier = define_tier(
            benefits=[],
            tier_code="SUSTAINER",
            name="Sustainer",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=2500,
        )

        published = publish_tier(tier["id"])
        assert published["status"] == "PUBLISHED"
        assert published["published_at"].startswith("2026-08-01T00:00:00")

        validate_error(
            api_client.publish_membership_tier(tier["id"], DO_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
        )

        unchanged = _read_tier(tier["id"])
        assert unchanged["status"] == "PUBLISHED"
        assert unchanged["published_at"] == published["published_at"]


def _setup_proposal_at_three_revision_rounds():
    """An UNRESTRICTED proposal cycled through three revision rounds and left in
    INDEPENDENCE_REVIEW with `revision_round_count` at 3."""
    period = open_fiscal_period()
    funder = setup_cleared_funder(
        legal_name="Ironwood Trust", funder_type="FOUNDATION"
    )
    proposal = draft_proposal(
        funder["id"],
        period["id"],
        title="General operating support",
        requested_amount_cents=350000,
        restriction_type="UNRESTRICTED",
    )
    proposal_pipeline_action(proposal["id"], "SUBMIT_FOR_REVIEW")

    review_proposal(
        proposal["id"],
        "REQUEST_REVISION",
        review_note="Round 1: tighten the independence language.",
    )
    proposal_pipeline_action(proposal["id"], "REVISE")
    proposal_pipeline_action(proposal["id"], "SUBMIT_FOR_REVIEW")

    review_proposal(
        proposal["id"],
        "REQUEST_REVISION",
        review_note="Round 2: drop the naming clause.",
    )
    proposal_pipeline_action(proposal["id"], "SUBMIT_FOR_REVIEW")

    review_proposal(
        proposal["id"],
        "REQUEST_REVISION",
        review_note="Round 3: restate the firewall.",
    )
    proposal_pipeline_action(proposal["id"], "SUBMIT_FOR_REVIEW")

    return {"period": period, "funder": funder, "proposal": proposal}


class TestGrantProposalRevisionCycleIsBounded:
    def test_the_fourth_revision_request_is_refused_and_clearance_still_works(self):
        """Three rounds are legal - re-entering review directly and through a REVISE
        hop back to DRAFT - and the fourth request is refused without disturbing the
        count or blocking a clearance.

        PRD: "`REQUEST_REVISION` moves the proposal to `REVISION_REQUESTED` and
        increments `revision_round_count` by 1; it requires `revision_round_count` to
        be strictly below 3, so at most three revision rounds are possible and a
        fourth attempt is `ERR_REVISION_ROUNDS_EXHAUSTED`."

        Design: Corner/State Machines/sm_grant_proposal_revision_cycle_is_bounded_at_three_rounds
        """
        ctx = _setup_proposal_at_three_revision_rounds()
        proposal_id = ctx["proposal"]["id"]

        in_review = read_proposal(proposal_id)
        assert in_review["status"] == "INDEPENDENCE_REVIEW"
        assert in_review["revision_round_count"] == 3

        validate_error(
            api_client.grant_proposal_internal_review(
                proposal_id,
                {"decision": "REQUEST_REVISION", "review_note": "Round 4 attempt."},
                ED_HEADERS,
            ),
            ApiErrorId.ERR_REVISION_ROUNDS_EXHAUSTED,
        )
        assert read_proposal(proposal_id)["revision_round_count"] == 3

        cleared = review_proposal(proposal_id, "CLEAR")
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_by_user_id"] == USER_IDS["editorial_director"]
        assert cleared["revision_round_count"] == 3


def _setup_initiated_membership_contribution():
    """One PENDING member with a single INITIATED 2500-cent membership row."""
    period = open_fiscal_period()
    tier = _published_sustainer()
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    contribution = record_contribution(
        period["id"],
        "MEMBERSHIP",
        2500,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    return {
        "period": period,
        "tier": tier,
        "member": member,
        "contribution": contribution,
    }


class TestContributionDimensionsAdvanceIndependently:
    def test_a_receipt_can_be_issued_while_the_money_is_still_initiated(self):
        """Acknowledgment moves UNACKNOWLEDGED to RECEIPTED without touching the
        settlement dimension, and the receipt counter starts at one.

        PRD: "With `disclose_publicly` false, an `UNACKNOWLEDGED` contribution whose
        `settlement_status` is anything other than `FAILED` becomes `RECEIPTED`: it
        is assigned a `receipt_number` of the literal `RCPT-` followed by a
        zero-padded six-digit counter that increments once per receipt in the
        `created_at` ascending order of acknowledgment, and its `quid_pro_quo_cents`
        and `deductible_cents` are frozen against later tier changes."

        Design: Corner/State Machines/sm_contribution_settlement_and_acknowledgment_dimensions_advance_independently
        """
        ctx = _setup_initiated_membership_contribution()

        receipted = acknowledge_contribution(
            ctx["contribution"]["id"], disclose_publicly=False
        )
        assert receipted["acknowledgment_status"] == "RECEIPTED"
        assert receipted["receipt_number"] == "RCPT-000001"
        assert receipted["settlement_status"] == "INITIATED"
        assert receipted["quid_pro_quo_cents"] == 0
        assert receipted["deductible_cents"] == 2500

    def test_settling_afterwards_leaves_the_receipt_exactly_where_it_was(self):
        """The settlement advances only its own dimension and activates the member,
        after which the disclosure hop advances only the acknowledgment dimension.

        PRD: "They advance on their own schedules: a contribution may be `RECEIPTED`
        while its money is still merely `INITIATED`, and a `REFUNDED` contribution
        keeps whatever receipt record it had."

        Design: Corner/State Machines/sm_contribution_settlement_and_acknowledgment_dimensions_advance_independently
        """
        ctx = _setup_initiated_membership_contribution()
        acknowledge_contribution(ctx["contribution"]["id"], disclose_publicly=False)

        settled = settle_contribution(ctx["contribution"]["id"])
        assert settled["settlement_status"] == "SETTLED"
        assert settled["acknowledgment_status"] == "RECEIPTED"
        assert settled["receipt_number"] == "RCPT-000001"

        activated = read_member(ctx["member"]["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["cycle_start_date"] == "2026-08-01"
        assert activated["next_renewal_date"] == "2026-09-01"
        assert activated["lifetime_giving_cents"] == 2500

        disclosed = acknowledge_contribution(
            ctx["contribution"]["id"], disclose_publicly=True
        )
        assert disclosed["acknowledgment_status"] == "DISCLOSED"
        assert disclosed["settlement_status"] == "SETTLED"
        assert read_contribution(ctx["contribution"]["id"])["receipt_number"] == (
            "RCPT-000001"
        )


def _setup_active_member_renewing_on_the_first_of_september():
    """An ACTIVE member on a MONTHLY 2500 tier activated by a contribution received
    2026-08-01, so `next_renewal_date` is 2026-09-01."""
    ctx = _setup_initiated_membership_contribution()
    settle_contribution(ctx["contribution"]["id"])
    ctx["member"] = read_member(ctx["member"]["id"])
    return ctx


class TestMemberGraceAndLapseAreDrivenByTheDailySweep:
    def test_the_renewal_date_itself_is_not_yet_overdue(self):
        """The clock reaching `next_renewal_date` is not enough: the date must lie
        strictly in the past.

        PRD: "A member in `ACTIVE` whose `next_renewal_date` now lies strictly in
        the past - the logical clock's date is greater than `next_renewal_date` -
        moves `ACTIVE -> GRACE`, and `grace_expires_at` is stamped as the tier's
        `grace_period_days` counted forward from `next_renewal_date` taken at
        `00:00:00Z`; that instant is when grace runs out."

        Design: Corner/State Machines/sm_member_grace_and_lapse_are_driven_by_the_daily_sweep
        """
        ctx = _setup_active_member_renewing_on_the_first_of_september()
        assert ctx["member"]["next_renewal_date"] == "2026-09-01"

        set_clock("2026-09-01T00:00:00Z")
        report = run_daily_sweep()
        assert report["members_moved_to_grace"] == 0
        assert read_member(ctx["member"]["id"])["status"] == "ACTIVE"

    def test_the_day_after_the_renewal_date_grades_the_member(self):
        """One day past the renewal date the sweep moves the member into GRACE and
        stamps the 30-day grace instant.

        PRD: "It reports what it did as `swept_at` plus five counters -
        `members_moved_to_grace`, `members_moved_to_lapsed`,
        `reports_moved_to_overdue`, `proposals_suspended` and `funders_restricted`."

        Design: Corner/State Machines/sm_member_grace_and_lapse_are_driven_by_the_daily_sweep
        """
        ctx = _setup_active_member_renewing_on_the_first_of_september()

        set_clock("2026-09-01T00:00:00Z")
        run_daily_sweep()
        set_clock("2026-09-02T00:00:00Z")
        report = run_daily_sweep()
        assert report["members_moved_to_grace"] == 1
        assert report["members_moved_to_lapsed"] == 0

        graded = read_member(ctx["member"]["id"])
        assert graded["status"] == "GRACE"
        assert graded["grace_expires_at"].startswith("2026-10-01T00:00:00")

    def test_the_exact_grace_instant_lapses_the_member(self):
        """LAPSED fires when the clock has reached `grace_expires_at`, not the day
        after, and the streak resets.

        PRD: "A member in `GRACE` whose `grace_expires_at` the logical clock has
        reached or passed moves `GRACE -> LAPSED`, which resets
        `consecutive_renewals` to 0 and clears `grace_expires_at` back to null."

        Design: Corner/State Machines/sm_member_grace_and_lapse_are_driven_by_the_daily_sweep
        """
        ctx = _setup_active_member_renewing_on_the_first_of_september()

        set_clock("2026-09-02T00:00:00Z")
        run_daily_sweep()
        set_clock("2026-10-01T00:00:00Z")
        report = run_daily_sweep()
        assert report["members_moved_to_lapsed"] == 1

        lapsed = read_member(ctx["member"]["id"])
        assert lapsed["status"] == "LAPSED"
        assert lapsed["grace_expires_at"] is None
        assert lapsed["consecutive_renewals"] == 0


def _setup_major_donor_at_the_threshold():
    """An ACTIVE member whose single SETTLED 500000-cent membership contribution put
    `lifetime_giving_cents` exactly on the major-donor threshold."""
    period = open_fiscal_period()
    tier = _published_sustainer()
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    contribution = record_contribution(
        period["id"],
        "MEMBERSHIP",
        500000,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    settle_contribution(contribution["id"])
    return {
        "period": period,
        "tier": tier,
        "member": read_member(member["id"]),
        "contribution": contribution,
    }


class TestRefundReversesLifetimeGivingButTheMajorDonorFlagLatches:
    def test_the_threshold_is_inclusive_so_the_member_is_a_major_donor(self):
        """Exactly 500000 cents makes the member a major donor and locks
        cultivation, which is the state the refund is measured against.

        PRD: "A member is a major donor - `is_major_donor` true - once
        `lifetime_giving_cents` reaches **5,000 dollars**; the comparison is
        inclusive, so a member sitting at exactly 500000 cents is a major donor."

        Design: Corner/State Machines/sm_refund_compensation_reverses_lifetime_giving_but_major_donor_latches
        """
        ctx = _setup_major_donor_at_the_threshold()

        assert ctx["member"]["lifetime_giving_cents"] == 500000
        assert ctx["member"]["is_major_donor"] is True
        assert ctx["member"]["cultivation_locked"] is True

    def test_the_refund_reverses_the_money_but_not_the_latch(self):
        """`lifetime_giving_cents` returns to 0 and the period's recognized revenue
        with it, while both latches stay true and the member stays ACTIVE.

        PRD: "Both `is_major_donor` and `cultivation_locked` **latch**: once
        `is_major_donor` has become true it stays true even if a later refund drops
        `lifetime_giving_cents` back under the threshold, and `cultivation_locked` is
        true exactly when `is_major_donor` is true and is likewise never cleared by a
        refund."

        Design: Corner/State Machines/sm_refund_compensation_reverses_lifetime_giving_but_major_donor_latches
        """
        ctx = _setup_major_donor_at_the_threshold()

        refunded = refund_contribution(
            ctx["contribution"]["id"],
            refund_reason="Donor reversed the gift within the pledge window.",
        )
        assert refunded["settlement_status"] == "REFUNDED"
        assert refunded["refunded_at"].startswith("2026-08-01T00:00:00")
        assert refunded["acknowledgment_status"] == "UNACKNOWLEDGED"

        latched = read_member(ctx["member"]["id"])
        assert latched["lifetime_giving_cents"] == 0
        assert latched["is_major_donor"] is True
        assert latched["cultivation_locked"] is True
        assert latched["status"] == "ACTIVE"

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["recognized_revenue_cents"] == 0
        assert picture["concentration_hhi"] == 0
        assert picture["top_source_share_bps"] == 0
        assert picture["reserve_months_target"] == 3
        assert picture["sustainability_posture"] == "WATCH"
