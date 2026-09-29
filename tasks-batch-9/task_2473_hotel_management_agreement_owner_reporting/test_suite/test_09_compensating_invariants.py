"""Compensating movements that must restore a balance exactly, without rewriting history."""

from test_helpers import (
    ASSET_HEADERS,
    BudgetDecision,
    CallReason,
    CallStatus,
    ClaimAction,
    ClaimStatus,
    DisputeStatus,
    EmployeeModel,
    EmployerOfRecord,
    FundingSource,
    LedgerEntryType,
    LedgerSourceKind,
    MANAGER_HEADERS,
    PositionClass,
    ReviewDecision,
    ReviewDimension,
    assert_ledger_entry,
    assert_page,
)


# ---------------------------------------------------------------------------
# The append-only reserve ledger: disbursement then compensating reversal
# ---------------------------------------------------------------------------


def _reserve_conservation_hotel(scenario):
    """A reserve of 2200001 drawn to zero by an owner-funded dispute resolution."""
    agreement = scenario.register(
        hotel_name="Reserve Conservation Hotel",
        owner_entity_name="Ledger Owner LP",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0.04,
        centralized_services_cap_pct=0.015,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=1000000,
        max_dispute_rounds=1,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)

    package = scenario.expert_package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    distribution = scenario.only_distribution(package["id"])
    scenario.execute_distribution(distribution["id"])

    dispute = scenario.dispute(
        agreement["id"],
        franchise_requirement_ref="BSR-2026-311",
        estimated_cost_cents=2200001,
        remediation_start_utc="2026-09-01T00:00:00Z",
        remediation_deadline_utc="2026-12-01T00:00:00Z",
    )
    scenario.manager_response(dispute["id"], 2200001)
    scenario.owner_counter(dispute["id"], 2200001)
    scenario.resolve_owner_funds(dispute["id"], FundingSource.FFE_RESERVE)

    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "dispute_id": dispute["id"],
    }


class TestReserveLedgerConservationAcrossFundingAndRescission:
    def test_the_owner_funded_resolution_draws_the_reserve_down_to_zero(self, scenario):
        """PRD §3.9: "a sufficient reserve has a reserve ledger entry appended with `entry_type`
        `DISBURSEMENT`, `amount_cents` equal to the negative of `current_cost_estimate_cents`
        and `source_kind` `BRAND_DISPUTE_FUNDING`, and `ffe_reserve_balance_cents` is decreased
        by that amount."

        Design: Difficulty/compensating_invariant/reserve_ledger_conservation_across_dispute_funding_and_rescission
        """
        state = _reserve_conservation_hotel(scenario)

        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["ffe_reserve_balance_cents"] == 0

        entries = scenario.ledger(state["agreement_id"])
        assert len(entries) == 2
        assert_ledger_entry(
            entries[0],
            entry_type=LedgerEntryType.CONTRIBUTION,
            amount_cents=2200001,
            balance_after_cents=2200001,
            source_kind=LedgerSourceKind.DISTRIBUTION_EXECUTION,
        )
        assert_ledger_entry(
            entries[1],
            entry_type=LedgerEntryType.DISBURSEMENT,
            amount_cents=-2200001,
            balance_after_cents=0,
            source_kind=LedgerSourceKind.BRAND_DISPUTE_FUNDING,
        )

    def test_rescission_appends_a_third_row_that_restores_the_balance(self, scenario):
        """PRD §3.9: "Where the resolution drew on the reserve, rescission appends a
        compensating reserve ledger entry with `entry_type` `DISBURSEMENT_REVERSAL`,
        `amount_cents` equal to the positive `funded_amount_cents` and `source_kind`
        `BRAND_DISPUTE_RESCISSION`, and increases `ffe_reserve_balance_cents` by that amount,
        so the reserve returns to exactly where it stood."

        Design: Difficulty/compensating_invariant/reserve_ledger_conservation_across_dispute_funding_and_rescission
        """
        state = _reserve_conservation_hotel(scenario)

        scenario.rescind(state["dispute_id"])

        assert scenario.read_agreement(state["agreement_id"])["ffe_reserve_balance_cents"] == 2200001
        entries = scenario.ledger(state["agreement_id"])
        assert len(entries) == 3
        assert_ledger_entry(
            entries[2],
            entry_type=LedgerEntryType.DISBURSEMENT_REVERSAL,
            amount_cents=2200001,
            balance_after_cents=2200001,
            source_kind=LedgerSourceKind.BRAND_DISPUTE_RESCISSION,
        )

    def test_the_reversal_mutated_no_earlier_row(self, scenario):
        """PRD §2.9: "Each entry also stores `balance_after_cents`: taking the agreement's
        entries in `created_at` ascending order, that value is the sum of the `amount_cents` of
        every entry created strictly before this one, plus this entry's own `amount_cents`. The
        ledger is append-only and entries are never mutated."

        Design: Difficulty/compensating_invariant/reserve_ledger_conservation_across_dispute_funding_and_rescission
        """
        state = _reserve_conservation_hotel(scenario)

        scenario.rescind(state["dispute_id"])

        entries = scenario.ledger(state["agreement_id"])
        # The running balance replays 2200001 -> 0 -> 2200001 without rewriting history.
        assert [row["balance_after_cents"] for row in entries] == [2200001, 0, 2200001]
        assert_ledger_entry(
            entries[1],
            entry_type=LedgerEntryType.DISBURSEMENT,
            amount_cents=-2200001,
            balance_after_cents=0,
            source_kind=LedgerSourceKind.BRAND_DISPUTE_FUNDING,
        )

    def test_the_signed_sum_of_the_three_rows_equals_the_agreement_balance(self, scenario):
        """PRD §2.9: "One invariant is asserted after every append and holds at all times: the
        agreement's `ffe_reserve_balance_cents` equals the signed sum of `amount_cents` across
        every reserve ledger entry of that agreement."

        Design: Difficulty/compensating_invariant/reserve_ledger_conservation_across_dispute_funding_and_rescission
        """
        state = _reserve_conservation_hotel(scenario)

        scenario.rescind(state["dispute_id"])

        entries = assert_page(
            scenario.api.list_reserve_ledger(state["agreement_id"], ASSET_HEADERS),
            expected_rows=3,
            total_count=3,
            has_more=False,
        )
        signed_sum = sum(row["amount_cents"] for row in entries)
        assert signed_sum == 2200001
        assert (
            signed_sum
            == scenario.read_agreement(state["agreement_id"])["ffe_reserve_balance_cents"]
        )

    def test_rescission_clears_the_funding_without_rewinding_the_round(self, scenario):
        """PRD §3.9: "In every case `funded_amount_cents` is reset to zero and `funding_source`
        is reset to null, while `round` is left unchanged — rescinding does not rewind the
        negotiation count."

        Design: Difficulty/compensating_invariant/reserve_ledger_conservation_across_dispute_funding_and_rescission
        """
        state = _reserve_conservation_hotel(scenario)

        rescinded = scenario.rescind(state["dispute_id"])

        assert rescinded["status"] == DisputeStatus.OWNER_COUNTERED
        assert rescinded["round"] == 1
        assert rescinded["funded_amount_cents"] == 0
        assert rescinded["funding_source"] is None
        # PRD §2.9: working capital moves only through funded calls, the first bucket of an
        # executed distribution, a paid cure and employment-claim allocations.
        assert scenario.read_agreement(state["agreement_id"])["working_capital_balance_cents"] == 1000000


# ---------------------------------------------------------------------------
# Two parent balances restored by an employment-claim reversal
# ---------------------------------------------------------------------------


def _employer_of_record_hotel(scenario):
    """A manager-employed hotel with one odd-cent GM claim still in FILED."""
    agreement = scenario.register(
        hotel_name="Employer Of Record Hotel",
        owner_entity_name="Liability Split Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        employee_model=EmployeeModel.MANAGER_EMPLOYEES,
        manager_indemnity_cap_cents=2000000,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=1000000,
        funding_due_days=15,
    )
    scenario.activate(agreement["id"])

    claim = scenario.claim(
        agreement["id"],
        position_class=PositionClass.GM,
        claim_amount_cents=3000001,
        gross_negligence=False,
    )
    return {"agreement_id": agreement["id"], "claim_id": claim["id"]}


class TestEmploymentClaimAllocationReversalRestoresBothBalances:
    def test_the_odd_cent_of_the_even_split_stays_with_the_owner(self, scenario):
        """PRD §3.9: "Otherwise, where the `position_class` is `GM` or `EXEC_COMMITTEE`, the
        claim is split evenly with the cap applied on top: `manager_share_cents` is the smaller
        of `claim_amount_cents` divided by two using floor division and
        `manager_indemnity_cap_cents`, so an odd-cent claim leaves the extra cent with the
        owner."

        Design: Difficulty/compensating_invariant/employment_claim_allocation_reversal_restores_both_balances
        """
        state = _employer_of_record_hotel(scenario)

        allocated = scenario.allocate_claim(state["claim_id"], ClaimAction.ALLOCATE)

        assert allocated["status"] == ClaimStatus.ALLOCATED
        assert allocated["employer_of_record"] == EmployerOfRecord.MANAGER
        assert allocated["manager_share_cents"] == 1500000
        assert allocated["owner_share_cents"] == 1500001
        # PRD §3.9: the two shares always sum to `claim_amount_cents`.
        assert allocated["manager_share_cents"] + allocated["owner_share_cents"] == 3000001

    def test_allocation_debits_working_capital_and_credits_manager_liability(self, scenario):
        """PRD §3.9: "Allocation moves the claim `FILED → ALLOCATED` and cascades in two hops.
        Because the shares were set, the agreement's `working_capital_balance_cents` is
        decreased by `owner_share_cents` and its `manager_liability_accrued_cents` is increased
        by `manager_share_cents`."

        Design: Difficulty/compensating_invariant/employment_claim_allocation_reversal_restores_both_balances
        """
        state = _employer_of_record_hotel(scenario)

        scenario.allocate_claim(state["claim_id"], ClaimAction.ALLOCATE)

        agreement = scenario.read_agreement(state["agreement_id"])
        # 1000000 less the owner's 1500001 — the one balance permitted to go negative.
        assert agreement["working_capital_balance_cents"] == -500001
        assert agreement["manager_liability_accrued_cents"] == 1500000
        assert agreement["ffe_reserve_balance_cents"] == 0

    def test_the_debit_below_the_floor_raises_one_claim_allocation_call(self, scenario):
        """PRD §3.9: "Then, because that decrease may have pushed the working capital below the
        covenant, a working capital call is created with `reason` `CLAIM_ALLOCATION`,
        `amount_cents` equal to `working_capital_floor_cents` less the now-reduced
        `working_capital_balance_cents`, `auto_created` true and `status` `REQUESTED` — and
        that second hop is skipped entirely when the balance still meets the floor." PRD §3.6:
        "Every call, however raised, has its `due_date_utc` set to the logical clock at the
        moment of issue advanced by the agreement's `funding_due_days`."

        Design: Difficulty/compensating_invariant/employment_claim_allocation_reversal_restores_both_balances
        """
        state = _employer_of_record_hotel(scenario)

        scenario.allocate_claim(state["claim_id"], ClaimAction.ALLOCATE)

        rows = assert_page(
            scenario.api.list_working_capital_calls(state["agreement_id"], MANAGER_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        call = rows[0]
        assert call["reason"] == CallReason.CLAIM_ALLOCATION
        # 500000 less the post-hop balance of -500001.
        assert call["amount_cents"] == 1000001
        assert call["auto_created"] is True
        assert call["status"] == CallStatus.REQUESTED
        assert call["due_date_utc"].startswith("2026-08-16T00:00:00")

    def test_reversal_restores_both_balances_exactly_and_zeroes_the_shares(self, scenario):
        """PRD §3.9: "A `REVERSE` action by `AssetManager` moves the claim
        `ALLOCATED → REVERSED`, increases `working_capital_balance_cents` by
        `owner_share_cents`, decreases `manager_liability_accrued_cents` by
        `manager_share_cents` — restoring both balances exactly — and then resets
        `owner_share_cents` and `manager_share_cents` to zero."

        Design: Difficulty/compensating_invariant/employment_claim_allocation_reversal_restores_both_balances
        """
        state = _employer_of_record_hotel(scenario)
        scenario.allocate_claim(state["claim_id"], ClaimAction.ALLOCATE)

        reversed_claim = scenario.allocate_claim(state["claim_id"], ClaimAction.REVERSE)

        assert reversed_claim["status"] == ClaimStatus.REVERSED
        assert reversed_claim["manager_share_cents"] == 0
        assert reversed_claim["owner_share_cents"] == 0
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["working_capital_balance_cents"] == 1000000
        assert agreement["manager_liability_accrued_cents"] == 0
        assert agreement["ffe_reserve_balance_cents"] == 0

    def test_the_funding_call_survives_the_reversal(self, scenario):
        """PRD §3.9: "Reversal does not retract any working capital call the earlier allocation
        raised; the call stands and follows its own lifecycle."

        Design: Difficulty/compensating_invariant/employment_claim_allocation_reversal_restores_both_balances
        """
        state = _employer_of_record_hotel(scenario)
        scenario.allocate_claim(state["claim_id"], ClaimAction.ALLOCATE)

        scenario.allocate_claim(state["claim_id"], ClaimAction.REVERSE)

        rows = assert_page(
            scenario.api.list_working_capital_calls(state["agreement_id"], MANAGER_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert rows[0]["reason"] == CallReason.CLAIM_ALLOCATION
        assert rows[0]["amount_cents"] == 1000001
        assert rows[0]["status"] == CallStatus.REQUESTED
