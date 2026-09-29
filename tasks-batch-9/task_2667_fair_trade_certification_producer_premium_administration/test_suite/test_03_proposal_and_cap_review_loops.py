"""Two review cycles that are not straight lines: a vote that sends a proposal back for
revision, and a corrective action plan that is rejected once before it is accepted."""

from test_helpers import (
    AUDITOR_1_ID,
    CHAIR,
    OFFICER,
    assert_fund_partition,
    assert_instant,
    assert_money,
    assert_pct,
    assert_score,
    factories as f,
    validate_paginated,
    validate_success,
)


def _committee_with_a_drafted_proposal(api):
    """An ACTIVE five-member committee over a 1200000 cent fund, holding one DRAFT proposal."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    committee = f.constitute_committee(
        api, chain["producer_id"], member_count=5,
        approved_use_categories=["EDUCATION", "INFRASTRUCTURE"],
    )
    chain["committee_id"] = committee["id"]
    f.record_settled_trade(api, chain, 12000, declared_unit_price_cents_per_kg=500, is_organic=True)
    proposal = f.draft_proposal(api, chain, 500000, title="School roof repair")
    chain["proposal_id"] = proposal["id"]
    return chain


def _revise_and_reopen(api, proposal_id):
    validate_success(
        api.revise_proposal(
            proposal_id,
            f.revision_payload("School roof repair, phase 1", "EDUCATION", 400000),
            CHAIR,
        ),
        200,
    )


class TestProposalVoteForksBackToRevision:
    """Closing a round is a fork: one branch returns the proposal to its drafters."""

    def test_a_short_first_round_sends_the_proposal_back_and_round_two_approves_it(
        self, api, clock
    ):
        """Two of five ballots close the first round at REVISION_REQUESTED on 40.00 turnout with
        100.00 approval; after revision, the reopened round closes APPROVED on 60.00 and 66.67.

        The revision branch itself increments ``current_round`` by 1, and opening the reopened
        round increments it again, so the second close sits at ``current_round`` 3.

        Design: Difficulty/non_linear_state_machine/proposal_vote_forks_to_revision_requested_then_loops_back_and_approves
        """
        chain = _committee_with_a_drafted_proposal(api)
        proposal_id = chain["proposal_id"]

        validate_success(api.open_vote(proposal_id, CHAIR), 200)
        f.cast_ballots(api, proposal_id, ["APPROVE", "APPROVE"])
        first_close = validate_success(api.close_vote(proposal_id, CHAIR), 200)

        assert first_close["status"] == "REVISION_REQUESTED"
        assert_pct(first_close["turnout_pct"], "40.00", "turnout_pct")
        assert_pct(first_close["approval_pct"], "100.00", "approval_pct")

        _revise_and_reopen(api, proposal_id)
        revised = f.read_proposal(api, proposal_id)
        assert revised["status"] == "DRAFT"
        assert_money(revised["requested_amount_cents"], 400000, "requested_amount_cents")

        validate_success(api.open_vote(proposal_id, CHAIR), 200)
        f.cast_ballots(api, proposal_id, ["APPROVE", "APPROVE", "REJECT"])
        second_close = validate_success(api.close_vote(proposal_id, CHAIR), 200)

        assert second_close["current_round"] == 3
        assert_pct(second_close["turnout_pct"], "60.00", "turnout_pct")
        assert_pct(second_close["approval_pct"], "66.67", "approval_pct")
        assert second_close["status"] == "APPROVED"

    def test_round_two_is_tallied_from_round_two_ballots_only(self, api, clock):
        """All five ballots are kept — two stamped with the first round's number and three with
        the reopened round's — and the approved 400000 cents is what the fund commits.

        The revision branch increments ``current_round`` and reopening increments it again, so
        the reopened round's ballots carry ``round_number`` 3 while round 2 never received one.

        Design: Difficulty/non_linear_state_machine/proposal_vote_forks_to_revision_requested_then_loops_back_and_approves
        """
        chain = _committee_with_a_drafted_proposal(api)
        proposal_id = chain["proposal_id"]

        validate_success(api.open_vote(proposal_id, CHAIR), 200)
        f.cast_ballots(api, proposal_id, ["APPROVE", "APPROVE"])
        validate_success(api.close_vote(proposal_id, CHAIR), 200)
        _revise_and_reopen(api, proposal_id)
        validate_success(api.open_vote(proposal_id, CHAIR), 200)
        f.cast_ballots(api, proposal_id, ["APPROVE", "APPROVE", "REJECT"])
        validate_success(api.close_vote(proposal_id, CHAIR), 200)

        ballots, _ = validate_paginated(api.list_proposal_votes(proposal_id, CHAIR))
        assert len(ballots) == 5, f"expected 5 recorded ballots, got {len(ballots)}"
        rounds = [ballot["round_number"] for ballot in ballots]
        assert rounds.count(1) == 2, f"expected 2 first-round ballots, got {rounds.count(1)}"
        assert rounds.count(3) == 3, f"expected 3 reopened-round ballots, got {rounds.count(3)}"
        fund = f.read_fund(api, chain["producer_id"])
        assert_fund_partition(fund, committed_cents=400000, balance_cents=800000)


def _major_finding_under_review(api):
    """A CERTIFIED producer carrying one MAJOR finding raised inside a started surveillance audit."""
    producer = f.build_certified_producer(api)
    audit = f.build_started_audit(
        api, producer["holder_id"], "2026-08-01", "2026-08-05",
        auditor_user_id=AUDITOR_1_ID, audit_type="SURVEILLANCE",
    )
    finding = f.raise_finding(
        api, audit["id"], "MAJOR", "FT-2.4.7",
        "Wage records incomplete for seasonal workers",
    )
    producer["audit_id"] = audit["id"]
    producer["finding_id"] = finding["id"]
    return producer


def _submit_cap(api, world, narrative):
    return validate_success(
        api.submit_cap(world["finding_id"], f.cap_payload(narrative), world["holder_headers"]),
        201,
    )


def _review_cap(api, world, decision, note):
    return validate_success(
        api.review_cap(world["finding_id"], f.cap_review_payload(decision, note), OFFICER), 200
    )


class TestCapRejectionLoop:
    """A rejected corrective action plan sends the finding back for another round."""

    def test_a_rejected_plan_leaves_the_finding_on_its_first_round(self, api, clock):
        """The first plan is submitted and rejected, so the finding sits at CAP_REJECTED still
        counting one round of review.

        Design: Difficulty/non_linear_state_machine/nonconformity_cap_rejection_loop_increments_round_before_closing
        """
        world = _major_finding_under_review(api)

        _submit_cap(api, world, "Payroll ledger will be reconstructed from bank transfers")
        rejected = _review_cap(api, world, "REJECT", "No evidence attached")

        assert rejected["status"] == "CAP_REJECTED"
        assert rejected["cap_round"] == 1, f"expected cap_round 1, got {rejected['cap_round']}"

    def test_the_second_plan_closes_the_finding_on_round_two(self, api, clock):
        """Resubmitting after the rejection carries the finding to CLOSED on round two, with the
        deadline and pre-insert score frozen at the values it was raised with.

        Design: Difficulty/non_linear_state_machine/nonconformity_cap_rejection_loop_increments_round_before_closing
        """
        world = _major_finding_under_review(api)

        _submit_cap(api, world, "Payroll ledger will be reconstructed from bank transfers")
        _review_cap(api, world, "REJECT", "No evidence attached")
        _submit_cap(
            api, world, "Reconstructed payroll ledger and signed worker attestations attached"
        )
        closed = _review_cap(api, world, "ACCEPT", "Evidence sufficient")

        assert closed["cap_round"] == 2, f"expected cap_round 2, got {closed['cap_round']}"
        assert closed["status"] == "CLOSED"
        assert_instant(closed["deadline_at"], "2026-09-15T00:00:00Z", "deadline_at")
        assert_score(closed["compliance_score_at_raise"], 100, "compliance_score_at_raise")

    def test_closing_the_audit_restores_the_score_and_anchors_the_next_audit(self, api, clock):
        """With its only finding closed the audit can close, the holder is back to a perfect
        score with no open majors, and the cadence anchor is set two years past the window.

        Design: Difficulty/non_linear_state_machine/nonconformity_cap_rejection_loop_increments_round_before_closing
        """
        world = _major_finding_under_review(api)

        _submit_cap(api, world, "Payroll ledger will be reconstructed from bank transfers")
        _review_cap(api, world, "REJECT", "No evidence attached")
        _submit_cap(
            api, world, "Reconstructed payroll ledger and signed worker attestations attached"
        )
        _review_cap(api, world, "ACCEPT", "Evidence sufficient")
        closed_audit = validate_success(api.close_audit(world["audit_id"], OFFICER), 200)

        assert closed_audit["open_nonconformity_count"] == 0
        assert closed_audit["status"] == "CLOSED"
        holder = f.read_holder(api, world["holder_id"])
        assert_score(holder["compliance_score"], 100)
        assert holder["open_major_count"] == 0
        assert_instant(
            holder["next_audit_due_at"], "2028-08-05T00:00:00Z", "next_audit_due_at"
        )
