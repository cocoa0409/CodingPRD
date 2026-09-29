"""Void-and-restore cycles must return conserved quantities to their exact values.

The first scenario conserves the round's percentage identity across a de minimis
buyout and its reversal, with no money moving at all. The second conserves the
money identity in whole cents across two partial receipts and a full reversal,
with an orphan write-off standing in the middle of it.
"""
from test_helpers.assertions import (
    assert_ledger_figures,
    assert_percentage,
    assert_share_totals,
)
from test_helpers.fixtures import (
    add_verified_waste_in,
    adopt_round,
    cast_ballot,
    create_investigation,
    create_listed_site,
    create_participating_party,
    issue_action,
    open_balloting,
    open_round,
    post_oversight,
    read_action,
    read_ledger,
    read_party,
    read_round,
    read_site,
    record_collection,
    record_defunct,
    respond_to_action,
    set_clock,
    share_for,
    void_action,
)

DE_MINIMIS_VOID_REASON = (
    "Signature authority defect in the de minimis settlement instrument."
)
COLLECTION_VOID_REASON = (
    "Consent judgment vacated on appeal; funds returned to the payor."
)


def _halbrook_de_minimis_offer():
    """An adopted round and a live de minimis offer above the premium floor."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(
        name="Halbrook Drum Reconditioning", epa_region=4, hrs_score=40.10
    )
    prp_a = create_participating_party(
        site["id"],
        legal_name="Halbrook Drum Co",
        party_type="OWNER_OPERATOR",
        viability_score=82,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Corner Dry Cleaners LLC",
        party_type="GENERATOR",
        viability_score=15,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1971)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1988)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 PCE in shallow groundwater",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    adopt_round(allocation_round["id"], [prp_a["id"], prp_b["id"]])
    post_oversight(
        site["id"], 4_000_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-18"
    )
    action = issue_action(
        site["id"], prp_b["id"], 80_000, action_type="DE_MINIMIS_SETTLEMENT"
    )
    return site, prp_a, prp_b, allocation_round, action


class TestDeMinimisVoidRestoresTheShareIdentity:
    def test_the_adopted_round_starts_with_the_whole_hundred_in_the_allocated_bucket(self):
        """The three percentage buckets total exactly one hundred.

        PRD: "On the allocation side there is a matching identity: for an adopted round, `allocated_share_total_pct` plus `orphan_share_pct` plus `settled_share_pct` equals exactly 100.00."

        Design: Difficulty/compensating_invariant/de_minimis_void_restores_the_share_percentage_identity_to_exactly_100
        """
        _, _, _, allocation_round, action = _halbrook_de_minimis_offer()

        assert_share_totals(read_round(allocation_round["id"]), 100.00, 0.00, 0.00)
        assert action["premium_floor_cents"] == 66_528
        assert action["demanded_cents"] == 80_000

    def test_acceptance_moves_the_percentage_out_of_allocated_and_into_settled(self):
        """The buyout restructures the composition but not the total.

        PRD: "Its share in the adopted round moves `ALLOCATED → SETTLED`: the share's current `final_pct` is preserved into `pre_settlement_final_pct` and its `final_pct` is set to 0.00, and that same amount of percentage is moved out of the round's `allocated_share_total_pct` and into its `settled_share_pct`."

        Design: Difficulty/compensating_invariant/de_minimis_void_restores_the_share_percentage_identity_to_exactly_100
        """
        _, prp_a, prp_b, allocation_round, action = _halbrook_de_minimis_offer()
        respond_to_action(
            action["id"],
            prp_b["id"],
            "ACCEPT",
            "De minimis premium accepted for contribution protection.",
        )

        settled_party = read_party(prp_b["id"])
        assert settled_party["status"] == "DE_MINIMIS_SETTLED"
        assert settled_party["contribution_protection"] is True

        settled_share = share_for(allocation_round["id"], prp_b["id"])
        assert settled_share["disposition"] == "SETTLED"
        assert_percentage(settled_share["final_pct"], 0.00, "final_pct")
        assert_percentage(
            settled_share["pre_settlement_final_pct"], 0.72, "pre_settlement_final_pct"
        )

        untouched = share_for(allocation_round["id"], prp_a["id"])
        assert untouched["disposition"] == "ALLOCATED"
        assert_percentage(untouched["final_pct"], 99.28, "final_pct")

        assert_share_totals(read_round(allocation_round["id"]), 99.28, 0.00, 0.72)

    def test_voiding_restores_the_percentage_from_the_preserved_figure_without_drift(self):
        """The reversal restores the stored figure rather than recomputing.

        PRD: "Its share moves `SETTLED → ALLOCATED` with `final_pct` restored from `pre_settlement_final_pct` and `pre_settlement_final_pct` cleared, and the restored amount is moved back out of the round's `settled_share_pct` and into its `allocated_share_total_pct`."

        Design: Difficulty/compensating_invariant/de_minimis_void_restores_the_share_percentage_identity_to_exactly_100
        """
        _, _, prp_b, allocation_round, action = _halbrook_de_minimis_offer()
        respond_to_action(action["id"], prp_b["id"], "ACCEPT")
        void_action(action["id"], DE_MINIMIS_VOID_REASON)

        voided = read_action(action["id"])
        assert voided["status"] == "VOIDED"
        assert voided["received_cents"] == 0

        restored_party = read_party(prp_b["id"])
        assert restored_party["status"] == "PARTICIPATING"
        assert restored_party["contribution_protection"] is False

        restored_share = share_for(allocation_round["id"], prp_b["id"])
        assert restored_share["disposition"] == "ALLOCATED"
        assert_percentage(restored_share["final_pct"], 0.72, "final_pct")
        assert restored_share["pre_settlement_final_pct"] in (None, "")

        assert_share_totals(read_round(allocation_round["id"]), 100.00, 0.00, 0.00)

    def test_no_money_moved_anywhere_in_the_percentage_cycle(self):
        """A de minimis acceptance is a promise, not a payment.

        PRD: "Acceptance is a promise to pay, not a payment: `received_cents` stays at 0 and the site's `recovered_cost_cents` does not move."

        Design: Difficulty/compensating_invariant/de_minimis_void_restores_the_share_percentage_identity_to_exactly_100
        """
        site, _, prp_b, _, action = _halbrook_de_minimis_offer()
        respond_to_action(action["id"], prp_b["id"], "ACCEPT")
        void_action(action["id"], DE_MINIMIS_VOID_REASON)

        assert_ledger_figures(read_ledger(site["id"]), 4_620_000, 0, 0, 4_620_000)
        assert read_site(site["id"])["total_response_cost_cents"] == 4_620_000


def _winnow_junction_accepted_demand():
    """An orphan write-off in the middle of the ledger and an accepted demand."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(
        name="Winnow Junction Pesticide Formulation", epa_region=5, hrs_score=58.30
    )
    prp_a = create_participating_party(
        site["id"],
        legal_name="Winnow Agrochemical Inc",
        party_type="OWNER_OPERATOR",
        viability_score=91,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Junction Blending Corp",
        party_type="GENERATOR",
        viability_score=12,
    )
    prp_c = create_participating_party(
        site["id"],
        legal_name="Depot Haulage LLC",
        party_type="TRANSPORTER",
        viability_score=44,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3000, "I", "A", 1969)
    add_verified_waste_in(site["id"], prp_b["id"], 1000, "III", "B", 1975)
    add_verified_waste_in(site["id"], prp_c["id"], 40, "IV", "C", 1980)
    create_investigation(
        site["id"],
        exposure_medium="SOIL",
        scope_summary="OU-1 pesticide-contaminated soil and sediment",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    open_balloting(allocation_round["id"])
    cast_ballot(allocation_round["id"], prp_a["id"], "ACCEPT")
    cast_ballot(allocation_round["id"], prp_b["id"], "ACCEPT")
    cast_ballot(
        allocation_round["id"],
        prp_c["id"],
        "REJECT",
        ballot_rationale="Transporter liability overstated.",
    )
    post_oversight(
        site["id"], 4_000_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-19"
    )
    record_defunct(
        prp_b["id"], "Chapter 7 liquidation closed in 2019 with no successor."
    )
    action = issue_action(
        site["id"], prp_a["id"], 3_740_814, action_type="COST_RECOVERY_DEMAND"
    )
    respond_to_action(action["id"], prp_a["id"], "ACCEPT")
    return site, prp_a, prp_b, prp_c, allocation_round, action


class TestCollectThenVoidRestoresTheMoneyIdentity:
    def test_the_orphan_write_off_sits_in_the_middle_of_the_pre_collection_ledger(self):
        """A defunct party's percentage becomes a written-off cash bucket.

        PRD: "`orphan_write_off_cents` is `total_response_cost_cents` multiplied by the adopted round's `orphan_share_pct`, divided by 100 and rounded half up to whole cents."

        Design: Difficulty/compensating_invariant/collect_then_void_restores_the_money_ledger_identity_around_an_orphan_write_off
        """
        site, _, prp_b, _, allocation_round, _ = _winnow_junction_accepted_demand()

        assert_ledger_figures(read_ledger(site["id"]), 4_620_000, 0, 847_770, 3_772_230)
        assert_share_totals(read_round(allocation_round["id"]), 81.65, 18.35, 0.00)

        orphaned = share_for(allocation_round["id"], prp_b["id"])
        assert orphaned["disposition"] == "ORPHANED"
        assert_percentage(orphaned["final_pct"], 0.00, "final_pct")
        assert_percentage(
            orphaned["pre_settlement_final_pct"], 18.35, "pre_settlement_final_pct"
        )
        assert read_party(prp_b["id"])["status"] == "ORPHAN"

    def test_the_identity_holds_after_a_partial_receipt_not_merely_at_the_end(self):
        """A short receipt leaves the action accepted and the books balanced.

        PRD: "If the cumulative total now equals `demanded_cents` the action moves to `COLLECTED`; if it falls short the action stays `ACCEPTED` as a partial receipt, and further receipts are accepted against it until the demand is satisfied."

        Design: Difficulty/compensating_invariant/collect_then_void_restores_the_money_ledger_identity_around_an_orphan_write_off
        """
        site, _, _, _, _, action = _winnow_junction_accepted_demand()

        partial = record_collection(
            action["id"], 3_000_000, receipt_reference="FT-2027-WJP-0001"
        )
        assert partial["status"] == "ACCEPTED"
        assert partial["received_cents"] == 3_000_000
        assert_ledger_figures(
            read_ledger(site["id"]), 4_620_000, 3_000_000, 847_770, 772_230
        )

    def test_the_closing_receipt_collects_the_action_and_settles_the_respondent(self):
        """Protection is granted only once the money is fully in hand.

        PRD: "A fully collected `COST_RECOVERY_DEMAND` closes the party out: the respondent moves from `PARTICIPATING` or `RECALCITRANT` to `SETTLED` and its `contribution_protection` becomes true."

        Design: Difficulty/compensating_invariant/collect_then_void_restores_the_money_ledger_identity_around_an_orphan_write_off
        """
        site, prp_a, _, _, _, action = _winnow_junction_accepted_demand()
        record_collection(action["id"], 3_000_000, receipt_reference="FT-2027-WJP-0001")
        closed = record_collection(
            action["id"], 740_814, receipt_reference="FT-2027-WJP-0002"
        )

        assert closed["status"] == "COLLECTED"
        assert closed["received_cents"] == 3_740_814
        assert closed["received_cents"] == closed["demanded_cents"]
        assert read_party(prp_a["id"])["status"] == "SETTLED"
        assert_ledger_figures(
            read_ledger(site["id"]), 4_620_000, 3_740_814, 847_770, 31_416
        )

    def test_voiding_reverses_the_whole_booked_amount_and_touches_only_that_bucket(self):
        """The reversal returns the ledger to its pre-collection numbers exactly.

        PRD: "Voiding is a full compensating reversal, and its correctness is measured by the ledger: the site's `recovered_cost_cents` is decreased by exactly the `received_cents` the action had booked, the action's `received_cents` is reset to 0, and `unrecovered_cost_cents` is re-derived, so the conservation identity of §2.10 is restored with no residual drift."

        Design: Difficulty/compensating_invariant/collect_then_void_restores_the_money_ledger_identity_around_an_orphan_write_off
        """
        site, prp_a, _, _, allocation_round, action = _winnow_junction_accepted_demand()
        record_collection(action["id"], 3_000_000, receipt_reference="FT-2027-WJP-0001")
        record_collection(action["id"], 740_814, receipt_reference="FT-2027-WJP-0002")
        void_action(action["id"], COLLECTION_VOID_REASON)

        voided = read_action(action["id"])
        assert voided["status"] == "VOIDED"
        assert voided["received_cents"] == 0
        assert_ledger_figures(read_ledger(site["id"]), 4_620_000, 0, 847_770, 3_772_230)

    def test_the_money_reversal_leaves_the_share_percentages_alone(self):
        """A demand settlement never moved the percentages in the first place.

        PRD: "Voiding a collected `COST_RECOVERY_DEMAND` returns the respondent from `SETTLED` to `PARTICIPATING` and sets `contribution_protection` to false, but **leaves the share entirely alone** — there is nothing to restore, because a demand settlement never zeroed the `final_pct` in the first place."

        Design: Difficulty/compensating_invariant/collect_then_void_restores_the_money_ledger_identity_around_an_orphan_write_off
        """
        _, prp_a, _, _, allocation_round, action = _winnow_junction_accepted_demand()
        record_collection(action["id"], 3_000_000, receipt_reference="FT-2027-WJP-0001")
        record_collection(action["id"], 740_814, receipt_reference="FT-2027-WJP-0002")
        void_action(action["id"], COLLECTION_VOID_REASON)

        assert read_party(prp_a["id"])["status"] == "PARTICIPATING"
        payer_share = share_for(allocation_round["id"], prp_a["id"])
        assert payer_share["disposition"] == "ALLOCATED"
        assert_percentage(payer_share["final_pct"], 80.97, "final_pct")
        assert_share_totals(read_round(allocation_round["id"]), 81.65, 18.35, 0.00)
