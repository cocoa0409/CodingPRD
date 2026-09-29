"""Special assessment proposals: voting bases, the inclusive quorum and
adoption boundaries, the lien-driven ballot void, and weight conservation."""
from test_helpers import (
    ApiErrorId,
    create_ballot_payload,
    create_delinquency_action_payload,
    make_clerk_headers,
    make_member_owner_headers,
    make_treasurer_headers,
    payment_payload,
    read_ballot,
    read_proposal,
    revoke_ballot_payload,
    set_clock,
    setup_annual_assessment,
    setup_proposal,
    open_balloting,
    validate_error,
    validate_paginated,
    validate_success,
)

SEGMENT_2400 = {
    "name": "Pine Hollow Road",
    "length_feet": 2400,
    "width_feet": 22,
    "max_grade_pct": 9,
    "surface_type": "GRAVEL",
    "turnout_count": 2,
    "culvert_count": 3,
    "turnaround_present": True,
    "bridge_present": False,
}
PINE_HOLLOW = {
    "name": "Pine Hollow Road Association",
    "reserve_target_cents": 1_000_000,
    "default_voting_basis": "PER_PARCEL",
    "delinquency_interest_basis": "STATUTORY",
    "quorum_bps": 5000,
}
THREE_PARCELS = [
    {
        "deed_book_page": "DB120-P41",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    },
    {
        "deed_book_page": "DB120-P42",
        "frontage_feet": 400,
        "usage_class": "SEASONAL",
        "trips_per_day": 3,
    },
    {
        "deed_book_page": "DB120-P43",
        "frontage_feet": 250,
        "usage_class": "AGRICULTURAL",
        "trips_per_day": 6,
    },
]
FOUR_PARCELS = [
    {
        "deed_book_page": "DB130-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    },
    {
        "deed_book_page": "DB130-P02",
        "frontage_feet": 400,
        "usage_class": "SEASONAL",
        "trips_per_day": 3,
    },
    {
        "deed_book_page": "DB130-P03",
        "frontage_feet": 250,
        "usage_class": "AGRICULTURAL",
        "trips_per_day": 6,
    },
    {
        "deed_book_page": "DB130-P04",
        "frontage_feet": 300,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
    },
]
SINGLE_PARCEL = [THREE_PARCELS[0]]

TREASURER = make_treasurer_headers()
FIRST_TREASURER = make_treasurer_headers("bt-user-1")
SECOND_TREASURER = make_treasurer_headers("bt-user-2")


def _levied_fy2027(parcel_specs, budget_requirement_cents, association_overrides=None,
                   segment_overrides=None):
    set_clock("2026-10-01T00:00:00Z")
    overrides = dict(PINE_HOLLOW)
    overrides.update(association_overrides or {})
    return setup_annual_assessment(
        parcel_specs=parcel_specs,
        fiscal_year=2027,
        fy_start_date="2026-10-01",
        fy_end_date="2027-09-30",
        budget_requirement_cents=budget_requirement_cents,
        method_variant="FRONTAGE_WEIGHTED",
        association_overrides=overrides,
        segment_overrides=segment_overrides or SEGMENT_2400,
    )


def _cast(api, proposal_id, member, choice):
    """Cast against a freshly read proposal version, since every cast bumps it."""
    version = read_proposal(proposal_id)["version"]
    return validate_success(
        api.create_ballot(
            create_ballot_payload(proposal_id, member["id"], choice, version),
            make_member_owner_headers(member["id"]),
        ),
        201,
    )


def _proposal_charges(api, proposal_id):
    charges, _ = validate_paginated(
        api.list_assessment_charges(
            make_clerk_headers(), params={"proposal_id": proposal_id, "limit": 100}
        )
    )
    return charges


class TestVotingBasisDecidesTheOutcome:
    """The same two ballots adopt one proposal and reject its twin."""

    def _two_proposals(self):
        scenario = _levied_fy2027(THREE_PARCELS, 4_000_000)
        scenario["pa"] = open_balloting(
            setup_proposal(
                scenario,
                project_type="GRADING",
                title="Regrade the hollow",
                estimated_cost_cents=1_500_000,
                cost_allocation_method="EQUAL_SHARE",
                voting_basis="PER_PARCEL",
            )["id"],
            "2026-10-15T00:00:00Z",
        )
        scenario["pb"] = open_balloting(
            setup_proposal(
                scenario,
                project_type="GRADING",
                title="Regrade the hollow, assessed-share vote",
                estimated_cost_cents=1_500_000,
                cost_allocation_method="EQUAL_SHARE",
                voting_basis="ASSESSED_SHARE",
            )["id"],
            "2026-10-15T00:00:00Z",
        )
        return scenario

    def test_per_parcel_weighs_every_deeded_membership_at_one(self, api):
        """PRD §3.5: "Under `PER_PARCEL` the weight is one — one vote per deeded
        membership regardless of assessment size, so small parcels carry the same
        weight as large ones."
        PRD §3.5: "When `quorum_met` is true and `yes_weight_total` multiplied by
        ten thousand is at least `counted_weight_total` multiplied by
        `required_threshold_bps`, the proposal moves `BALLOTING → ADOPTED`."

        Design: Difficulty/dual_variant_calc/proposal_voting_basis_per_parcel_adopts_assessed_share_rejects
        """
        scenario = self._two_proposals()
        m1, m2, _m3 = scenario["members"]
        pa = scenario["pa"]

        assert pa["eligible_weight_total"] == 3
        assert pa["required_threshold_bps"] == 5000

        yes = _cast(api, pa["id"], m2, "YES")
        no = _cast(api, pa["id"], m1, "NO")
        assert yes["weight_snapshot"] == 1
        assert no["weight_snapshot"] == 1

        set_clock("2026-10-15T00:00:00Z")
        tallied = validate_success(api.tally_proposal(pa["id"], TREASURER))

        assert tallied["status"] == "ADOPTED"
        assert tallied["counted_weight_total"] == 2
        assert tallied["yes_weight_total"] == 1
        assert tallied["quorum_met"] is True
        assert tallied["approved_amount_cents"] == 1_500_000

        charges = _proposal_charges(api, pa["id"])
        assert len(charges) == 3
        assert all(c["amount_cents"] == 500_000 for c in charges)
        assert all(c["charge_type"] == "SPECIAL" for c in charges)

    def test_assessed_share_weighs_the_newest_certified_annual_charge(self, api):
        """PRD §3.5: "Under `ASSESSED_SHARE` the weight is derived from the member's
        newest certified annual charge: take that member's charges whose
        `charge_type` is `ANNUAL` and whose `status` is anything other than
        `VOIDED`, and whose roll's `status` is `CERTIFIED` or `LEVIED`; rank them by
        the roll's `fiscal_year` descending and then by the charge's `created_at`
        descending; the first row wins, and the weight is that charge's
        `amount_cents` divided by one hundred with any fraction discarded downward,
        that is, the assessment in whole dollars."
        PRD §3.5: "The same ballots can therefore adopt a proposal under
        `PER_PARCEL` and fail it under `ASSESSED_SHARE`, when the yes voters happen
        to be the lightly assessed ones."

        Design: Difficulty/dual_variant_calc/proposal_voting_basis_per_parcel_adopts_assessed_share_rejects
        """
        scenario = self._two_proposals()
        m1, m2, _m3 = scenario["members"]
        pb = scenario["pb"]

        assert pb["eligible_weight_total"] == 39998, "15890 + 13150 + 10958"
        assert pb["required_threshold_bps"] == 5000

        yes = _cast(api, pb["id"], m2, "YES")
        no = _cast(api, pb["id"], m1, "NO")
        assert yes["weight_snapshot"] == 13150
        assert no["weight_snapshot"] == 15890

        set_clock("2026-10-15T00:00:00Z")
        tallied = validate_success(api.tally_proposal(pb["id"], TREASURER))

        assert tallied["status"] == "REJECTED"
        assert tallied["counted_weight_total"] == 29040
        assert tallied["yes_weight_total"] == 13150
        assert tallied["quorum_met"] is True
        assert tallied["approved_amount_cents"] == 0
        assert _proposal_charges(api, pb["id"]) == []

    def test_a_rejected_proposal_keeps_its_ballots_as_the_record(self, api):
        """PRD §3.5: "No charges are created, `approved_amount_cents` stays zero, and
        every `CAST` ballot stays `CAST` as the historical record of the vote."

        Design: Difficulty/dual_variant_calc/proposal_voting_basis_per_parcel_adopts_assessed_share_rejects
        """
        scenario = self._two_proposals()
        m1, m2, _m3 = scenario["members"]
        pb = scenario["pb"]
        yes = _cast(api, pb["id"], m2, "YES")
        no = _cast(api, pb["id"], m1, "NO")

        set_clock("2026-10-15T00:00:00Z")
        validate_success(api.tally_proposal(pb["id"], TREASURER))

        assert read_ballot(yes["id"])["status"] == "CAST"
        assert read_ballot(no["id"])["status"] == "CAST"
        assert read_ballot(yes["id"])["weight_snapshot"] == 13150


class TestQuorumAndAdoptionBoundaries:
    """Cross-multiplied integers, inclusive on both sides."""

    def _quorum_four(self, api):
        scenario = _levied_fy2027(
            FOUR_PARCELS,
            4_120_000,
            association_overrides={"name": "Cedar Ridge Road Association"},
            segment_overrides=dict(SEGMENT_2400, name="Cedar Ridge Road"),
        )
        scenario["pa"] = open_balloting(
            setup_proposal(
                scenario,
                project_type="GRADING",
                title="Ditch and regrade",
                estimated_cost_cents=1_500_000,
                cost_allocation_method="EQUAL_SHARE",
                voting_basis="PER_PARCEL",
            )["id"],
            "2026-11-01T00:00:00Z",
        )
        scenario["pb"] = open_balloting(
            setup_proposal(
                scenario,
                project_type="PAVING",
                title="Pave the first quarter mile",
                estimated_cost_cents=1_500_000,
                cost_allocation_method="EQUAL_SHARE",
                voting_basis="PER_PARCEL",
            )["id"],
            "2026-11-01T00:00:00Z",
        )
        return scenario

    def test_quorum_and_adoption_are_both_satisfied_at_exact_equality(self, api):
        """PRD §3.5: "`quorum_met` is recomputed on every ballot mutation and is
        true exactly when `counted_weight_total` multiplied by ten thousand is at
        least `eligible_weight_total` multiplied by the association's `quorum_bps`."
        PRD §3.5: "When `quorum_met` is true and `yes_weight_total` multiplied by ten
        thousand is at least `counted_weight_total` multiplied by
        `required_threshold_bps`, the proposal moves `BALLOTING → ADOPTED`."

        Design: Difficulty/boundary_precision_check/quorum_and_adoption_exact_equality_adopt_while_one_bp_short_rejects
        """
        scenario = self._quorum_four(api)
        m1, m2 = scenario["members"][0], scenario["members"][1]
        pa = scenario["pa"]

        assert scenario["roll"]["total_share_units"] == 1030
        assert scenario["roll"]["total_levied_cents"] == 4_120_000
        assert scenario["roll"]["unallocated_residual_cents"] == 0
        assert scenario["roll"]["reserve_contribution_cents"] == 618_000
        assert pa["eligible_weight_total"] == 4
        assert pa["required_threshold_bps"] == 5000

        _cast(api, pa["id"], m1, "YES")
        _cast(api, pa["id"], m2, "NO")

        set_clock("2026-11-02T00:00:00Z")
        tallied = validate_success(api.tally_proposal(pa["id"], TREASURER))

        assert tallied["counted_weight_total"] == 2
        assert tallied["yes_weight_total"] == 1
        assert tallied["no_weight_total"] == 1
        assert tallied["quorum_met"] is True, "2 * 10000 == 4 * 5000 clears the quorum"
        assert tallied["status"] == "ADOPTED", "1 * 10000 == 2 * 5000 clears adoption"
        assert tallied["approved_amount_cents"] == 1_500_000

    def test_the_paving_threshold_rejects_two_of_three_by_one_basis_point(self, api):
        """PRD §3.5: "The `PAVING` base is deliberately six thousand six hundred and
        sixty-seven rather than a clean two-thirds, which means that two of three
        equal votes falls just short of the bar rather than just clearing it."
        PRD §3.5: "The proposal moves `BALLOTING → REJECTED` in either of two
        situations: `quorum_met` is true but `yes_weight_total` multiplied by ten
        thousand falls short of `counted_weight_total` multiplied by
        `required_threshold_bps`"

        Design: Difficulty/boundary_precision_check/quorum_and_adoption_exact_equality_adopt_while_one_bp_short_rejects
        """
        scenario = self._quorum_four(api)
        m1, m2, m3 = scenario["members"][0], scenario["members"][1], scenario["members"][2]
        pb = scenario["pb"]

        assert pb["eligible_weight_total"] == 4
        assert pb["required_threshold_bps"] == 6667

        _cast(api, pb["id"], m1, "YES")
        _cast(api, pb["id"], m2, "YES")
        _cast(api, pb["id"], m3, "NO")

        set_clock("2026-11-02T00:00:00Z")
        tallied = validate_success(api.tally_proposal(pb["id"], TREASURER))

        assert tallied["counted_weight_total"] == 3
        assert tallied["yes_weight_total"] == 2
        assert tallied["quorum_met"] is True, "3 * 10000 >= 4 * 5000"
        assert tallied["status"] == "REJECTED", "2 * 10000 == 20000 < 3 * 6667 == 20001"
        assert tallied["approved_amount_cents"] == 0
        assert _proposal_charges(api, pb["id"]) == []

    def test_adoption_spreads_the_estimate_equally_over_the_four_parcels(self, api):
        """PRD §3.5: "each parcel's share unit is chosen by the proposal's
        `cost_allocation_method` — its `frontage_share_units` under
        `FRONTAGE_WEIGHTED`, its `trip_share_units` under
        `TRIP_GENERATION_WEIGHTED`, or a flat one under `EQUAL_SHARE`."
        PRD §3.5: "One charge is created per assessable parcel with `charge_type`
        `SPECIAL`, `proposal_id` set to this proposal, `status` `OPEN`, a `due_date`
        of the current clock date plus forty-five days, and `roll_id` set to the
        association's latest levied roll."

        Design: Difficulty/boundary_precision_check/quorum_and_adoption_exact_equality_adopt_while_one_bp_short_rejects
        """
        scenario = self._quorum_four(api)
        m1, m2 = scenario["members"][0], scenario["members"][1]
        pa = scenario["pa"]
        _cast(api, pa["id"], m1, "YES")
        _cast(api, pa["id"], m2, "NO")

        set_clock("2026-11-02T00:00:00Z")
        validate_success(api.tally_proposal(pa["id"], TREASURER))

        charges = _proposal_charges(api, pa["id"])
        assert len(charges) == 4
        for charge in charges:
            assert charge["amount_cents"] == 375_000
            assert charge["charge_type"] == "SPECIAL"
            assert charge["status"] == "OPEN"
            assert charge["due_date"] == "2026-12-17"
            assert charge["roll_id"] == scenario["roll"]["id"]


class TestLienVoidsABallotThreeHopsAway:
    """Effectuating a lien reaches a proposal the payload never names."""

    def _balloting_with_one_vote(self, api):
        scenario = _levied_fy2027(SINGLE_PARCEL, 4_000_000)
        proposal = setup_proposal(
            scenario,
            project_type="GRADING",
            title="Winter regrade",
            estimated_cost_cents=1_500_000,
            cost_allocation_method="EQUAL_SHARE",
            voting_basis="PER_PARCEL",
        )
        scenario["proposal"] = open_balloting(proposal["id"], "2027-01-05T00:00:00Z")
        scenario["ballot"] = _cast(
            api, scenario["proposal"]["id"], scenario["members"][0], "YES"
        )
        scenario["charge"] = scenario["charges"][0]
        set_clock("2026-12-15T00:00:00Z")
        scenario["lien"] = validate_success(
            api.create_delinquency_action(
                scenario["charge"]["id"],
                create_delinquency_action_payload("LIEN_FILING"),
                FIRST_TREASURER,
            ),
            201,
        )
        return scenario

    def test_the_lien_voids_the_ballot_of_the_newly_encumbered_member(self, api):
        """PRD §3.6: "Fourth, because the member's `standing_status` became
        `LIEN_FILED`, every ballot of that member whose `status` is `CAST` on a
        proposal whose `status` is `BALLOTING` moves `CAST → VOIDED`, and each
        affected proposal has its `counted_weight_total`, its choice totals, and its
        `quorum_met` recomputed — which bumps that proposal's `version` and is
        precisely the situation the ballot version check in §2.9 exists to surface."

        Design: Difficulty/transitive_cascade/lien_effectuation_cascades_to_a_balloting_proposal_tally
        """
        scenario = self._balloting_with_one_vote(api)
        before = read_proposal(scenario["proposal"]["id"])
        assert before["eligible_weight_total"] == 1
        assert before["counted_weight_total"] == 1
        assert before["yes_weight_total"] == 1
        assert before["quorum_met"] is True

        effective = validate_success(
            api.effectuate_delinquency_action(scenario["lien"]["id"], SECOND_TREASURER)
        )
        assert effective["status"] == "EFFECTIVE"
        assert effective["effectuated_by_user_id"] == "bt-user-2"
        assert effective["lien_amount_cents"] == 1_600_000
        assert effective["payoff_amount_cents"] == 1_615_781

        ballot = read_ballot(scenario["ballot"]["id"])
        assert ballot["status"] == "VOIDED"
        assert ballot["weight_snapshot"] == 1, "the snapshot survives as the record"

    def test_the_void_recomputes_the_totals_and_bumps_the_proposal_version(self, api):
        """PRD §2.8: "The general shape of a cascade in this system is that a single
        client request may mutate three or four rows. Each such secondary mutation
        refreshes that row's `updated_at` and increments its `version`, exactly as a
        direct write would."
        PRD §3.5: "the proposal's `counted_weight_total` and choice totals are
        recomputed from `CAST` ballots only. The proposal's `quorum_met` is
        recomputed and its `version` increments by one."

        Design: Difficulty/transitive_cascade/lien_effectuation_cascades_to_a_balloting_proposal_tally
        """
        scenario = self._balloting_with_one_vote(api)
        before = read_proposal(scenario["proposal"]["id"])

        validate_success(
            api.effectuate_delinquency_action(scenario["lien"]["id"], SECOND_TREASURER)
        )

        after = read_proposal(scenario["proposal"]["id"])
        assert after["counted_weight_total"] == 0
        assert after["yes_weight_total"] == 0
        assert after["quorum_met"] is False
        assert after["eligible_weight_total"] == 1, "the snapshot does not move"
        assert after["version"] > before["version"]
        assert after["status"] == "BALLOTING", "voiding a ballot does not close the round"


class TestBallotErrorPrecedence:
    """A proposal-state error and a member-standing error firing at once."""

    def _draft_again_with_delinquent_voter(self, api):
        scenario = _levied_fy2027(SINGLE_PARCEL, 4_000_000)
        proposal = setup_proposal(
            scenario,
            project_type="GRADING",
            title="Autumn regrade",
            estimated_cost_cents=1_500_000,
            cost_allocation_method="EQUAL_SHARE",
            voting_basis="PER_PARCEL",
        )
        scenario["proposal"] = open_balloting(proposal["id"], "2026-10-05T00:00:00Z")

        set_clock("2026-10-06T00:00:00Z")
        scenario["tallied"] = validate_success(api.tally_proposal(proposal["id"], TREASURER))

        set_clock("2026-12-15T00:00:00Z")
        validate_success(
            api.create_delinquency_action(
                scenario["charges"][0]["id"],
                create_delinquency_action_payload("NOTICE"),
                FIRST_TREASURER,
            ),
            201,
        )
        return scenario

    def test_a_failed_quorum_returns_the_round_to_draft(self, api):
        """PRD §3.5: "When `quorum_met` is false and `failed_tally_count` is still
        below two, the proposal moves `BALLOTING → DRAFT`. Its `failed_tally_count`
        increases by one; every `CAST` ballot of the proposal moves `CAST → VOIDED`;
        `counted_weight_total`, `yes_weight_total`, `no_weight_total`, and
        `abstain_weight_total` all reset to zero and `quorum_met` returns to false;
        and both `balloting_opened_at` and `balloting_closes_at` reset to null so
        that a fresh round must be explicitly opened."

        Design: Difficulty/priority_pair_validation_conflict/ballot_proposal_state_error_outranks_member_standing_error
        """
        scenario = self._draft_again_with_delinquent_voter(api)
        tallied = scenario["tallied"]

        assert tallied["status"] == "DRAFT"
        assert tallied["failed_tally_count"] == 1
        assert tallied["counted_weight_total"] == 0
        assert tallied["balloting_closes_at"] is None

    def test_the_proposal_state_error_masks_the_member_standing_error(self, api):
        """PRD §2.10: "More generally, every request walks the following checks in
        this exact order, and the first failure is the error returned. Where several
        checks could all fire, the earlier one masks the later ones."
        PRD §3.5: "The proposal must be `BALLOTING`, the logical clock must still be
        strictly before `balloting_closes_at` — a cast at or after the closing
        instant is rejected with `ERR_BALLOTING_CLOSED` — the `member_id` must equal
        `X-User-ID`, the member's `standing_status` must be `GOOD_STANDING`
        (otherwise `ERR_MEMBER_NOT_IN_GOOD_STANDING`), and the member's parcel must
        have `covenant_recorded` true (otherwise `ERR_COVENANT_NOT_RECORDED`)."

        Design: Difficulty/priority_pair_validation_conflict/ballot_proposal_state_error_outranks_member_standing_error
        """
        scenario = self._draft_again_with_delinquent_voter(api)
        member = scenario["members"][0]
        proposal = read_proposal(scenario["proposal"]["id"])

        validate_error(
            api.create_ballot(
                create_ballot_payload(
                    proposal["id"], member["id"], "YES", proposal["version"]
                ),
                make_member_owner_headers(member["id"]),
            ),
            ApiErrorId.ERR_PROPOSAL_NOT_BALLOTING.value,
        )

        assert read_proposal(proposal["id"])["counted_weight_total"] == 0

    def test_reopening_the_round_surfaces_the_masked_standing_error(self, api):
        """PRD §2.10 item 51, which sits after item 19 in the order: "The voting
        member's `standing_status` is `GOOD_STANDING` — otherwise
        `ERR_MEMBER_NOT_IN_GOOD_STANDING` (409)."
        PRD §3.5: "the member's `standing_status` must be `GOOD_STANDING` (otherwise
        `ERR_MEMBER_NOT_IN_GOOD_STANDING`), and the member's parcel must have
        `covenant_recorded` true (otherwise `ERR_COVENANT_NOT_RECORDED`)."

        Design: Difficulty/priority_pair_validation_conflict/ballot_proposal_state_error_outranks_member_standing_error
        """
        scenario = self._draft_again_with_delinquent_voter(api)
        member = scenario["members"][0]

        reopened = open_balloting(scenario["proposal"]["id"], "2027-01-05T00:00:00Z")
        assert reopened["status"] == "BALLOTING"
        assert reopened["eligible_weight_total"] == 1, (
            "a DELINQUENT member is still in the eligible snapshot"
        )

        validate_error(
            api.create_ballot(
                create_ballot_payload(
                    reopened["id"], member["id"], "YES", reopened["version"]
                ),
                make_member_owner_headers(member["id"]),
            ),
            ApiErrorId.ERR_MEMBER_NOT_IN_GOOD_STANDING.value,
        )

        after = read_proposal(reopened["id"])
        assert after["counted_weight_total"] == 0
        assert after["quorum_met"] is False


class TestCountedWeightConservation:
    """counted_weight_total always equals the CAST ballots' weight."""

    def _open_round(self, api):
        scenario = _levied_fy2027(THREE_PARCELS, 4_000_000)
        proposal = setup_proposal(
            scenario,
            project_type="GRADING",
            title="Full-length regrade",
            estimated_cost_cents=1_500_000,
            cost_allocation_method="EQUAL_SHARE",
            voting_basis="PER_PARCEL",
        )
        scenario["proposal"] = open_balloting(proposal["id"], "2027-01-05T00:00:00Z")
        return scenario

    def _assert_totals_reconcile(self, proposal):
        assert (
            proposal["yes_weight_total"]
            + proposal["no_weight_total"]
            + proposal["abstain_weight_total"]
            == proposal["counted_weight_total"]
        )

    def test_revoking_and_recasting_conserve_the_counted_weight(self, api):
        """PRD §3.5: "On revocation the proposal's `counted_weight_total` falls by
        that ballot's `weight_snapshot`, the matching choice total falls by the same
        amount, `quorum_met` is recomputed, and the proposal's `version` increments
        by one."
        PRD §3.5: "Recasting is legal: any prior `CAST` ballot by the same member on
        the same proposal moves `CAST → SUPERSEDED`, and the proposal's
        `counted_weight_total` and choice totals are recomputed from `CAST` ballots
        only."

        Design: Difficulty/compensating_invariant/counted_voting_weight_conserved_across_revoke_recast_and_lien_void
        """
        scenario = self._open_round(api)
        m1, m2, _m3 = scenario["members"]
        proposal_id = scenario["proposal"]["id"]

        b1 = _cast(api, proposal_id, m1, "YES")
        first = read_proposal(proposal_id)
        assert (first["counted_weight_total"], first["yes_weight_total"]) == (1, 1)
        assert first["quorum_met"] is False, "1 * 10000 < 3 * 5000"
        self._assert_totals_reconcile(first)

        _cast(api, proposal_id, m2, "NO")
        second = read_proposal(proposal_id)
        assert (second["counted_weight_total"], second["no_weight_total"]) == (2, 1)
        assert second["quorum_met"] is True
        self._assert_totals_reconcile(second)

        validate_success(
            api.revoke_ballot(
                b1["id"],
                revoke_ballot_payload(second["version"]),
                make_member_owner_headers(m1["id"]),
            )
        )
        third = read_proposal(proposal_id)
        assert third["counted_weight_total"] == 1
        assert third["yes_weight_total"] == 0
        assert third["quorum_met"] is False
        assert read_ballot(b1["id"])["status"] == "REVOKED"
        assert read_ballot(b1["id"])["weight_snapshot"] == 1
        self._assert_totals_reconcile(third)

        _cast(api, proposal_id, m1, "YES")
        fourth = read_proposal(proposal_id)
        assert fourth["counted_weight_total"] == 2
        assert fourth["yes_weight_total"] == 1
        assert fourth["quorum_met"] is True
        assert read_ballot(b1["id"])["status"] == "REVOKED", "a revocation is terminal"
        self._assert_totals_reconcile(fourth)

    def test_a_voided_ballot_is_not_restored_when_the_lien_is_paid_off(self, api):
        """PRD §3.6: "A member sitting in `DELINQUENT` or `LIEN_FILED` returns to
        `GOOD_STANDING` exactly when, after the mutation, no charge of theirs remains
        `DELINQUENT` or `LIEN_ENCUMBERED`."
        PRD §3.5: "the proposal's `counted_weight_total` and choice totals are
        recomputed from `CAST` ballots only."

        Design: Difficulty/compensating_invariant/counted_voting_weight_conserved_across_revoke_recast_and_lien_void
        """
        scenario = self._open_round(api)
        m1, m2, _m3 = scenario["members"]
        proposal_id = scenario["proposal"]["id"]
        m2_charge = [c for c in scenario["charges"] if c["member_id"] == m2["id"]][0]
        assert m2_charge["amount_cents"] == 1_315_068

        _cast(api, proposal_id, m1, "YES")
        b2 = _cast(api, proposal_id, m2, "NO")

        set_clock("2026-12-15T00:00:00Z")
        lien = validate_success(
            api.create_delinquency_action(
                m2_charge["id"], create_delinquency_action_payload("LIEN_FILING"),
                FIRST_TREASURER,
            ),
            201,
        )
        validate_success(api.effectuate_delinquency_action(lien["id"], SECOND_TREASURER))

        voided = read_proposal(proposal_id)
        assert read_ballot(b2["id"])["status"] == "VOIDED"
        assert voided["counted_weight_total"] == 1
        assert voided["yes_weight_total"] == 1
        assert voided["no_weight_total"] == 0
        assert voided["quorum_met"] is False
        self._assert_totals_reconcile(voided)

        validate_success(
            api.create_payment(m2_charge["id"], payment_payload(1_315_068), make_clerk_headers())
        )

        after = read_proposal(proposal_id)
        assert read_ballot(b2["id"])["status"] == "VOIDED", "the void is not compensated"
        assert after["counted_weight_total"] == 1
        assert after["quorum_met"] is False
        assert after["status"] == "BALLOTING"
        assert after["eligible_weight_total"] == 3
        self._assert_totals_reconcile(after)

    def test_exactly_three_ballot_rows_survive_the_whole_sequence(self, api):
        """PRD §3.5: "Ballots may be read individually, listed per proposal, or
        listed across proposals with `proposal_id`, `member_id`, and `status`
        filters."
        PRD §3.5: "The new ballot starts `CAST`, has `cast_at` stamped with the
        current logical-clock instant, and freezes its `weight_snapshot` from the
        weight computation above under the proposal's basis."

        Design: Difficulty/compensating_invariant/counted_voting_weight_conserved_across_revoke_recast_and_lien_void
        """
        scenario = self._open_round(api)
        m1, m2, _m3 = scenario["members"]
        proposal_id = scenario["proposal"]["id"]
        m2_charge = [c for c in scenario["charges"] if c["member_id"] == m2["id"]][0]

        b1 = _cast(api, proposal_id, m1, "YES")
        b2 = _cast(api, proposal_id, m2, "NO")
        validate_success(
            api.revoke_ballot(
                b1["id"],
                revoke_ballot_payload(read_proposal(proposal_id)["version"]),
                make_member_owner_headers(m1["id"]),
            )
        )
        b3 = _cast(api, proposal_id, m1, "YES")

        set_clock("2026-12-15T00:00:00Z")
        lien = validate_success(
            api.create_delinquency_action(
                m2_charge["id"], create_delinquency_action_payload("LIEN_FILING"),
                FIRST_TREASURER,
            ),
            201,
        )
        validate_success(api.effectuate_delinquency_action(lien["id"], SECOND_TREASURER))

        ballots, _meta = validate_paginated(
            api.list_proposal_ballots(proposal_id, TREASURER)
        )
        by_id = {b["id"]: b["status"] for b in ballots}
        assert len(ballots) == 3
        assert by_id[b1["id"]] == "REVOKED"
        assert by_id[b2["id"]] == "VOIDED"
        assert by_id[b3["id"]] == "CAST"

        proposal = read_proposal(proposal_id)
        assert proposal["counted_weight_total"] == 1
        assert proposal["counted_weight_total"] == sum(
            b["weight_snapshot"] for b in ballots if b["status"] == "CAST"
        )
