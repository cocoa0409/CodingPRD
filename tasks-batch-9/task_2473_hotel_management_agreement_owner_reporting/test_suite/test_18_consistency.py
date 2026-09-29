"""Immediate consistency: the response body and the very next read tell the same story."""

from test_helpers import (
    ASSET_HEADERS,
    AccrualStatus,
    BudgetDecision,
    BudgetStatus,
    CallReason,
    CallStatus,
    DistributionStatus,
    FinancialStatus,
    MANAGER_HEADERS,
    OWNER_HEADERS,
    ReviewDecision,
    ReviewDimension,
    assert_object_envelope,
    assert_page,
    owner_review_payload,
    working_capital_call_payload,
)


# ---------------------------------------------------------------------------
# The acceptance cascade is visible in the first read that follows
# ---------------------------------------------------------------------------


def _immediate_cascade_hotel(scenario):
    """A SUBMITTED (2026, 9) period whose closing cash is zero, ready for acceptance."""
    agreement = scenario.register(
        hotel_name="Immediate Cascade Hotel",
        owner_entity_name="Immediate Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
        funding_due_days=15,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)
    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.submit_package(package["id"])
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


def _accept_financial(scenario, package_id):
    """The owner's FINANCIAL acceptance, returned as its raw response."""
    return scenario.api.review_report_package(
        package_id,
        owner_review_payload(ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT),
        OWNER_HEADERS,
    )


class TestOwnerReviewResponseAlreadyReflectsTheFullCascade:
    def test_the_response_body_and_the_next_accrual_read_agree(self, scenario):
        """PRD §3.6: "moves `financial_status` `SUBMITTED → ACCEPTED` and sets off a four-hop
        cascade. Because the dimension became `ACCEPTED`, every fee accrual of that package sitting
        in `ACCRUED` moves to `INVOICED`, processed in `created_at` ascending order."

        Design: Corner/consistency model/owner_review_response_already_reflects_the_full_cascade
        """
        state = _immediate_cascade_hotel(scenario)

        reviewed = assert_object_envelope(_accept_financial(scenario, state["package_id"]), 200)

        # The write's own body already carries the new status: no settling read is needed.
        assert reviewed["financial_status"] == FinancialStatus.ACCEPTED
        rows = assert_page(
            scenario.api.list_fee_accruals(
                state["package_id"], OWNER_HEADERS, {"status": AccrualStatus.INVOICED}
            ),
            expected_rows=2,
            total_count=2,
            has_more=False,
        )
        assert sorted(row["amount_cents"] for row in rows) == [780000, 1922000]

    def test_the_distribution_and_the_shortfall_call_are_there_on_the_first_read(self, scenario):
        """PRD §3.6: "a `CashDistribution` row is created in `status` `CALCULATED` with its buckets
        filled by the waterfall described below." And "a call with `reason`
        `DISTRIBUTION_SHORTFALL`, `amount_cents` equal to the distribution's `shortfall_cents`,
        `auto_created` set to true and `status` `REQUESTED`." PRD §3.7: "Every call, however raised,
        has its `due_date_utc` set to the logical clock at the moment of issue advanced by the
        agreement's `funding_due_days`."

        Design: Corner/consistency model/owner_review_response_already_reflects_the_full_cascade
        """
        state = _immediate_cascade_hotel(scenario)
        _accept_financial(scenario, state["package_id"])

        distributions = assert_page(
            scenario.api.list_distributions(state["package_id"], OWNER_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        calls = assert_page(
            scenario.api.list_working_capital_calls(
                state["agreement_id"], OWNER_HEADERS, {"reason": CallReason.DISTRIBUTION_SHORTFALL}
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )

        distribution = distributions[0]
        assert distribution["status"] == DistributionStatus.CALCULATED
        for bucket in (
            "wc_restoration_cents",
            "base_fee_paid_cents",
            "reserve_contribution_cents",
            "owner_priority_paid_cents",
            "incentive_fee_paid_cents",
            "residual_to_owner_cents",
        ):
            assert distribution[bucket] == 0
        assert distribution["shortfall_cents"] == 3702000
        assert calls[0]["amount_cents"] == 3702000
        assert calls[0]["auto_created"] is True
        assert calls[0]["status"] == CallStatus.REQUESTED
        assert calls[0]["due_date_utc"].startswith("2026-08-16T00:00:00")


# ---------------------------------------------------------------------------
# The sweep counters and the swept rows move in the same instant
# ---------------------------------------------------------------------------


def _sweep_consistency_hotel(scenario):
    """A SUBMITTED budget due 2026-08-31 and a REQUESTED call due 2026-08-16."""
    agreement = scenario.register(
        hotel_name="Sweep Consistency Hotel",
        owner_entity_name="Consistency Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        owner_review_window_days=30,
        funding_due_days=15,
        initial_working_capital_cents=0,
        working_capital_floor_cents=0,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    submitted = scenario.submit_budget(budget["id"])
    call = scenario.api.create_working_capital_call(
        agreement["id"],
        working_capital_call_payload(500000, CallReason.FLOOR_RESTORATION),
        MANAGER_HEADERS,
    )
    return {
        "agreement_id": agreement["id"],
        "budget_id": budget["id"],
        "deadline": submitted["owner_decision_deadline_utc"],
        "call_id": assert_object_envelope(call, 201)["id"],
    }


class TestClockSweepCountersAgreeWithImmediatelyFollowingReads:
    def test_every_counter_is_matched_by_the_read_that_follows_it(self, scenario):
        """PRD §2.10: "Every budget in `SUBMITTED` whose `owner_decision_deadline_utc` is strictly
        before the new clock value becomes `DEEMED_APPROVED`. The count is reported as
        `deemed_approved_budget_count`." And "Every working capital call in `REQUESTED` whose
        `due_date_utc` is strictly before the new clock value becomes `OVERDUE`, with no cash
        movement. The count is reported as `overdue_call_count`."

        Design: Corner/consistency model/clock_sweep_counters_agree_with_immediately_following_reads
        """
        state = _sweep_consistency_hotel(scenario)
        assert state["deadline"].startswith("2026-08-31T00:00:00")

        swept = scenario.set_clock("2026-09-01T00:00:00Z")

        assert swept["deemed_approved_budget_count"] == 1
        assert swept["overdue_call_count"] == 1
        deemed = assert_page(
            scenario.api.list_budgets(
                ASSET_HEADERS,
                {"agreement_id": state["agreement_id"], "status": BudgetStatus.DEEMED_APPROVED},
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert deemed[0]["id"] == state["budget_id"]
        overdue = assert_page(
            scenario.api.list_working_capital_calls(
                state["agreement_id"], ASSET_HEADERS, {"status": CallStatus.OVERDUE}
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert overdue[0]["id"] == state["call_id"]
        # The old status is gone in the same instant the new one arrived.
        assert_page(
            scenario.api.list_budgets(
                ASSET_HEADERS,
                {"agreement_id": state["agreement_id"], "status": BudgetStatus.SUBMITTED},
            ),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

    def test_replaying_the_same_clock_value_sweeps_nothing(self, scenario):
        """PRD §2.10: "Every performance test in `FAILED_CURABLE` or `CURE_ELECTED` whose
        `cure_deadline_utc` is strictly before the new clock value becomes
        `TERMINATION_TRIGGERED`. The count is reported as `lapsed_cure_count`." And "Every dispute in
        `ESCALATED_TO_FRANCHISOR` whose `standstill_end_utc` is at or before the new clock value
        becomes `DEADLOCKED`. The count is reported as `deadlocked_dispute_count`." And "Every
        agreement in `TERMINATION_NOTICED` whose `termination_effective_utc` is at or before the new
        clock value becomes `TERMINATED`. The count is reported as `terminated_agreement_count`."

        Design: Corner/consistency model/clock_sweep_counters_agree_with_immediately_following_reads
        """
        state = _sweep_consistency_hotel(scenario)
        scenario.set_clock("2026-09-01T00:00:00Z")

        replayed = scenario.set_clock("2026-09-01T00:00:00Z")

        assert replayed["current_utc"].startswith("2026-09-01T00:00:00")
        for counter in (
            "deemed_approved_budget_count",
            "overdue_call_count",
            "lapsed_cure_count",
            "deadlocked_dispute_count",
            "terminated_agreement_count",
        ):
            assert replayed[counter] == 0
        assert scenario.read_budget(state["budget_id"])["status"] == BudgetStatus.DEEMED_APPROVED
