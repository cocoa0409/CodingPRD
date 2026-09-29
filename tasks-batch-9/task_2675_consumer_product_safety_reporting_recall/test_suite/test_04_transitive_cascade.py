"""Single triggers whose consequences land three and four rows away."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field_values,
    assert_fields_null,
    assert_reserve_conserved,
    assert_unit_ledger_conserved,
    assert_version_advanced,
)

# The plan is approved while the clock still reads the filing instant, so the
# stop-sale takes effect then and the acknowledgement falls due 72 hours later.
APPROVAL_INSTANT = "2026-03-13T00:00:00"
ACK_DUE_INSTANT = "2026-03-16T00:00:00"
FULFILMENT_INSTANT = "2026-03-14T00:00:00"

ASSESSED_PENALTY_CENTS = 5500000
PREVIEW_WITHOUT_BONUS_CENTS = 4675000
PREVIEW_WITH_BONUS_CENTS = 4400000


def _instant(value):
    """The second-resolution prefix of an ISO 8601 instant."""
    return str(value)[:19]


class TestPlanApprovalStopSaleCascade:
    """One signature reaching the recall, its notification and the retailer."""

    def _approved_plan(self, api):
        """A submitted plan with one pending notification, then approved."""
        env = fx.submitted_recall_env(api)
        env["notification_before"] = fx.get_notification(api, env["notification_id"])
        env["retailer_before"] = fx.get_retailer(api, env["retailer_id"])

        assert_field_values(
            env["notification_before"],
            status="PENDING",
            stop_sale_required=False,
        )
        assert_field_values(
            env["retailer_before"],
            compliance_posture="CLEAR",
            open_stop_sale_count=0,
            verified_removal_count=0,
            delinquent_count=0,
        )
        assert_field_values(
            env["recall"],
            plan_status="SUBMITTED",
            notification_status="NOT_STARTED",
        )

        env["approved"] = fx.approve_plan(api, env["recall_id"])
        return env

    def test_first_link_advances_the_plan_and_the_notification_dimension(self, api):
        """Approval stamps the stop-sale instant and starts the notification dimension.

        The contract states: "The first link advances `plan_status` `SUBMITTED →
        APPROVED` and stamps `stop_sale_effective_at` with the logical clock." The
        second dimension follows from the notification link: "A follow-on effect of
        that link moves the recall's `notification_status` `NOT_STARTED →
        IN_PROGRESS`, but only when at least one notification actually flipped".

        Design: Difficulty/transitive_cascade/plan_approval_cascades_recall_to_notification_to_retailer_posture_depth3
        """
        env = self._approved_plan(api)

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall,
            plan_status="APPROVED",
            notification_status="IN_PROGRESS",
            units_in_commerce=100,
            units_corrected=0,
        )
        assert _instant(recall["stop_sale_effective_at"]) == APPROVAL_INSTANT
        assert_unit_ledger_conserved(recall)

    def test_second_link_issues_the_pending_notification_with_a_72_hour_deadline(
        self, api
    ):
        """The notification the payload never names is issued with its own deadline.

        The contract states: "The second link reaches every retailer notification
        on this recall whose `status` is `PENDING` and flips it `PENDING → ISSUED`,
        setting `stop_sale_required` to true, `issued_at` to that same
        logical-clock instant, and `ack_due_at` to `issued_at` plus 72 hours (three
        days), processing the notifications in `created_at` ascending order." That
        row is only visible on its own read surface: "no creation response ever
        contains the sibling rows a cascade touched."

        Design: Difficulty/transitive_cascade/plan_approval_cascades_recall_to_notification_to_retailer_posture_depth3
        """
        env = self._approved_plan(api)

        notification = fx.get_notification(api, env["notification_id"])
        assert_field_values(
            notification,
            status="ISSUED",
            stop_sale_required=True,
            recall_id=env["recall_id"],
            retailer_id=env["retailer_id"],
        )
        assert _instant(notification["issued_at"]) == APPROVAL_INSTANT
        assert _instant(notification["ack_due_at"]) == ACK_DUE_INSTANT
        assert_fields_null(notification, "acknowledged_at", "verified_at")
        assert_version_advanced(env["notification_before"], notification)

        rows, _meta = validate_paginated(
            fx.list_notifications(api, recall_id=env["recall_id"], status="ISSUED")
        )
        assert [row["id"] for row in rows] == [env["notification_id"]], (
            "the filtered collection is the channel the issuance cascade shows up on"
        )

    def test_third_link_raises_the_retailers_stop_sale_count_and_posture(self, api):
        """The cascade lands on a retailer two hops from the approved plan.

        The contract states: "The third link reaches each flipped notification's
        retailer, incrementing that retailer's `open_stop_sale_count` by 1 and
        setting its `compliance_posture` to `STOP_SALE_ACTIVE`. Every notification
        and every retailer touched has its `version` incremented by 1."

        Design: Difficulty/transitive_cascade/plan_approval_cascades_recall_to_notification_to_retailer_posture_depth3
        """
        env = self._approved_plan(api)

        retailer = fx.get_retailer(api, env["retailer_id"])
        assert_field_values(
            retailer,
            compliance_posture="STOP_SALE_ACTIVE",
            open_stop_sale_count=1,
            verified_removal_count=0,
            delinquent_count=0,
        )
        assert_version_advanced(env["retailer_before"], retailer)


class TestClaimFulfilmentCreditCascade:
    """One fulfilment reaching the ledger, the flag and the penalty docket."""

    def _fulfilled_thirty_unit_claim(self, api):
        """A monitoring recall with a penalty docket and one thirty-unit claim fulfilled."""
        env = fx.penalty_case_env(api, violation_count=4)

        assert_field_values(
            env["case"],
            status="ASSESSMENT_OPEN",
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
            cooperation_bonus_applied=False,
            consent_agreement_preview_cents=PREVIEW_WITHOUT_BONUS_CENTS,
        )

        claim = fx.create_claim(
            api,
            env["recall_id"],
            consumer_ref="CR-3001",
            remedy_type="REFUND",
            quantity=30,
            unit_price_cents=4999,
            shipping_cents_per_unit=899,
        )
        env["claim_id"] = claim["id"]
        fx.approve_claim(api, claim["id"])

        env["recall_before"] = fx.get_recall(api, env["recall_id"])
        env["case_before"] = fx.get_penalty_case(api, env["case_id"])
        env["fulfilled"] = fx.fulfill_claim(api, claim["id"])
        return env

    def test_first_two_links_fulfil_the_claim_and_rewrite_the_unit_ledger(self, api):
        """Fulfilment stamps the claim and moves thirty units across the ledger.

        The contract states: "Its first link advances the claim `APPROVED →
        FULFILLED` and stamps `fulfilled_at` with the logical clock. Its second
        link moves the recall's unit ledger: `units_corrected` increases by the
        claim's `quantity` and `units_outstanding` decreases by the same
        `quantity`, so that the conserved sum of the two continues to equal
        `units_in_commerce`." The priced total does not move with it: "The claim's
        `reimbursement_total_cents` is computed once at registration and frozen".

        Design: Difficulty/transitive_cascade/claim_fulfilment_cascades_ledger_to_effectiveness_to_cooperation_credit_depth4
        """
        env = self._fulfilled_thirty_unit_claim(api)

        claim = fx.get_claim(api, env["claim_id"])
        assert_field_values(
            claim,
            status="FULFILLED",
            quantity=30,
            reimbursement_total_cents=190200,
        )
        assert _instant(claim["fulfilled_at"]) == FULFILMENT_INSTANT
        assert_fields_null(claim, "voided_at")

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall,
            units_in_commerce=100,
            units_corrected=30,
            units_outstanding=70,
        )
        assert_unit_ledger_conserved(recall)
        assert_version_advanced(env["recall_before"], recall)

    def test_third_link_flips_the_effectiveness_flag_when_the_rate_reaches_the_goal(
        self, api
    ):
        """Thirty of a hundred units corrected exactly reaches a thirty percent goal.

        The contract states: "Its third link, triggered because `units_corrected`
        changed, re-evaluates the correction rate on the units basis and flips the
        recall's `effectiveness_flag` from `PENDING` to `MET` when that rate has
        reached the recall's `participation_goal_pct`." The rate itself is defined
        as: "On the `UNITS_BASIS` variant the denominator is the recall's
        `units_in_commerce`, that is every unit believed to be in consumer hands;
        this is the regulator-facing correction rate, and it is the variant that
        always drives `effectiveness_flag`."

        Design: Difficulty/transitive_cascade/claim_fulfilment_cascades_ledger_to_effectiveness_to_cooperation_credit_depth4
        """
        env = self._fulfilled_thirty_unit_claim(api)

        assert_field_values(env["recall_before"], effectiveness_flag="PENDING")

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall,
            effectiveness_flag="MET",
            plan_status="MONITORING",
        )
        assert_decimal_equals(recall["participation_goal_pct"], "30.00")

    def test_fourth_link_grants_the_bonus_and_reprices_the_settlement_preview(
        self, api
    ):
        """The effectiveness milestone cuts the penalty preview four hops downstream.

        The contract states: "Its fourth link, triggered only when the third
        produced `MET`, reaches the civil penalty case whose `section_report_id`
        equals the recall's own `section_report_id` and whose `status` is
        `ASSESSMENT_OPEN`, `OFFER_MADE` or `COUNTERED`: that case has
        `cooperation_bonus_applied` set to true, its non-binding settlement preview
        recomputed, and its `version` incremented by 1." The boosted rate is
        defined as: "When `cooperation_bonus_applied` is true, five further
        percentage points are added to the tier's percentage, subject to an overall
        ceiling of thirty percent". In the preview variant "only
        `consent_agreement_preview_cents` is written".

        Design: Difficulty/transitive_cascade/claim_fulfilment_cascades_ledger_to_effectiveness_to_cooperation_credit_depth4
        """
        env = self._fulfilled_thirty_unit_claim(api)

        case = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            case,
            status="ASSESSMENT_OPEN",
            cooperation_bonus_applied=True,
            consent_agreement_preview_cents=PREVIEW_WITH_BONUS_CENTS,
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
            reserved_cents=0,
            available_cents=ASSESSED_PENALTY_CENTS,
        )
        assert_fields_null(
            case,
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
        )
        assert_version_advanced(env["case_before"], case)
        assert_reserve_conserved(case)
