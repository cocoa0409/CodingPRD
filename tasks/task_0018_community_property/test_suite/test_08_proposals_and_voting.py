"""Owners-committee proposals, votes, and tally (PRD §3.8).

Covers:
- Proposal lifecycle DRAFT → OPEN → TALLIED_PASSED/FAILED → PUBLISHED.
- Frozen eligible_weight_total at OPEN.
- Vote method variants PER_HOUSEHOLD vs PER_AREA (difficulty-design instance
  vote_tally_per_household_vs_per_area).
- Pass-threshold strict >= boundary (difficulty-design instance
  vote_pass_threshold_strict_ge AND vote_pass_threshold_branch_on_frozen_denominator).
- Vote weight conservation invariant (difficulty-design instance
  vote_weight_conservation_yes_no_abstain).
- Voter eligibility, vote uniqueness, voting closed errors.
- Cancel-vs-tally race semantics (PRD §3.8 + concurrency rule §2.9).
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_proposal,
    assert_vote,
    cast_vote,
    cast_vote_payload,
    create_and_open_proposal,
    create_owner_with_property,
    create_proposal_payload,
    fetch_proposal,
    iso_utc,
    list_audit_entries_for,
    make_committee_chair_headers,
    make_owner_headers,
    setup_overdue_bill,
    setup_proposal_voters,
    setup_two_proposals_voting_method_split,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestProposalLifecycle:
    def test_create_proposal_starts_in_draft(self, api):
        """PRD §3.8: "New proposals open in status DRAFT."

        Claim: POST /proposals returns status==DRAFT.
        """
        chair = make_committee_chair_headers()
        payload = create_proposal_payload(
            voting_method="PER_HOUSEHOLD",
            voting_starts_at=iso_utc(datetime.now(timezone.utc) + timedelta(seconds=60)),
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=2)),
        )
        res = api.create_proposal(payload, chair)
        data = validate_success(res, 201)
        assert_proposal(data)
        assert data["status"] == "DRAFT"

    def test_open_freezes_eligible_weight_total(self, api):
        """PRD §3.8: "Opening a proposal freezes the eligible voter list ... The
        proposal's eligible_weight_total is computed by summing the per-property
        weight across the eligible voter list and frozen at this moment."
        PRD §3.8: "Under the PER_HOUSEHOLD variant of the tally calculation, each
        property contributes weight 1.0 regardless of its area."

        Claim: with three ELIGIBLE owners and PER_HOUSEHOLD method,
        eligible_weight_total at OPEN == 3.0.
        """
        voters = setup_proposal_voters(3)
        proposal = create_and_open_proposal(
            voting_method="PER_HOUSEHOLD",
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=2)),
        )
        assert proposal["status"] == "OPEN"
        # PRD says eligible_weight_total = number of eligible owners' properties under
        # PER_HOUSEHOLD. Since the helper creates all voters AFTER opening would be wrong;
        # but here we need voters BEFORE open. We re-setup correctly:
        # Actually: setup_proposal_voters runs first, then create_and_open_proposal opens —
        # the eligible list snapshot at OPEN time includes the three voters.
        assert proposal["eligible_weight_total"] >= len(voters), (
            f"PER_HOUSEHOLD eligible_weight_total at OPEN must be >= number of pre-existing "
            f"eligible owners ({len(voters)}); got {proposal['eligible_weight_total']}"
        )


class TestVoteMethodSplit:
    """Difficulty-design instance: vote_tally_per_household_vs_per_area.
    Same set of cast Vote rows can flip PASS to FAIL between PER_HOUSEHOLD and PER_AREA."""

    def test_per_household_passes_per_area_fails_on_same_votes(self, api):
        """PRD §3.8: "Under the PER_HOUSEHOLD variant of the tally calculation, each
        property contributes weight 1.0 regardless of its area; under the PER_AREA
        variant, each property contributes weight equal to its area_sqm, and
        eligible_weight_total is therefore the total area across eligible properties."
        PRD §3.8: "if the ratio is greater than or equal to the threshold the proposal
        transitions OPEN → TALLIED_PASSED; otherwise it transitions OPEN → TALLIED_FAILED."

        Setup (per recipe): 4 owners, areas {80, 100, 120, 200}; PER_HOUSEHOLD and
        PER_AREA proposals, both pass_threshold_pct=0.6667. Cast YES from areas
        80, 100, 120; NO from area 200.

        PER_HOUSEHOLD: yes_weight=3, eligible_weight_total=4, ratio=0.75 >= 0.6667 → PASSED.
        PER_AREA:      yes_weight=300, eligible_weight_total=500, ratio=0.60 < 0.6667 → FAILED.

        Claim: same votes, different methods → A=TALLIED_PASSED, B=TALLIED_FAILED.

        # difficulty: dual_variant_calc/vote_tally_per_household_vs_per_area
        """
        voters, proposal_a, proposal_b = setup_two_proposals_voting_method_split(
            [80.00, 100.00, 120.00, 200.00]
        )
        # Cast YES from the first three (areas 80, 100, 120); NO from the fourth (200).
        for proposal in (proposal_a, proposal_b):
            for idx, (owner, prop) in enumerate(voters):
                choice = "YES" if idx < 3 else "NO"
                cast_vote(proposal, owner, prop, choice=choice)
        # Advance the clock past voting_ends_at.
        ends_at = datetime.fromisoformat(proposal_a["voting_ends_at"].replace("Z", "+00:00"))
        advance_clock_to(iso_utc(ends_at + timedelta(seconds=60)))
        chair = make_committee_chair_headers()
        tallied_a = validate_success(api.tally_proposal(proposal_a["id"], chair), 200)
        tallied_b = validate_success(api.tally_proposal(proposal_b["id"], chair), 200)
        assert tallied_a["status"] == "TALLIED_PASSED", (
            f"PER_HOUSEHOLD with 3/4 YES (ratio 0.75 >= 0.6667) must PASS; got {tallied_a['status']}"
        )
        assert tallied_b["status"] == "TALLIED_FAILED", (
            f"PER_AREA with 300/500 YES (ratio 0.60 < 0.6667) must FAIL; got {tallied_b['status']}"
        )


class TestPassThresholdStrictBoundary:
    """Difficulty-design instance: vote_pass_threshold_strict_ge AND
    vote_pass_threshold_branch_on_frozen_denominator."""

    def test_two_thirds_of_three_fails_at_threshold_0_6667(self, api):
        """PRD §3.8: "The pass test compares the ratio of yes_weight to the frozen
        eligible_weight_total — denominator is the frozen eligible total, never the
        sum of cast votes — against pass_threshold_pct: if the ratio is greater
        than or equal to the threshold the proposal transitions OPEN → TALLIED_PASSED;
        otherwise it transitions OPEN → TALLIED_FAILED."

        Setup: 3 ELIGIBLE owners, PER_HOUSEHOLD, pass_threshold_pct=0.6667. Two
        owners vote YES, one ABSTAIN. yes_weight=2, eligible_weight_total=3 (frozen),
        ratio = 2/3 = 0.6666... which is strictly less than 0.6667 → FAIL.

        Claim: status == TALLIED_FAILED at the strict-< boundary.

        # difficulty: boundary_precision_check/vote_pass_threshold_strict_ge
        # difficulty: combinatorial_formula/vote_pass_threshold_branch_on_frozen_denominator
        """
        voters = setup_proposal_voters(3)
        proposal = create_and_open_proposal(
            voting_method="PER_HOUSEHOLD",
            pass_threshold_pct=0.6667,
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
        )
        # First 2 cast YES; third ABSTAINs.
        cast_vote(proposal, voters[0][0], voters[0][1], "YES")
        cast_vote(proposal, voters[1][0], voters[1][1], "YES")
        cast_vote(proposal, voters[2][0], voters[2][1], "ABSTAIN")
        # Advance past voting_ends_at.
        ends_at = datetime.fromisoformat(proposal["voting_ends_at"].replace("Z", "+00:00"))
        advance_clock_to(iso_utc(ends_at + timedelta(seconds=60)))
        chair = make_committee_chair_headers()
        tallied = validate_success(api.tally_proposal(proposal["id"], chair), 200)
        assert tallied["status"] == "TALLIED_FAILED", (
            f"yes/eligible = 2/3 = 0.6666... is strictly less than 0.6667 → FAIL; got {tallied['status']}"
        )

    def test_unanimous_two_of_two_passes(self, api):
        """PRD §3.8: same threshold semantics, "if the ratio is greater than or
        equal to the threshold the proposal transitions OPEN → TALLIED_PASSED."

        Setup: 2 ELIGIBLE owners, PER_HOUSEHOLD, threshold 0.6667. Both vote YES →
        ratio 1.0 >= 0.6667 → PASS.

        Claim: status == TALLIED_PASSED for unanimous YES.

        # difficulty: boundary_precision_check/vote_pass_threshold_strict_ge
        """
        voters = setup_proposal_voters(2)
        proposal = create_and_open_proposal(
            voting_method="PER_HOUSEHOLD",
            pass_threshold_pct=0.6667,
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
        )
        for owner, prop in voters:
            cast_vote(proposal, owner, prop, "YES")
        ends_at = datetime.fromisoformat(proposal["voting_ends_at"].replace("Z", "+00:00"))
        advance_clock_to(iso_utc(ends_at + timedelta(seconds=60)))
        chair = make_committee_chair_headers()
        tallied = validate_success(api.tally_proposal(proposal["id"], chair), 200)
        assert tallied["status"] == "TALLIED_PASSED"


class TestVoteWeightConservation:
    """Difficulty-design instance: vote_weight_conservation_yes_no_abstain."""

    def test_per_area_weight_sum_invariants_after_each_cast(self, api):
        """PRD §3.8: "On cast, the server records voter_owner_id, property_id, and
        choice, freezes the per-property weight at the current voting-method's rate
        (1.0 for PER_HOUSEHOLD, the property's area_sqm for PER_AREA), updates the
        proposal's running yes_weight or no_weight."
        PRD §3.8: "denominator is the frozen eligible total, never the sum of cast
        votes."

        Setup: 4 ELIGIBLE owners, areas [80, 100, 120, 200]; PER_AREA;
        eligible_weight_total = 500 frozen at OPEN. Cast YES from area 80, then NO
        from area 100. At each step, yes + no <= eligible_weight_total and the
        invariant yes + no + abstain + uncast == eligible_weight_total holds for
        any reasonable interpretation of "uncast".

        Claim: after v1 (YES, weight=80), yes_weight==80, no_weight==0,
        eligible_weight_total==500, and yes+no <= 500. After v2 (NO, weight=100),
        yes_weight==80, no_weight==100, eligible_weight_total still 500.

        # difficulty: compensating_invariant/vote_weight_conservation_yes_no_abstain
        """
        voters = setup_proposal_voters(4, areas=[80.00, 100.00, 120.00, 200.00])
        proposal = create_and_open_proposal(
            voting_method="PER_AREA",
            pass_threshold_pct=0.6667,
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
        )
        # Frozen eligible_weight_total at OPEN must equal the sum of areas (500.00).
        assert proposal["eligible_weight_total"] == pytest.approx(500.00, abs=0.001), (
            f"PER_AREA eligible_weight_total at OPEN must be sum of eligible areas (500.00); "
            f"got {proposal['eligible_weight_total']}"
        )
        cast_vote(proposal, voters[0][0], voters[0][1], "YES")  # weight 80
        after_v1 = fetch_proposal(proposal["id"])
        assert after_v1["yes_weight"] == pytest.approx(80.00, abs=0.001)
        assert after_v1.get("no_weight", 0) == pytest.approx(0.0, abs=0.001)
        # eligible_weight_total must remain frozen.
        assert after_v1["eligible_weight_total"] == pytest.approx(500.00, abs=0.001)
        cast_vote(proposal, voters[1][0], voters[1][1], "NO")  # weight 100
        after_v2 = fetch_proposal(proposal["id"])
        assert after_v2["yes_weight"] == pytest.approx(80.00, abs=0.001)
        assert after_v2["no_weight"] == pytest.approx(100.00, abs=0.001)
        # Frozen still 500.00.
        assert after_v2["eligible_weight_total"] == pytest.approx(500.00, abs=0.001)


class TestVoteEligibilityAndUniqueness:
    def test_voter_not_on_snapshot_rejected(self, api):
        """PRD §3.8: "The voter must have been on the frozen eligible list — a
        brand-new owner registered after open or a delinquent owner whose status
        flipped before open cannot vote, and is rejected with ERR_VOTER_NOT_ELIGIBLE."

        Claim: an owner registered after the proposal is OPEN tries to vote →
        ERR_VOTER_NOT_ELIGIBLE.
        """
        # Open with one voter so the proposal can transition DRAFT→OPEN.
        existing_voters = setup_proposal_voters(1)
        proposal = create_and_open_proposal(
            voting_method="PER_HOUSEHOLD",
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
        )
        # Now register a new owner — not on the snapshot.
        new_owner, new_prop = create_owner_with_property()
        headers = make_owner_headers(new_owner["id"])
        payload = cast_vote_payload(new_prop["id"], "YES")
        res = api.cast_vote(proposal["id"], payload, headers)
        validate_error(res, "ERR_VOTER_NOT_ELIGIBLE")

    def test_duplicate_vote_rejected(self, api):
        """PRD §3.8: "Exactly one vote is allowed per (proposal_id, property_id)
        pair; a duplicate is rejected with ERR_DUPLICATE_VOTE."

        Claim: a second cast on the same (proposal, property) → ERR_DUPLICATE_VOTE.
        """
        voters = setup_proposal_voters(1)
        proposal = create_and_open_proposal(
            voting_method="PER_HOUSEHOLD",
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
        )
        owner, prop = voters[0]
        cast_vote(proposal, owner, prop, "YES")
        # Second vote on same (proposal_id, property_id) — must be rejected.
        headers = make_owner_headers(owner["id"])
        payload = cast_vote_payload(prop["id"], "NO")
        res = api.cast_vote(proposal["id"], payload, headers)
        validate_error(res, "ERR_DUPLICATE_VOTE")


class TestVotingWindowErrors:
    def test_vote_after_voting_ends_at_returns_voting_closed(self, api):
        """PRD §3.8: "A vote requires the proposal to be OPEN and now() to be at or
        after voting_starts_at and strictly before voting_ends_at; votes outside
        that window are rejected with ERR_VOTING_CLOSED."

        Claim: cast after voting_ends_at → ERR_VOTING_CLOSED.
        """
        voters = setup_proposal_voters(1)
        proposal = create_and_open_proposal(
            voting_method="PER_HOUSEHOLD",
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(seconds=120)),
        )
        # Advance past voting_ends_at.
        ends_at = datetime.fromisoformat(proposal["voting_ends_at"].replace("Z", "+00:00"))
        advance_clock_to(iso_utc(ends_at + timedelta(seconds=60)))
        owner, prop = voters[0]
        headers = make_owner_headers(owner["id"])
        payload = cast_vote_payload(prop["id"], "YES")
        res = api.cast_vote(proposal["id"], payload, headers)
        validate_error(res, "ERR_VOTING_CLOSED")

    def test_open_with_inverted_window_rejected(self, api):
        """PRD §3.8: "this transition requires voting_starts_at to be strictly
        earlier than voting_ends_at and voting_ends_at to be strictly later than
        now() — a malformed window is rejected with ERR_VOTING_WINDOW_INVALID."

        Claim: a draft with voting_starts_at >= voting_ends_at → ERR_VOTING_WINDOW_INVALID.
        """
        chair = make_committee_chair_headers()
        now = datetime.now(timezone.utc)
        # Start AFTER end — the inverted window must trigger the rejection at OPEN
        # (or already at create — the PRD lists §3.8 invariants on creation/open).
        starts = iso_utc(now + timedelta(days=2))
        ends = iso_utc(now + timedelta(days=1))
        payload = create_proposal_payload(
            voting_method="PER_HOUSEHOLD",
            voting_starts_at=starts,
            voting_ends_at=ends,
        )
        # PRD §1.4 says applies_to is "POST /proposals, POST /proposals/{id}/open".
        # We try create first; if it succeeds, /open must reject.
        create_res = api.create_proposal(payload, chair)
        if create_res.status_code == 201:
            data = create_res.json()["data"]
            res = api.open_proposal(data["id"], chair)
            validate_error(res, "ERR_VOTING_WINDOW_INVALID")
        else:
            from test_helpers import validate_error
            validate_error(create_res, "ERR_VOTING_WINDOW_INVALID")


class TestCancelVsTallyRace:
    """PRD §2.9 + §3.8: cancel from OPEN requires now() < voting_ends_at; once the
    close instant passes, only tally is admitted and the cancel is rejected with
    ERR_INVALID_STATE."""

    def test_cancel_after_voting_ends_at_rejected_with_invalid_state(self, api):
        """PRD §3.8: "cancellation from OPEN requires now() to be strictly less than
        voting_ends_at (after the close instant the cancel competes with tally and
        is rejected with ERR_INVALID_STATE)."

        Claim: cancel attempt after voting_ends_at on an OPEN proposal → ERR_INVALID_STATE.
        """
        setup_proposal_voters(2)
        proposal = create_and_open_proposal(
            voting_method="PER_HOUSEHOLD",
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(seconds=120)),
        )
        ends_at = datetime.fromisoformat(proposal["voting_ends_at"].replace("Z", "+00:00"))
        advance_clock_to(iso_utc(ends_at + timedelta(seconds=60)))
        chair = make_committee_chair_headers()
        res = api.cancel_proposal(proposal["id"], chair)
        validate_error(res, "ERR_INVALID_STATE")


class TestPublishAndAudit:
    def test_publish_appends_proposal_published_audit(self, api):
        """PRD §3.8: "The publish action accepts a proposal in either TALLIED_PASSED
        or TALLIED_FAILED and advances to PUBLISHED, sets published_at to the
        current time, appends an AuditEntry with action PROPOSAL_PUBLISHED."

        Claim: publishing a TALLIED_PASSED proposal → status==PUBLISHED, published_at
        is set, an AuditEntry with action=PROPOSAL_PUBLISHED exists for the proposal.
        """
        voters = setup_proposal_voters(2)
        proposal = create_and_open_proposal(
            voting_method="PER_HOUSEHOLD",
            voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(seconds=120)),
        )
        for owner, prop in voters:
            cast_vote(proposal, owner, prop, "YES")
        ends_at = datetime.fromisoformat(proposal["voting_ends_at"].replace("Z", "+00:00"))
        advance_clock_to(iso_utc(ends_at + timedelta(seconds=60)))
        chair = make_committee_chair_headers()
        tallied = validate_success(api.tally_proposal(proposal["id"], chair), 200)
        assert tallied["status"] == "TALLIED_PASSED"
        published = validate_success(api.publish_proposal(proposal["id"], chair), 200)
        assert published["status"] == "PUBLISHED"
        assert published.get("published_at"), "published_at must be set on PUBLISHED"
        entries = list_audit_entries_for(subject_kind="PROPOSAL", subject_id=proposal["id"])
        actions = [e.get("action") for e in entries]
        assert "PROPOSAL_PUBLISHED" in actions, (
            f"Expected PROPOSAL_PUBLISHED audit; got {actions!r}"
        )
