"""Capital projects and majority-in-interest voting: threshold boundary,
decline-driven tally exclusion, validation order, terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopt_rates_for_year,
    cast_vote,
    create_project,
    get_project,
    get_success_data,
    open_voting,
    setup_mii_voting,
    setup_open_year,
    validate_error,
    validate_paginated,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]

TWO_SIGNATORIES = (
    [{"iata_code": "EA"}, {"iata_code": "EB"}]
)
TWO_SIGNATORY_ACTIVITY = (
    [{"iata_code": "EA", "landed_weight_kg": 600},
     {"iata_code": "EB", "landed_weight_kg": 400}]
)


class TestThresholdBoundary:
    def test_exact_threshold_approves(self, api):
        """PRD §3.4: "Approval requires both legs to pass: the number of
        distinct approving carriers multiplied by one hundred must be at least
        the threshold percent times the total number of eligible signatory
        carriers, and the approving weight multiplied by one hundred must be at
        least the threshold percent times the total eligible signatory weight.
        The boundary is inclusive on both legs — a tally landing exactly at the
        threshold approves the project, moving it from `MII_VOTING` to
        `APPROVED`."

        Design: Difficulty/boundary_precision_check/mii_threshold_exact_50pct_count_and_weight
        """
        ws, project = setup_mii_voting(
            "FY_BND2", TWO_SIGNATORIES, TWO_SIGNATORY_ACTIVITY,
            mii_threshold_pct=50, project_name="Taxiway B")

        resp = cast_vote(ws, project["id"], "EA", "APPROVE")
        validate_success(resp, 201)

        decided = get_project(project["id"])
        # E1 alone: count 1/2 = 50% >= 50% and weight 600/1000 = 60% >= 50%.
        assert decided["status"] == "APPROVED", (
            "A tally landing exactly at the threshold approves the project")

    def test_tally_fields_track_the_approving_vote(self, api):
        """PRD §3.4: "From then until the decision, the electorate and its
        weights are fixed: the eligible voters are the distinct airlines
        holding an active agreement in `SIGNATORY` standing on the fiscal year
        at the moment of tally, and each voter's weight is its snapshotted
        `mii_eligible_weight_kg`."
        PRD §3.4: "Every accepted ballot recomputes the tally and can decide
        the project on the spot."

        Design: Difficulty/boundary_precision_check/mii_threshold_exact_50pct_count_and_weight
        """
        ws, project = setup_mii_voting(
            "FY_BND3", TWO_SIGNATORIES, TWO_SIGNATORY_ACTIVITY,
            mii_threshold_pct=50, project_name="Taxiway C")

        validate_success(cast_vote(ws, project["id"], "EA", "APPROVE"), 201)

        decided = get_project(project["id"])
        assert decided["votes_for_count"] == 1
        assert decided["votes_for_weight_kg"] == 600, (
            "The approving weight is E1's snapshotted 600 kg")
        assert decided["status"] == "APPROVED"


class TestDeclineRenewalCascade:
    def _setup_voting_with_s1_approve(self, api, label):
        ws, project = setup_mii_voting(
            label,
            [{"iata_code": "SA"}, {"iata_code": "SB"}],
            [{"iata_code": "SA", "landed_weight_kg": 600},
             {"iata_code": "SB", "landed_weight_kg": 400}],
            mii_threshold_pct=60, project_name="Runway Rehab")
        validate_success(cast_vote(ws, project["id"], "SA", "APPROVE"), 201)
        # S1 alone: count 1/2 = 50% < 60%, so the project stays in MII_VOTING.
        assert get_project(project["id"])["status"] == "MII_VOTING"
        return ws, project

    def test_decline_excludes_prior_approve_ballot(self, api):
        """PRD §3.4: "When a carrier's agreement lapses or the carrier declines
        renewal — the `SIGNATORY` to `NON_SIGNATORY` moves of §3.1 — any
        `APPROVE` ballot that carrier has cast on a project still in
        `MII_VOTING` is excluded from the recomputation of both
        `votes_for_count` and `votes_for_weight_kg`."

        Design: Difficulty/transitive_cascade/airline_decline_renewal_cascade_to_mii_tally_exclusion
        """
        ws, project = self._setup_voting_with_s1_approve(api, "FY_DEC")

        resp = api.decline_renewal_agreement(ws["agreements"]["SA"]["id"],
                                             ws["airline_headers"]["SA"])
        validate_success(resp)

        after = get_project(project["id"])
        assert after["votes_for_count"] == 0, "S1's ballot is excluded"
        assert after["votes_for_weight_kg"] == 0, "S1's weight is excluded"
        assert after["status"] == "MII_VOTING", (
            "The project is still open after the exclusion")

    def test_decline_moves_signature_status_and_leaves_vote_open(self, api):
        """PRD §3.1: "Signature standing can also be lost. A carrier may
        decline renewal, moving `signature_status` from `SIGNATORY` back to
        `NON_SIGNATORY`"
        PRD §3.4: "An airline that walks away from the agreement cannot carry
        its endorsement into a decision it will not be bound by."

        Design: Difficulty/transitive_cascade/airline_decline_renewal_cascade_to_mii_tally_exclusion
        """
        ws, project = self._setup_voting_with_s1_approve(api, "FY_DEC2")

        declined = validate_success(
            api.decline_renewal_agreement(ws["agreements"]["SA"]["id"],
                                          ws["airline_headers"]["SA"]))
        assert declined["signature_status"] == "NON_SIGNATORY"

        # The surviving electorate can still be heard: S2's ballot is accepted.
        resp = cast_vote(ws, project["id"], "SB", "APPROVE")
        validate_success(resp, 201)
        after = get_project(project["id"])
        assert after["votes_for_count"] == 1
        assert after["votes_for_weight_kg"] == 400


class TestVoteValidationOrder:
    def test_vote_on_unopened_project_reports_state_not_eligibility(self, api):
        """PRD §2.8: "Only after the request is well-formed does the server ask
        whether the target resource's current state admits the requested
        transition (`ERR_INVALID_STATE`)... Endpoint-specific business rules
        rank last of all: vote eligibility (`ERR_NOT_SIGNATORY`), the
        one-ballot-per-carrier rule (`ERR_DUPLICATE_VOTE`), a project no longer
        accepting votes (`ERR_PROJECT_ALREADY_DECIDED`)..."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_mii_vote
        """
        ws = setup_open_year("FY_PVR", airline_specs=[{"iata_code": "NV"}])
        # The carrier never countersigns (stays NON_SIGNATORY) and the project
        # is never opened for voting (stays PROPOSED).
        project = create_project(ws, project_name="Terminal Expansion",
                                 cost_center="TERMINAL", budget_cents=9000000,
                                 mii_threshold_pct=50)

        resp = cast_vote(ws, project["id"], "NV", "APPROVE")
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_project(project["id"])
        assert after["votes_for_count"] == 0

    def test_non_signatory_voter_on_open_project_rejected(self, api):
        """PRD §3.4: "Eligibility is checked first: a carrier without an
        active, signatory agreement on the parent fiscal year is refused with
        `ERR_NOT_SIGNATORY`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_mii_vote
        """
        ws = setup_open_year("FY_PVR2", airline_specs=[{"iata_code": "NV"}])
        adopt_rates_for_year(ws)
        project = create_project(ws, project_name="Apron", budget_cents=1000,
                                 mii_threshold_pct=50)
        open_voting(project["id"])

        resp = cast_vote(ws, project["id"], "NV", "APPROVE")
        validate_error(resp, ApiErrorId.ERR_NOT_SIGNATORY)


class TestTerminalLockdownAndDuplicate:
    def test_votes_after_auto_approval_rejected(self, api):
        """PRD §3.4: "Either automatic decision seals the ballot box, so
        subsequent ballots draw `ERR_PROJECT_ALREADY_DECIDED` per the ordering
        above."

        Design: Corner/state_machines/capital_project_terminal_lockdown
        """
        ws, project = setup_mii_voting(
            "FY_TL",
            [{"iata_code": "TA"}, {"iata_code": "TB"}],
            [{"iata_code": "TA", "landed_weight_kg": 600},
             {"iata_code": "TB", "landed_weight_kg": 400}],
            mii_threshold_pct=50, project_name="Runway A")
        validate_success(cast_vote(ws, project["id"], "TA", "APPROVE"), 201)
        assert get_project(project["id"])["status"] == "APPROVED"

        resp = cast_vote(ws, project["id"], "TB", "APPROVE")
        validate_error(resp, ApiErrorId.ERR_PROJECT_ALREADY_DECIDED)

    def test_second_ballot_from_same_carrier_rejected(self, api):
        """PRD §3.4: "Uniqueness is checked second: a carrier that has already
        voted on this project — at most one vote per carrier per project — is
        refused with `ERR_DUPLICATE_VOTE`."
        PRD §3.4: "The ordering matters — a repeat ballot on an already-decided
        project reports the duplicate, not the closed project."

        Design: Corner/state_machines/duplicate_vote_rejected
        """
        ws, project = setup_mii_voting(
            "FY_DP",
            [{"iata_code": "DP"}],
            [{"iata_code": "DP", "landed_weight_kg": 100}],
            mii_threshold_pct=75, project_name="Apron")
        validate_success(cast_vote(ws, project["id"], "DP", "APPROVE"), 201)

        resp = cast_vote(ws, project["id"], "DP", "REJECT")
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE)

    def test_votes_reverse_reachable_from_project(self, api):
        """PRD §4 endpoint table: "List the votes on a project"
        (GET /airport/capital_projects/{id}/mii_votes).
        PRD §3.4: "A carrier user casts a ballot by submitting its `airline_id`
        and a `ballot` of `APPROVE` or `REJECT`; the vote is stamped with
        `cast_at` and carries its `capital_project_id` back-reference."

        Design: Corner/endpoints/reverse_reachability_mii_votes_by_project
        """
        ws, project = setup_mii_voting(
            "FY_MV",
            [{"iata_code": "MV"}],
            [{"iata_code": "MV", "landed_weight_kg": 100}],
            mii_threshold_pct=90, project_name="Taxiway")
        validate_success(cast_vote(ws, project["id"], "MV", "APPROVE"), 201)

        data, meta = validate_paginated(api.list_mii_votes(project["id"],
                                                           FINANCE))
        assert len(data) == 1
        assert data[0]["airline_id"] == ws["airlines"]["MV"]["id"]
        assert data[0]["capital_project_id"] == project["id"]
