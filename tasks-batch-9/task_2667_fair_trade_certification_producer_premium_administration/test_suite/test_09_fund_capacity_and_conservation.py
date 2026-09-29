"""What the premium fund will let a committee promise, and what it takes back when a promise
or a shipment is undone."""

from test_helpers import (
    CHAIR,
    OFFICER,
    api_errors as E,
    assert_clock_stamp,
    assert_created_at_ascending,
    assert_fund_conservation,
    assert_fund_partition,
    assert_ledger_entry,
    assert_money,
    assert_node_position,
    assert_volume,
    factories as f,
    validate_error,
    validate_success,
)


def _funded_committee_with_one_long_approval(api):
    """A 3000000 cent fund with 1500000 already committed across September and October."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    committee = f.constitute_committee(
        api, chain["producer_id"], member_count=5,
        approved_use_categories=["EDUCATION", "INFRASTRUCTURE"],
    )
    chain["committee_id"] = committee["id"]
    f.record_settled_trade(api, chain, 30000, declared_unit_price_cents_per_kg=500, is_organic=True)

    first = f.draft_proposal(
        api, chain, 1500000, title="Autumn school block", use_category="EDUCATION",
        use_period_start="2026-09-01", use_period_end="2026-11-01",
    )
    validate_success(api.open_vote(first["id"], CHAIR), 200)
    f.cast_ballots(api, first["id"], ["APPROVE", "APPROVE", "REJECT"])
    validate_success(api.close_vote(first["id"], CHAIR), 200)
    chain["first_proposal_id"] = first["id"]
    return chain


def _open_a_clinic_round(api, chain, use_period_start, use_period_end):
    proposal = f.draft_proposal(
        api, chain, 950000, title="Clinic extension", use_category="INFRASTRUCTURE",
        use_period_start=use_period_start, use_period_end=use_period_end,
    )
    validate_success(api.open_vote(proposal["id"], CHAIR), 200)
    f.cast_ballots(api, proposal["id"], ["APPROVE", "APPROVE", "ABSTAIN"])
    return proposal


class TestFundWindowCapacity:
    """Overlapping plans are capped in aggregate, not one by one."""

    def test_two_affordable_approvals_that_overlap_breach_the_capacity_ceiling(
        self, api, clock
    ):
        """1500000 already approved for September to November plus 950000 for October to December
        is 2450000, past the 2400000 the fund's lifetime accrual allows in one overlapping window.

        Design: Difficulty/resource_temporal_overlap/fund_window_capacity_rejects_the_aggregate_of_overlapping_use_periods
        """
        chain = _funded_committee_with_one_long_approval(api)
        proposal = _open_a_clinic_round(api, chain, "2026-10-01", "2026-12-01")

        response = api.close_vote(proposal["id"], CHAIR)

        validate_error(response, E.ERR_FUND_PERIOD_CAPACITY_EXCEEDED, 409)
        blocked = f.read_proposal(api, proposal["id"])
        assert blocked["status"] == "UNDER_VOTE"
        assert blocked["approved_at"] is None
        fund = f.read_fund(api, chain["producer_id"])
        assert_fund_partition(fund, balance_cents=1500000, committed_cents=1500000)
        assert fund["pending_proposal_count"] == 1
        assert int(fund["balance_cents"]) > 950000, (
            "the refusal is a capacity refusal, not a shortage of money"
        )

    def test_the_same_amount_over_a_non_overlapping_window_is_approved(self, api, clock):
        """Moved to November and December, where it merely touches the approved window, the same
        950000 cent plan closes as APPROVED.

        Design: Difficulty/resource_temporal_overlap/fund_window_capacity_rejects_the_aggregate_of_overlapping_use_periods
        """
        chain = _funded_committee_with_one_long_approval(api)
        proposal = _open_a_clinic_round(api, chain, "2026-11-01", "2026-12-01")

        closed = validate_success(api.close_vote(proposal["id"], CHAIR), 200)

        assert closed["status"] == "APPROVED"
        assert_fund_partition(
            f.read_fund(api, chain["producer_id"]),
            balance_cents=550000, committed_cents=2450000, total_accrued_cents=3000000,
        )


def _settled_organic_shipment(api):
    """A 30000 kg organic lot moved, verified and settled, accruing 3000000 cents."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    committee = f.constitute_committee(api, chain["producer_id"], member_count=5)
    chain["committee_id"] = committee["id"]
    trade = f.record_settled_trade(
        api, chain, 30000, declared_unit_price_cents_per_kg=500, is_organic=True
    )
    chain["trade_id"] = trade["id"]
    chain["trade"] = trade
    chain["fund_id"] = f.read_fund(api, chain["producer_id"])["id"]
    return chain


def _void(api, trade_id):
    return api.void_trade(
        trade_id, {"reason": "Buyer returned the lot as non-conforming"}, OFFICER
    )


class TestVoidingASettledTrade:
    """Voiding gives every kilogram and every cent back to where it came from."""

    def test_voided_trade_is_reversed_without_losing_its_verification_history(self, api, clock):
        """The settlement is undone and stamped, while the auditor's verdict on the shipment
        stays on the record.

        Design: Difficulty/compensating_invariant/void_settled_trade_restores_the_conserved_kilograms_on_both_nodes
        """
        chain = _settled_organic_shipment(api)

        voided = validate_success(_void(api, chain["trade_id"]), 200)

        assert voided["settlement_status"] == "REVERSED"
        assert_clock_stamp(voided["voided_at"], clock, "voided_at")
        assert voided["verification_status"] == "VERIFIED", (
            "voiding the settlement does not erase the verification outcome"
        )
        assert_money(voided["premium_cents"], 3000000, "premium_cents")

    def test_both_sides_of_the_link_return_to_their_pre_trade_kilograms(self, api, clock):
        """The seller's 30000 claimed kilograms go back into its available credit and the
        buyer's certified input drops back to nothing.

        Design: Difficulty/compensating_invariant/void_settled_trade_restores_the_conserved_kilograms_on_both_nodes
        """
        chain = _settled_organic_shipment(api)

        validate_success(_void(api, chain["trade_id"]), 200)

        seller = f.read_node(api, chain["seller_node_id"])
        assert_node_position(
            seller,
            certified_input_kg="50000.000",
            reserved_output_kg="0.000",
            claimed_output_kg="0.000",
            available_credit_kg="50000.000",
        )
        buyer = f.read_node(api, chain["buyer_node_id"])
        assert_volume(buyer["certified_input_kg"], "0.000", "buyer certified_input_kg")

    def test_the_reversal_is_a_new_ledger_row_that_empties_the_fund(self, api, clock):
        """The accrual is not deleted; a mirroring reversal is appended after it and the fund
        falls back to zero, which puts its committee back under restriction.

        Design: Difficulty/compensating_invariant/void_settled_trade_restores_the_conserved_kilograms_on_both_nodes
        """
        chain = _settled_organic_shipment(api)

        validate_success(_void(api, chain["trade_id"]), 200)

        entries = f.read_ledger_entries(api, fund_id=chain["fund_id"])
        assert len(entries) == 2, f"expected an accrual and its reversal, got {len(entries)}"
        assert_created_at_ascending(entries)
        assert_ledger_entry(
            entries[0], "ACCRUAL", 3000000, balance_after_cents=3000000,
            trade_transaction_id=chain["trade_id"],
        )
        assert_ledger_entry(
            entries[1], "REVERSAL", 3000000, balance_after_cents=0,
            trade_transaction_id=chain["trade_id"],
        )
        fund = f.read_fund(api, chain["producer_id"])
        assert_fund_partition(
            fund, total_accrued_cents=0, balance_cents=0, committed_cents=0, disbursed_cents=0
        )
        assert_fund_conservation(fund, entries)
        assert f.read_committee(api, chain["committee_id"])["status"] == "RESTRICTED"


def _approve_a_round(api, proposal_id, ballots=("APPROVE", "APPROVE", "APPROVE")):
    validate_success(api.open_vote(proposal_id, CHAIR), 200)
    f.cast_ballots(api, proposal_id, list(ballots))
    return validate_success(api.close_vote(proposal_id, CHAIR), 200)


def _committee_with_two_approved_plans(api):
    """3000000 accrued, 2400000 promised to a road and 500000 to a training course."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    committee = f.constitute_committee(
        api, chain["producer_id"], member_count=5,
        approved_use_categories=["EDUCATION", "INFRASTRUCTURE"],
    )
    chain["committee_id"] = committee["id"]
    f.record_settled_trade(api, chain, 30000, declared_unit_price_cents_per_kg=500, is_organic=True)
    chain["fund_id"] = f.read_fund(api, chain["producer_id"])["id"]

    first = f.draft_proposal(
        api, chain, 2400000, title="Access road resurfacing", use_category="INFRASTRUCTURE",
        use_period_start="2026-09-01", use_period_end="2026-10-01",
    )
    _approve_a_round(api, first["id"])
    second = f.draft_proposal(
        api, chain, 500000, title="Agronomy training course", use_category="EDUCATION",
        use_period_start="2026-10-01", use_period_end="2026-11-01",
    )
    _approve_a_round(api, second["id"])
    chain["first_proposal_id"] = first["id"]
    chain["second_proposal_id"] = second["id"]
    return chain


def _cancel(api, proposal_id):
    return api.cancel_proposal(proposal_id, CHAIR, {"reason": "Trainer contract fell through"})


class TestCancellingAnApprovedProposal:
    """Cancelling releases the promised money back into the spendable balance."""

    def test_cancelled_proposal_is_stamped_and_its_money_returns_to_the_balance(
        self, api, clock
    ):
        """The 500000 cents promised to the training course move from committed back to balance,
        leaving the fund's three parts still summing to everything ever accrued.

        Design: Difficulty/compensating_invariant/cancel_approved_proposal_restores_the_conserved_money_partition
        """
        chain = _committee_with_two_approved_plans(api)

        cancelled = validate_success(_cancel(api, chain["second_proposal_id"]), 200)

        assert cancelled["status"] == "CANCELLED"
        assert_clock_stamp(cancelled["cancelled_at"], clock, "cancelled_at")
        fund = f.read_fund(api, chain["producer_id"])
        assert_fund_partition(
            fund,
            total_accrued_cents=3000000,
            balance_cents=600000,
            committed_cents=2400000,
            disbursed_cents=0,
        )

    def test_the_release_row_mirrors_the_commitment_row_it_undoes(self, api, clock):
        """The commitment stays in the ledger and a release is appended after it, carrying the
        balance from 100000 back up to 600000 without changing the accrued total.

        Design: Difficulty/compensating_invariant/cancel_approved_proposal_restores_the_conserved_money_partition
        """
        chain = _committee_with_two_approved_plans(api)

        validate_success(_cancel(api, chain["second_proposal_id"]), 200)

        rows = f.read_ledger_entries(
            api, fund_id=chain["fund_id"], proposal_id=chain["second_proposal_id"]
        )
        assert len(rows) == 2, f"expected a commitment and its release, got {len(rows)}"
        assert_created_at_ascending(rows)
        assert_ledger_entry(
            rows[0], "COMMITMENT", 500000, balance_after_cents=100000,
            proposal_id=chain["second_proposal_id"],
        )
        assert_ledger_entry(
            rows[1], "RELEASE", 500000, balance_after_cents=600000,
            proposal_id=chain["second_proposal_id"],
        )
        assert_fund_conservation(
            f.read_fund(api, chain["producer_id"]),
            f.read_ledger_entries(api, fund_id=chain["fund_id"]),
        )

    def test_the_committee_recovers_and_the_other_plan_is_left_alone(self, api, clock):
        """With 600000 cents spendable again the committee leaves restriction, and the road
        resurfacing keeps its approval.

        Design: Difficulty/compensating_invariant/cancel_approved_proposal_restores_the_conserved_money_partition
        """
        chain = _committee_with_two_approved_plans(api)
        assert f.read_committee(api, chain["committee_id"])["status"] == "RESTRICTED"

        validate_success(_cancel(api, chain["second_proposal_id"]), 200)

        assert f.read_committee(api, chain["committee_id"])["status"] == "ACTIVE"
        untouched = f.read_proposal(api, chain["first_proposal_id"])
        assert untouched["status"] == "APPROVED"
        assert_money(untouched["requested_amount_cents"], 2400000, "requested_amount_cents")
