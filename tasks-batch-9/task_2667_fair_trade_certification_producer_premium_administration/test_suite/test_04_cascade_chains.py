"""Consequences that travel: an escalating finding reaching a pending shipment, and an
approved disbursement reaching a sibling draft."""

from test_helpers import (
    AUDITOR_1_ID,
    CHAIR,
    OFFICER,
    assert_fund_partition,
    assert_money,
    assert_node_position,
    assert_pct,
    factories as f,
    validate_paginated,
    validate_success,
)


def _chain_with_a_pending_shipment_and_a_critical_finding(api):
    """A 12000 kg reservation held against a producer that carries one critical finding."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    trade = f.record_trade(api, chain, 12000, declared_unit_price_cents_per_kg=500)
    audit = f.build_started_audit(
        api, chain["producer_id"], "2026-08-01", "2026-08-05",
        auditor_user_id=AUDITOR_1_ID, audit_type="SURVEILLANCE",
    )
    finding = f.raise_finding(
        api, audit["id"], "CRITICAL", "FT-4.2.1",
        "Premium payment records missing for two harvests",
    )
    chain["trade_id"] = trade["id"]
    chain["audit_id"] = audit["id"]
    chain["finding_id"] = finding["id"]
    return chain


class TestSweepEscalationChain:
    """One lapsed deadline suspends a holder, its node and the shipment out of that node."""

    def test_the_sweep_reports_every_hop_it_applied(self, api, clock, advance_clock):
        """Run twenty-five days past the finding's deadline, the sweep reports one overdue, one
        escalated, one suspended holder, one suspended node and one disputed shipment.

        Design: Difficulty/transitive_cascade/sweep_escalation_chains_from_nonconformity_to_holder_to_nodes_to_trades
        """
        _chain_with_a_pending_shipment_and_a_critical_finding(api)

        advance_clock("2026-08-26T00:00:00Z")
        swept = validate_success(api.run_compliance_sweep(OFFICER), 200)

        assert swept["overdue_count"] == 1, f"expected 1 overdue, got {swept['overdue_count']}"
        assert swept["escalated_count"] == 1, (
            f"expected 1 escalated, got {swept['escalated_count']}"
        )
        assert swept["suspended_holder_count"] == 1
        assert swept["suspended_node_count"] == 1
        assert swept["disputed_transaction_count"] == 1
        assert swept["decertified_holder_count"] == 0

    def test_the_chain_ends_by_releasing_the_reservation_on_the_disputed_shipment(
        self, api, clock, advance_clock
    ):
        """The finding escalates, the producer is suspended for escalation, its node follows, and
        the shipment out of that node is disputed with its 12000 kg reservation released.

        Design: Difficulty/transitive_cascade/sweep_escalation_chains_from_nonconformity_to_holder_to_nodes_to_trades
        """
        chain = _chain_with_a_pending_shipment_and_a_critical_finding(api)

        advance_clock("2026-08-26T00:00:00Z")
        validate_success(api.run_compliance_sweep(OFFICER), 200)

        assert f.read_nonconformity(api, chain["finding_id"])["status"] == "ESCALATED"
        holder = f.read_holder(api, chain["producer_id"])
        assert holder["certificate_status"] == "SUSPENDED"
        assert holder["suspension_reason"] == "NONCONFORMITY_ESCALATION"
        seller_node = f.read_node(api, chain["seller_node_id"])
        assert seller_node["status"] == "SUSPENDED"
        trade = f.read_trade(api, chain["trade_id"])
        assert trade["verification_status"] == "DISPUTED"
        assert trade["settlement_status"] == "PENDING"
        assert_node_position(
            seller_node, reserved_output_kg=0, available_credit_kg=50000,
        )

    def test_the_cascade_stops_at_the_suspended_holder_s_own_nodes(
        self, api, clock, advance_clock
    ):
        """The counterparty is not part of the chain: the brand stays CERTIFIED and its node ACTIVE.

        Design: Difficulty/transitive_cascade/sweep_escalation_chains_from_nonconformity_to_holder_to_nodes_to_trades
        """
        chain = _chain_with_a_pending_shipment_and_a_critical_finding(api)

        advance_clock("2026-08-26T00:00:00Z")
        validate_success(api.run_compliance_sweep(OFFICER), 200)

        assert f.read_node(api, chain["buyer_node_id"])["status"] == "ACTIVE"
        assert f.read_holder(api, chain["brand_id"])["certificate_status"] == "CERTIFIED"


def _committee_with_two_approvals_pending(api):
    """A 3000000 cent fund, one approved 2400000 proposal, one round open on 500000 and one draft."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    committee = f.constitute_committee(
        api, chain["producer_id"], member_count=5,
        approved_use_categories=["EDUCATION", "INFRASTRUCTURE"],
    )
    chain["committee_id"] = committee["id"]
    f.record_settled_trade(api, chain, 30000, declared_unit_price_cents_per_kg=500, is_organic=True)

    first = f.draft_proposal(
        api, chain, 2400000, title="Wet mill upgrade", use_category="INFRASTRUCTURE",
        use_period_start="2026-09-01", use_period_end="2026-10-01",
    )
    validate_success(api.open_vote(first["id"], CHAIR), 200)
    f.cast_ballots(api, first["id"], ["APPROVE", "APPROVE", "REJECT"])
    validate_success(api.close_vote(first["id"], CHAIR), 200)

    second = f.draft_proposal(
        api, chain, 500000, title="Adult literacy classes", use_category="EDUCATION",
        use_period_start="2026-10-01", use_period_end="2026-11-01",
    )
    third = f.draft_proposal(
        api, chain, 50000, title="Nursery seedlings", use_category="INFRASTRUCTURE",
        use_period_start="2026-11-01", use_period_end="2026-12-01",
    )
    validate_success(api.open_vote(second["id"], CHAIR), 200)
    f.cast_ballots(api, second["id"], ["APPROVE", "APPROVE", "ABSTAIN"])

    chain["first_proposal_id"] = first["id"]
    chain["second_proposal_id"] = second["id"]
    chain["third_proposal_id"] = third["id"]
    return chain


class TestApprovalCommitmentChain:
    """An approval writes a commitment, the commitment drains the fund, and the drained fund
    restricts the committee."""

    def test_the_approval_appends_the_commitment_that_leaves_the_fund_at_one_hundred_thousand(
        self, api, clock
    ):
        """Closing the second round approves it on 60.00 turnout and 66.67 approval, appending a
        second COMMITMENT entry for 500000 cents that leaves 100000 cents behind it.

        Design: Difficulty/transitive_cascade/approved_proposal_chains_from_ledger_to_fund_to_committee_to_sibling_drafts
        """
        chain = _committee_with_two_approvals_pending(api)

        closed = validate_success(api.close_vote(chain["second_proposal_id"], CHAIR), 200)

        assert closed["status"] == "APPROVED"
        assert_pct(closed["turnout_pct"], "60.00", "turnout_pct")
        assert_pct(closed["approval_pct"], "66.67", "approval_pct")
        commitments, _ = validate_paginated(
            api.list_ledger_entries(
                OFFICER, {"fund_id": chain["fund_id"], "entry_type": "COMMITMENT"}
            )
        )
        assert len(commitments) == 2, f"expected 2 commitment entries, got {len(commitments)}"
        assert_money(commitments[-1]["amount_cents"], 500000, "amount_cents")
        assert_money(commitments[-1]["balance_after_cents"], 100000, "balance_after_cents")

    def test_the_fund_moves_money_between_partitions_without_accruing_any(self, api, clock):
        """Both approvals together commit 2900000 of the 3000000 ever accrued, leaving a 100000
        cent balance and pushing the committee to RESTRICTED.

        Design: Difficulty/transitive_cascade/approved_proposal_chains_from_ledger_to_fund_to_committee_to_sibling_drafts
        """
        chain = _committee_with_two_approvals_pending(api)

        validate_success(api.close_vote(chain["second_proposal_id"], CHAIR), 200)

        fund = f.read_fund(api, chain["producer_id"])
        assert_fund_partition(
            fund, total_accrued_cents=3000000, balance_cents=100000, committed_cents=2900000
        )
        assert f.read_committee(api, chain["committee_id"])["status"] == "RESTRICTED"

    def test_the_restriction_cancels_the_sibling_draft_but_spares_the_earlier_approval(
        self, api, clock
    ):
        """The still-drafted third proposal is cancelled by the restriction, the earlier approval
        is untouched, and no proposal is left open or pending anywhere.

        Design: Difficulty/transitive_cascade/approved_proposal_chains_from_ledger_to_fund_to_committee_to_sibling_drafts
        """
        chain = _committee_with_two_approvals_pending(api)

        validate_success(api.close_vote(chain["second_proposal_id"], CHAIR), 200)

        assert f.read_proposal(api, chain["third_proposal_id"])["status"] == "CANCELLED"
        assert f.read_proposal(api, chain["first_proposal_id"])["status"] == "APPROVED"
        assert f.read_committee(api, chain["committee_id"])["open_proposal_count"] == 0
        assert f.read_fund(api, chain["producer_id"])["pending_proposal_count"] == 0
