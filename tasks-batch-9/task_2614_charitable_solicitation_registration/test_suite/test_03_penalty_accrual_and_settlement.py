"""Late-penalty accrual and the remediation settlement total.

A missed renewal deadline accrues month by month, and the rounding happens
inside each month rather than once at the end. The settlement a charity pays to
come back into good standing is then keyed on the penalties themselves.
"""

import pytest

from test_helpers import (
    REGULATOR,
    api_client,
    issue_enforcement_action,
    move_clock_to,
    read_enforcement_action,
    read_organization,
    read_registration,
    remediate_action,
    run_sweep,
    setup_registered_filing,
    setup_two_registered_filings,
    validate_paginated,
    validate_success,
)


def _action_for_registration(registration_id: str):
    """The enforcement action a sweep raised against one filing."""
    response = api_client.list_enforcement_actions(
        REGULATOR, params={"registration_id": registration_id}
    )
    actions, _meta = validate_paginated(response)
    assert actions, f"Expected an enforcement action on filing {registration_id}"
    return actions[0]


class TestLatePenaltyRoundingOrder:
    """Each month's charge is rounded before the months are added up."""

    def test_a_four_month_delinquency_rounds_every_month_before_summing(self):
        """PRD §3.9: "**Each month's charge is rounded half up to whole cents
        individually, before any summation.** The rounded monthly charges are
        summed, and the total is capped at the state's `late_fee_cap_cents`
        (default 50,000 cents) by taking the smaller of the two. The rounding
        order is observable and must not be re-arranged: with a base of 2,004
        cents, an escalation of 0.125 and four months late, rounding each month
        first gives 2,004 plus 2,255 plus 2,505 plus 2,756, which is 9,520 cents,
        whereas summing the unrounded monthly amounts and rounding once gives
        9,519 cents."

        Design: Difficulty/combinatorial_formula/late_penalty_per_month_rounding_before_summation_ca
        """
        ctx = setup_registered_filing()
        move_clock_to("2027-02-28T00:00:00Z")

        action = issue_enforcement_action(
            ctx["organization"]["id"], ctx["registration"]["id"], "PENALTY_ASSESSMENT"
        )

        assert action["penalty_cents"] == 9_520, (
            "106 days late is four accrual months of 2,004 / 2,255 / 2,505 / "
            f"2,756, got {action['penalty_cents']}"
        )
        assert action["penalty_cents"] != 9_519, (
            "9,519 is what summing the unrounded monthly amounts would produce"
        )
        assert action["cure_deadline"] == "2027-03-30T00:00:00.000Z", (
            "The issuing clock plus California's thirty-day cure period, got "
            f"{action['cure_deadline']}"
        )
        assert action["status"] == "OPEN", (
            f"A newly issued action is born OPEN, got {action['status']}"
        )
        assert action["state_code"] == "CA", (
            f"The state is copied from the linked filing, got {action['state_code']}"
        )
        assert read_organization(ctx["organization"]["id"])[
            "penalty_outstanding_cents"
        ] == 9_520, "Issuance raises the ledger by exactly the action's penalty"

    def test_a_six_month_delinquency_accrues_the_escalated_half_cent_months_separately(
        self,
    ):
        """PRD §3.9: "for each month index counting from 1 up to the number of
        months late, that month's charge is the state's `late_fee_base_cents`
        (default 2,000 cents) multiplied by one plus the state's
        `late_fee_escalation_pct` (default 0.1) times one less than the month
        index — so the first month is the plain base amount, the second is the
        base plus one escalation step, the third the base plus two steps, and so
        on."

        Design: Difficulty/combinatorial_formula/late_penalty_per_month_rounding_before_summation_ca
        """
        ctx = setup_registered_filing()
        move_clock_to("2027-04-14T00:00:00Z")

        action = issue_enforcement_action(
            ctx["organization"]["id"], ctx["registration"]["id"], "PENALTY_ASSESSMENT"
        )

        assert action["penalty_cents"] == 15_783, (
            "151 days late is six accrual months of 2,004 / 2,255 / 2,505 / "
            f"2,756 / 3,006 / 3,257, got {action['penalty_cents']}"
        )
        assert action["penalty_cents"] != 15_782, (
            "15,782 is what rounding the summed unrounded months would produce"
        )
        assert action["cure_deadline"] == "2027-05-14T00:00:00.000Z", (
            "The issuing clock plus thirty whole days, got "
            f"{action['cure_deadline']}"
        )


class TestMonthBucketBoundary:
    """Day ninety closes the third accrual month; day ninety-one opens a fourth."""

    def test_ninety_days_late_accrues_exactly_three_months(self):
        """PRD §3.9: "the number of months late is the days late divided by thirty
        and rounded **up** to the next whole number, so a single day late is
        already one month." PRD §3.9 also fixes the sweep's own arithmetic:
        "`cure_deadline` set to the sweep's clock plus the state's
        `cure_period_days` (default 30 days) counted in whole days."

        Design: Difficulty/boundary_precision_check/late_penalty_month_bucket_boundary_at_90_and_91_days
        """
        ctx = setup_two_registered_filings(domicile="CA", second_state="NV")

        assert ctx["registration"]["effective_due_date"] == "2026-11-14T00:00:00.000Z"
        assert (
            ctx["second_registration"]["effective_due_date"]
            == "2026-11-14T00:00:00.000Z"
        ), "Both states derive the same deadline from a June fiscal year end"

        move_clock_to("2027-02-12T00:00:00Z")
        run_sweep("CA")

        action = _action_for_registration(ctx["registration"]["id"])
        assert action["penalty_cents"] == 6_764, (
            "Ninety days late is 2,004 + 2,255 + 2,505, got "
            f"{action['penalty_cents']}"
        )
        assert action["cure_deadline"] == "2027-03-14T00:00:00.000Z", (
            f"The sweep clock plus thirty days, got {action['cure_deadline']}"
        )
        assert (
            read_registration(ctx["second_registration"]["id"])["status"]
            == "REGISTERED"
        ), "A sweep narrowed to California leaves the Nevada filing alone"

    def test_ninety_one_days_late_opens_a_fourth_month_and_the_ledger_holds_both_sums(
        self,
    ):
        """PRD §2.12: "`Organization.penalty_outstanding_cents` is at all times
        exactly the sum of `penalty_cents` over that organization's enforcement
        actions whose `status` is `OPEN`, `REMEDIATION_SUBMITTED` or `ESCALATED`;
        actions in `CURED` or `VACATED` contribute nothing."

        Design: Difficulty/boundary_precision_check/late_penalty_month_bucket_boundary_at_90_and_91_days
        """
        ctx = setup_two_registered_filings(domicile="CA", second_state="NV")

        move_clock_to("2027-02-12T00:00:00Z")
        run_sweep("CA")
        move_clock_to("2027-02-13T00:00:00Z")
        run_sweep("NV")

        nevada = _action_for_registration(ctx["second_registration"]["id"])
        assert nevada["penalty_cents"] == 9_520, (
            "Ninety-one days late adds a fourth month of 2,756, got "
            f"{nevada['penalty_cents']}"
        )

        organization = read_organization(ctx["organization"]["id"])
        assert organization["penalty_outstanding_cents"] == 16_284, (
            f"6,764 plus 9,520, got {organization['penalty_outstanding_cents']}"
        )
        assert organization["delinquent_registration_count"] == 2, (
            "Both filings were swept into delinquency, got "
            f"{organization['delinquent_registration_count']}"
        )
        assert organization["registered_state_count"] == 0, (
            "Neither filing is registered any more, got "
            f"{organization['registered_state_count']}"
        )
        assert organization["filing_posture"] == "DELINQUENT", (
            f"A delinquent filing moves the posture, got {organization['filing_posture']}"
        )


class TestSettlementDiscountTier:
    """The discount is keyed on the penalty subtotal, not on the final total."""

    def test_an_eighteen_thousand_cent_subtotal_earns_no_discount_on_the_reinstatement_fee(
        self,
    ):
        """PRD §3.9: "The definition looks circular to a careless reader, who keys
        the discount on the final total and inflates the discount; the pinned
        order resolves it. With a penalty subtotal of 18,000 cents and an
        undiscounted reinstatement fee of 12,500 cents, the correct result is no
        discount, a reinstatement charge of 12,500 and a settlement total of
        30,500 cents — not the 29,250 that keying the tier on the 30,500 total
        would have produced."

        Design: Difficulty/combinatorial_formula/remediation_settlement_discount_keyed_on_penalty_subtotal_ca
        """
        ctx = setup_registered_filing()
        action = issue_enforcement_action(
            ctx["organization"]["id"],
            ctx["registration"]["id"],
            "PENALTY_ASSESSMENT",
            penalty_cents_override=18_000,
        )

        remediated = validate_success(remediate_action(action["id"]))

        assert remediated["penalty_cents"] == 18_000, (
            f"The override is taken verbatim, got {remediated['penalty_cents']}"
        )
        assert remediated["settlement_total_cents"] == 30_500, (
            "18,000 of penalties plus an undiscounted 12,500 reinstatement fee, "
            f"got {remediated['settlement_total_cents']}"
        )
        assert remediated["settlement_total_cents"] != 29_250, (
            "29,250 is what keying the discount tier on the total would produce"
        )
        assert remediated["status"] == "REMEDIATION_SUBMITTED", (
            f"The action awaits a decision, got {remediated['status']}"
        )
        assert read_organization(ctx["organization"]["id"])[
            "penalty_outstanding_cents"
        ] == 18_000, "A submitted remediation is still an outstanding matter"

    @pytest.mark.parametrize(
        "penalty_cents,expected_total",
        [
            (19_999, 32_499),
            (20_000, 31_250),
            (50_000, 60_000),
        ],
    )
    def test_each_discount_tier_is_selected_on_the_penalty_subtotal(
        self, penalty_cents, expected_total
    ):
        """PRD §3.9: "a discount rate is selected **on that subtotal**: a subtotal
        of $500.00 (50,000 cents) or more earns 20 percent, a subtotal of $200.00
        (20,000 cents) or more but under $500.00 earns 10 percent, and anything
        below $200.00 earns no discount. Third, the reinstatement charge is the
        state's `reinstatement_fee_cents` (default 12,500 cents) multiplied by one
        minus that discount rate, rounded half up to whole cents — the single
        rounding step in this calculation. Fourth, `settlement_total_cents` is the
        penalty subtotal plus that reinstatement charge."

        Design: Difficulty/combinatorial_formula/remediation_settlement_discount_keyed_on_penalty_subtotal_ca
        """
        ctx = setup_registered_filing()
        action = issue_enforcement_action(
            ctx["organization"]["id"],
            ctx["registration"]["id"],
            "PENALTY_ASSESSMENT",
            penalty_cents_override=penalty_cents,
        )

        remediated = validate_success(remediate_action(action["id"]))

        assert remediated["settlement_total_cents"] == expected_total, (
            f"A subtotal of {penalty_cents} settles at {expected_total}, got "
            f"{remediated['settlement_total_cents']}"
        )

    def test_the_subtotal_gathers_every_live_action_on_the_same_filing(self):
        """PRD §3.9: "the penalty subtotal is the sum of `penalty_cents` over every
        enforcement action sharing this action's `registration_id` whose `status`
        is `OPEN`, `REMEDIATION_SUBMITTED` or `ESCALATED`, this action included;
        actions in `CURED` or `VACATED` are excluded, and the sum is taken at
        transition time with no time window."

        Design: Difficulty/combinatorial_formula/remediation_settlement_discount_keyed_on_penalty_subtotal_ca
        """
        ctx = setup_registered_filing()
        first = issue_enforcement_action(
            ctx["organization"]["id"],
            ctx["registration"]["id"],
            "PENALTY_ASSESSMENT",
            penalty_cents_override=10_000,
        )
        second = issue_enforcement_action(
            ctx["organization"]["id"],
            ctx["registration"]["id"],
            "PENALTY_ASSESSMENT",
            penalty_cents_override=10_000,
        )

        remediated = validate_success(remediate_action(first["id"]))

        assert remediated["settlement_total_cents"] == 31_250, (
            "A 20,000 subtotal earns ten percent, so 20,000 plus 11,250, got "
            f"{remediated['settlement_total_cents']}"
        )
        assert read_enforcement_action(second["id"])["settlement_total_cents"] == 0, (
            "The sibling action has not been remediated, so nothing is stamped on it"
        )
