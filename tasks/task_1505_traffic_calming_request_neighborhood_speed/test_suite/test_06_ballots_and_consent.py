"""Neighborhood consent ballots: tally arithmetic at the 60% boundary,
quorum gating, the clock-sweep cascade onto the request, post-tally vote
rejection, and the consent-denied budget release (PRD §2.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_plan,
    assert_cycle_budget_invariant,
    cast_vote,
    create_ballot,
    create_resident,
    create_segment,
    create_treatment_plan,
    create_vote_payload,
    get_ballot,
    get_funding_cycle,
    get_request,
    make_resident_headers,
    set_clock,
    setup_ballot_open,
    setup_funded,
    submit_plan_for_review,
    validate_error,
)


class TestClockSweepTallyCascade:
    def _setup(self):
        ctx = setup_ballot_open(
            name="Willow Ter",
            resident_prefix="tc2",
            requested_budget_cents=10000,
            treatment_type="SIGNAGE",
            estimated_cost_cents=5000,
            close_date="2026-08-10T00:00:00Z",
        )
        cast_vote(ctx["ballot"]["id"], ctx["residents"][0]["id"], "FOR")
        return ctx

    def test_sweep_tallies_ballot_with_consent_granted(self):
        """PRD §3.6: "Once the logical clock passes `close_date`, the tally sweep fires: the ballot moves from `OPEN` to its terminal `TALLIED` status, the three counters are computed from its vote rows, and the `outcome` is decided by integer arithmetic. Consent is granted when two conditions both hold: `votes_received` reaches `quorum_required`, and one hundred times `votes_for` is greater than or equal to sixty times `votes_received`."

        Design: Difficulty/transitive_cascade/clock_sweep_tally_to_consent_depth2
        """
        ctx = self._setup()
        set_clock("2026-08-11T00:00:00Z")
        ballot = get_ballot(ctx["ballot"]["id"])
        assert ballot["status"] == "TALLIED", (
            f"link 1: the sweep must tally the ballot, got {ballot['status']}"
        )
        assert ballot["outcome"] == "CONSENT_GRANTED"
        assert ballot["votes_received"] == 1
        assert ballot["votes_for"] == 1

    def test_tally_outcome_forks_request_to_consent_granted(self):
        """PRD §3.6: "The outcome then forks the request. On `CONSENT_GRANTED`, the request moves from `BALLOT_OPEN` to `CONSENT_GRANTED`."
        PRD §2.4: "the ballot-tally sweep closes and tallies any open ballot whose close date has passed, cascading the outcome onto the parent request (§3.6)."

        Design: Difficulty/transitive_cascade/clock_sweep_tally_to_consent_depth2
        """
        ctx = self._setup()
        set_clock("2026-08-11T00:00:00Z")
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "CONSENT_GRANTED", (
            f"link 2: the granted outcome must fork the request, "
            f"got {req['status']}"
        )


class TestBallotApprovalBoundary:
    """8 households -> petition needs 5 signatures, quorum is ceil(2.0) = 2.
    Five votes cast, exactly three FOR: 100*3 == 300 >= 60*5 == 300."""

    def _setup(self):
        ctx = setup_ballot_open(
            name="Ivy Rd",
            resident_prefix="bp2",
            household_count=8,
            close_date="2026-08-10T00:00:00Z",
        )
        ballot_id = ctx["ballot"]["id"]
        for resident, choice in zip(
            ctx["residents"], ["FOR", "FOR", "FOR", "AGAINST", "AGAINST"]
        ):
            cast_vote(ballot_id, resident["id"], choice)
        return ctx

    def test_exact_sixty_percent_grants_consent(self):
        """PRD §3.6: "The comparison is deliberately cross-multiplied in integers with no floating point, so a slate standing at exactly sixty percent in favor passes."
        PRD §3.6: "Opening snapshots the electorate: the ballot's `treatment_plan_id` is set to the request's `APPROVED` plan, `eligible_households` to the segment's `household_count` at that moment, and `quorum_required` to one quarter of the eligible households rounded up to a whole number."

        Design: Difficulty/boundary_precision_check/ballot_approval_exact_sixty_percent_grants
        """
        ctx = self._setup()
        assert ctx["ballot"]["quorum_required"] == 2, (
            f"quorum must be ceil(8 * 25%) = 2, "
            f"got {ctx['ballot']['quorum_required']}"
        )
        set_clock("2026-08-11T00:00:00Z")
        ballot = get_ballot(ctx["ballot"]["id"])
        assert ballot["votes_received"] == 5
        assert ballot["votes_for"] == 3
        assert ballot["outcome"] == "CONSENT_GRANTED", (
            f"exactly 60% in favor must pass (300 >= 300), "
            f"got {ballot['outcome']}"
        )

    def test_exact_sixty_percent_moves_request_to_consent_granted(self):
        """PRD §3.6: "The outcome then forks the request. On `CONSENT_GRANTED`, the request moves from `BALLOT_OPEN` to `CONSENT_GRANTED`."

        Design: Difficulty/boundary_precision_check/ballot_approval_exact_sixty_percent_grants
        """
        ctx = self._setup()
        set_clock("2026-08-11T00:00:00Z")
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "CONSENT_GRANTED", (
            f"request must follow the granted ballot, got {req['status']}"
        )


class TestVoteAfterTally:
    def _setup(self):
        ctx = setup_ballot_open(
            name="Juniper St", resident_prefix="ce1",
            close_date="2026-08-10T00:00:00Z",
        )
        cast_vote(ctx["ballot"]["id"], ctx["residents"][0]["id"], "FOR")
        set_clock("2026-08-11T00:00:00Z")
        return ctx

    def test_vote_rejected_once_ballot_tallied(self):
        """PRD §3.6: "The ballot must still be `OPEN` — a vote attempted after tallying is rejected with `ERR_BALLOT_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/vote_rejected_once_ballot_tallied
        """
        ctx = self._setup()
        assert get_ballot(ctx["ballot"]["id"])["status"] == "TALLIED"
        resp = api_client.cast_vote(
            ctx["ballot"]["id"],
            create_vote_payload(choice="AGAINST"),
            make_resident_headers(ctx["residents"][1]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BALLOT_INVALID_STATE)

    def test_rejected_vote_leaves_tally_counters_untouched(self):
        """PRD §3.6: "Votes are immutable once cast — there is no exclusion set — and every vote recomputes the ballot's `votes_received`, `votes_for`, and `votes_against` counters."

        Design: Difficulty/cross_entity_state_dependency/vote_rejected_once_ballot_tallied
        """
        ctx = self._setup()
        resp = api_client.cast_vote(
            ctx["ballot"]["id"],
            create_vote_payload(choice="AGAINST"),
            make_resident_headers(ctx["residents"][1]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BALLOT_INVALID_STATE)
        ballot = get_ballot(ctx["ballot"]["id"])
        assert ballot["votes_received"] == 1, (
            f"no vote row may be created after tally, "
            f"got votes_received {ballot['votes_received']}"
        )
        assert ballot["votes_for"] == 1
        assert ballot["votes_against"] == 0


class TestConsentDeniedReleasesBudget:
    """Forward/compensating pair on cycle budget cents: publication commits
    10750, plan approval re-baselines to 9675, and the CONSENT_DENIED tally
    releases the then-current allocation back to the cycle."""

    def _setup(self):
        ctx = setup_funded(
            name="Magnolia Ave",
            resident_prefix="ci1",
            requested_budget_cents=10000,
            cycle_budget_total_cents=50000,
        )
        return ctx

    def _drive_to_denied(self, ctx):
        plan = create_treatment_plan(
            ctx["request"]["id"], "SIGNAGE", 9000, "te-1"
        )
        submit_plan_for_review(plan["id"], "te-1")
        approve_plan(plan["id"], "ce-1")
        ballot = create_ballot(
            ctx["request"]["id"], "2026-08-10T00:00:00Z"
        )
        cast_vote(ballot["id"], ctx["residents"][0]["id"], "AGAINST")
        set_clock("2026-08-11T00:00:00Z")
        return ballot

    def test_publication_and_rebaseline_conserve_budget(self):
        """PRD §3.4: "Two derived balances track its consumption: `budget_committed_cents`, the sum of `allocated_cents` over every request currently `FUNDED` under the cycle, and `budget_available_cents`, which is maintained as an invariant — always the total minus the committed amount."

        Design: Difficulty/compensating_invariant/cycle_budget_conserved_across_fund_and_consent_denial
        """
        ctx = self._setup()
        req = ctx["request"]
        assert req["status"] == "FUNDED" and req["allocated_cents"] == 10750
        cycle = get_funding_cycle(ctx["cycle"]["id"])
        assert cycle["budget_committed_cents"] == 10750
        assert cycle["budget_available_cents"] == 39250
        assert_cycle_budget_invariant(cycle)

        plan = create_treatment_plan(
            ctx["request"]["id"], "SIGNAGE", 9000, "te-1"
        )
        submit_plan_for_review(plan["id"], "te-1")
        approve_plan(plan["id"], "ce-1")
        cycle = get_funding_cycle(ctx["cycle"]["id"])
        # Re-baselined to 9000 + round(675.00) = 9675 before the ballot.
        assert cycle["budget_committed_cents"] == 9675
        assert get_request(ctx["request"]["id"])["allocated_cents"] == 9675
        assert_cycle_budget_invariant(cycle)

    def test_consent_denied_releases_allocation_back_to_cycle(self):
        """PRD §3.6: "On `CONSENT_DENIED`, the request moves to the terminal `CONSENT_DENIED` stage and the provisional allocation is released back to its funding cycle as a compensating action: the cycle's `budget_committed_cents` decreases by the request's `allocated_cents`, its `budget_available_cents` increases by the same amount, and the request's `allocated_cents` is zeroed while both its `funding_cycle_id` and its `citywide_rank` are cleared back to null."

        Design: Difficulty/compensating_invariant/cycle_budget_conserved_across_fund_and_consent_denial
        """
        ctx = self._setup()
        ballot = self._drive_to_denied(ctx)

        tallied = get_ballot(ballot["id"])
        assert tallied["outcome"] == "CONSENT_DENIED"
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "CONSENT_DENIED"
        assert req["allocated_cents"] == 0
        assert req["funding_cycle_id"] is None
        assert req["citywide_rank"] is None
        cycle = get_funding_cycle(ctx["cycle"]["id"])
        assert cycle["budget_committed_cents"] == 0, (
            "the release must compensate the re-baselined allocation exactly"
        )
        assert cycle["budget_available_cents"] == 50000
        assert_cycle_budget_invariant(cycle)


class TestBallotTallyEdgeCases:
    def test_zero_votes_ballot_is_denied(self):
        """PRD §3.6: "Any other result is `CONSENT_DENIED` — and a ballot that drew zero votes is always denied, since it cannot have met quorum."

        Design: Corner/calculations/ballot_zero_votes_denied_empty_set
        """
        ctx = setup_ballot_open(
            name="Zero Ave", resident_prefix="zro",
            treatment_type="SIGNAGE", estimated_cost_cents=9000,
            close_date="2026-08-06T00:00:00Z",
        )
        set_clock("2026-08-07T00:00:00Z")
        ballot = get_ballot(ctx["ballot"]["id"])
        assert ballot["status"] == "TALLIED"
        assert ballot["votes_received"] == 0
        assert ballot["outcome"] == "CONSENT_DENIED", (
            f"an empty ballot must be denied, got {ballot['outcome']}"
        )
        assert get_request(ctx["request"]["id"])["status"] == "CONSENT_DENIED"

    def test_quorum_shortfall_denied_despite_unanimous_for(self):
        """PRD §3.6: "Consent is granted when two conditions both hold: `votes_received` reaches `quorum_required`, and one hundred times `votes_for` is greater than or equal to sixty times `votes_received`."

        Design: Corner/calculations/ballot_quorum_shortfall_denied_despite_unanimous_for
        """
        ctx = setup_ballot_open(
            name="Quorum Ave", resident_prefix="quo",
            household_count=8, close_date="2026-08-06T00:00:00Z",
        )
        assert ctx["ballot"]["quorum_required"] == 2
        cast_vote(ctx["ballot"]["id"], ctx["residents"][0]["id"], "FOR")
        set_clock("2026-08-07T00:00:00Z")
        ballot = get_ballot(ctx["ballot"]["id"])
        assert ballot["votes_received"] == 1
        assert ballot["votes_for"] == 1
        assert ballot["outcome"] == "CONSENT_DENIED", (
            f"1 of 2 quorum shortfall must deny despite 100% approval, "
            f"got {ballot['outcome']}"
        )


class TestVoteRules:
    def test_duplicate_household_vote_rejected(self):
        """PRD §3.6: "each household votes at most once per ballot: a repeat vote from the same household fails with `ERR_DUPLICATE_BALLOT_VOTE`."

        Design: Corner/validations/duplicate_ballot_vote_rejected
        """
        ctx = setup_ballot_open(name="DupVote Ave", resident_prefix="dvot")
        ballot_id = ctx["ballot"]["id"]
        resident = ctx["residents"][0]
        cast_vote(ballot_id, resident["id"], "FOR")
        resp = api_client.cast_vote(
            ballot_id,
            create_vote_payload(choice="AGAINST"),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALLOT_VOTE)
        ballot = get_ballot(ballot_id)
        assert ballot["votes_for"] == 1, (
            "the rejected repeat vote must not change tallies"
        )
        assert ballot["votes_against"] == 0

    def test_household_not_on_segment_rejected_for_votes(self):
        """PRD §3.6: "The voter's household must front the ballot's segment, or the vote is rejected with `ERR_HOUSEHOLD_NOT_ON_SEGMENT`"

        Design: Corner/validations/household_not_on_segment_rejected_for_votes
        """
        ctx = setup_ballot_open(name="Vote Seg A", resident_prefix="vsega")
        seg_b = create_segment(name="Vote Seg B", household_count=4)
        outsider = create_resident(
            seg_b["id"], "B1", "vseg-b1@example.com", "H1"
        )
        resp = api_client.cast_vote(
            ctx["ballot"]["id"],
            create_vote_payload(choice="FOR"),
            make_resident_headers(outsider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_NOT_ON_SEGMENT)
        assert get_ballot(ctx["ballot"]["id"])["votes_received"] == 0
