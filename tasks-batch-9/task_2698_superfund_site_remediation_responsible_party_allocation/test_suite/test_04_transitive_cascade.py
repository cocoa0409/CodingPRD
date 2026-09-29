"""Three-hop cascades from a single write.

Verifying a waste-in claim rewrites the record, then the party and site totals,
then the provisional percentages of a drafting round. A not-protective five-year
review moves the site phase, then the signed decision document, then the cost
posture.
"""
import pytest

from test_helpers.assertions import assert_percentage, assert_percentages_sum_to_100
from test_helpers.fixtures import (
    add_alternative,
    add_ownership_period,
    add_sample,
    add_waste_in,
    add_work_window,
    alternatives_of,
    award_contract,
    complete_construction,
    create_investigation,
    create_listed_site,
    create_participating_party,
    create_rod,
    create_solicitation,
    file_comment,
    open_comment_period,
    open_round,
    read_contract,
    read_party,
    read_rod,
    read_round,
    read_site,
    record_five_year_review,
    review_investigation,
    set_clock,
    share_for,
    sign_rod,
    submit_investigation,
    verify_waste_in,
)


def _ferris_landing_drafting_round():
    """Four parties with unverified claims and a round still in drafting."""
    set_clock("2027-01-04T09:00:00Z")
    site = create_listed_site(
        name="Ferris Landing Disposal", epa_region=5, hrs_score=42.75
    )
    prp1 = create_participating_party(
        site["id"], legal_name="Acme Solvents Inc", party_type="GENERATOR", viability_score=80
    )
    prp2 = create_participating_party(
        site["id"], legal_name="Northshore Plating Co", party_type="GENERATOR", viability_score=70
    )
    prp3 = create_participating_party(
        site["id"], legal_name="Delta Haulers LLC", party_type="TRANSPORTER", viability_score=40
    )
    prp4 = create_participating_party(
        site["id"], legal_name="Tiny Print Shop LLC", party_type="GENERATOR", viability_score=25
    )
    add_ownership_period(site["id"], prp1["id"], "1962-03-01", "1978-06-01", "PURCHASE")
    add_ownership_period(site["id"], prp2["id"], "1978-06-01", "1995-01-01", "MERGER")
    w1 = add_waste_in(
        site["id"], prp1["id"], 4000, "II", "A", 1971, transporter_name="Delta Haulers LLC"
    )
    add_waste_in(site["id"], prp2["id"], 1000, "I", "A", 1983)
    add_waste_in(site["id"], prp3["id"], 500, "IV", "C", 1988)
    add_waste_in(site["id"], prp4["id"], 40, "IV", "B", 1990)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 groundwater and waste mass delineation",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    return site, [prp1, prp2, prp3, prp4], w1, allocation_round


class TestWasteInVerificationCascadesThreeHops:
    def test_first_hop_rewrites_the_record_and_stamps_the_verifier(self):
        """Verification records the reduced volume and who decided it.

        PRD: "**The first hop** rewrites the record itself: `status` becomes `VERIFIED` with `verified_volume_tons` and `effective_volume_tons` both set to the accepted figure, or `status` becomes `REJECTED` with `effective_volume_tons` set to 0."

        Design: Difficulty/transitive_cascade/waste_in_verification_cascades_three_hops_into_draft_round_shares
        """
        _, _, w1, _ = _ferris_landing_drafting_round()

        verified = verify_waste_in(
            w1["id"], 3600, verification_note="400 t of the claim has no manifest support."
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_volume_tons"] == pytest.approx(3600, abs=0.01)
        assert verified["effective_volume_tons"] == pytest.approx(3600, abs=0.01)
        assert verified["verified_by_user_id"] == "rpm-001"

    def test_second_hop_rewrites_the_party_totals_and_every_party_percentage(self):
        """The one verified record becomes the whole site denominator.

        PRD: "Because that site total is the denominator of every party's `volumetric_share_pct`, **every** party of the site — not only the one whose record moved — has its `volumetric_share_pct` recomputed as its own `verified_volume_tons` divided by the site total, multiplied by 100 and rounded half up to two decimal places, reported as 0.00 when the site total is zero."

        Design: Difficulty/transitive_cascade/waste_in_verification_cascades_three_hops_into_draft_round_shares
        """
        site, parties, w1, _ = _ferris_landing_drafting_round()
        verify_waste_in(
            w1["id"], 3600, verification_note="400 t of the claim has no manifest support."
        )

        prp1 = read_party(parties[0]["id"])
        assert prp1["verified_volume_tons"] == pytest.approx(3600, abs=0.01)
        assert prp1["submitted_volume_tons"] == pytest.approx(3600, abs=0.01)
        assert prp1["max_toxicity_class"] == "II"
        assert_percentage(prp1["volumetric_share_pct"], 100.00, "volumetric_share_pct")
        assert prp1["de_minimis_eligible"] is False

        prp4 = read_party(parties[3]["id"])
        assert_percentage(prp4["volumetric_share_pct"], 0.00, "volumetric_share_pct")
        assert prp4["max_toxicity_class"] in (None, "")
        assert prp4["de_minimis_eligible"] is False

        assert read_site(site["id"])["verified_waste_volume_tons"] == pytest.approx(
            3600, abs=0.01
        )

    def test_third_hop_re_derives_the_provisional_percentages_of_the_drafting_round(self):
        """A drafting round follows the evidence; adoption has not happened.

        PRD: "**The third hop** follows from the changed party volumes. Every share of the site's allocation round has its `provisional_pct` re-derived against the new data — but only while that round is `DRAFTING`."

        Design: Difficulty/transitive_cascade/waste_in_verification_cascades_three_hops_into_draft_round_shares
        """
        _, parties, w1, allocation_round = _ferris_landing_drafting_round()
        verify_waste_in(
            w1["id"], 3600, verification_note="400 t of the claim has no manifest support."
        )

        round_id = allocation_round["id"]
        assert read_round(round_id)["status"] == "DRAFTING"
        percentages = []
        for party, expected in zip(parties, (63.75, 30.29, 5.52, 0.44)):
            share = share_for(round_id, party["id"])
            assert_percentage(share["provisional_pct"], expected, "provisional_pct")
            percentages.append(share["provisional_pct"])
        assert_percentages_sum_to_100(percentages)
        assert share_for(round_id, parties[0]["id"])["final_pct"] in (None, "")


def _granite_hollow_om_site():
    """A site carried to operations and maintenance with a signed remedy."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(
        name="Granite Hollow Landfill", epa_region=2, hrs_score=55.00
    )
    investigation = create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 groundwater plume, landfill cap evaluation",
    )
    add_sample(
        investigation["id"], "GROUNDWATER", "TRICHLOROETHENE", 24.0, "VALID",
        "2027-01-20T10:00:00Z", "LAB-G-0001",
    )
    add_sample(
        investigation["id"], "GROUNDWATER", "VINYL_CHLORIDE", 60.0, "ESTIMATED",
        "2027-01-20T11:00:00Z", "LAB-G-0002",
    )
    submit_investigation(investigation["id"])
    review_investigation(
        investigation["id"], "APPROVE", "Risk assessment adequate for remedy selection."
    )
    alt_a = add_alternative(
        investigation["id"],
        label="CAP_AND_PUMP_TREAT",
        capital_cost_cents=1_250_000_000,
        annual_om_cost_cents=45_000_000,
        om_years=30,
        discount_rate_bp=700,
        effectiveness_score=90,
        implementability_score=62,
    )
    rod = create_rod(
        site["id"],
        investigation["id"],
        comment_period_days=30,
        proposed_plan_summary="Cap the landfill and pump-and-treat OU-1 groundwater.",
    )
    set_clock("2027-03-01T09:00:00Z")
    open_comment_period(rod["id"])
    set_clock("2027-03-05T14:00:00Z")
    file_comment(
        rod["id"],
        commenter_name="Granite Hollow Neighbors Association",
        comment_text="Request additional vapour intrusion sampling near the school.",
    )
    set_clock("2027-04-01T09:00:00Z")
    sign_rod(
        rod["id"],
        responsiveness_summary="Vapour intrusion sampling added to the O&M plan.",
    )
    contract = create_solicitation(
        site["id"],
        rod["id"],
        engineer_estimate_cents=700_000_000,
        solicitation_reference="SOL-2027-GHL-014",
    )
    award_contract(
        contract["id"],
        620_000_000,
        contractor_name="Northgate Environmental Constructors",
        max_concurrent_windows=2,
    )
    add_work_window(
        contract["id"],
        "2027-05-03T08:00:00Z",
        "2027-08-30T17:00:00Z",
        crew_size=24,
        description="Cap construction, phase 1",
    )
    set_clock("2029-05-15T09:00:00Z")
    complete_construction(contract["id"], punch_list_items=3)
    set_clock("2034-05-15T00:00:00Z")
    return site, investigation, alt_a, rod, contract


class TestNotProtectiveReviewCascadesThreeHops:
    def test_the_site_is_in_operations_and_maintenance_with_the_review_due(self):
        """Completion stamps the phase, the completion instant and the due date.

        PRD: "The site's `five_year_review_due_at` is set to `construction_complete_at` plus 1,826 days — five calendar years including one leap day — also at exactly midnight UTC."

        Design: Difficulty/transitive_cascade/not_protective_five_year_review_cascades_three_hops_into_cost_posture
        """
        site, _, _, _, _ = _granite_hollow_om_site()

        before = read_site(site["id"])
        assert before["listing_status"] == "OM_PHASE"
        assert before["construction_complete_at"].startswith("2029-05-15T00:00:00")
        assert before["five_year_review_due_at"].startswith("2034-05-15T00:00:00")
        assert before["cost_posture"] == "OPEN"
        assert before["total_response_cost_cents"] == 620_000_000

    def test_first_hop_moves_the_phase_and_chains_the_next_due_date_off_the_old_one(self):
        """The next review is due five years after the previous due date.

        PRD: "For both the self-loop and the reevaluation branch, the next `five_year_review_due_at` is derived by adding 1,826 days **to the previous due date, never to the date the review was actually performed**."

        Design: Difficulty/transitive_cascade/not_protective_five_year_review_cascades_three_hops_into_cost_posture
        """
        site, _, _, _, _ = _granite_hollow_om_site()
        record_five_year_review(
            site["id"],
            protectiveness_determination="NOT_PROTECTIVE",
            deletion_recommended=False,
            review_summary=(
                "Plume rebound above the action level; cap remains protective but "
                "groundwater remedy is not."
            ),
        )

        after = read_site(site["id"])
        assert after["listing_status"] == "REMEDY_REEVALUATION"
        assert after["last_five_year_review_at"].startswith("2034-05-15T00:00:00")
        assert after["last_protectiveness_determination"] == "NOT_PROTECTIVE"
        assert after["five_year_review_due_at"].startswith("2039-05-15T00:00:00")

    def test_second_and_third_hops_reopen_remedy_selection_and_restrict_the_site(self):
        """The signed document awaits amendment and the posture becomes restricted.

        PRD: "**The second hop follows from the first**: because the site has entered reevaluation, the site's decision document whose `status` is `SIGNED` moves `SIGNED → AMENDMENT_REQUIRED`, reopening remedy selection."

        Design: Difficulty/transitive_cascade/not_protective_five_year_review_cascades_three_hops_into_cost_posture
        """
        site, _, _, rod, _ = _granite_hollow_om_site()
        record_five_year_review(
            site["id"],
            protectiveness_determination="NOT_PROTECTIVE",
            deletion_recommended=False,
            review_summary=(
                "Plume rebound above the action level; cap remains protective but "
                "groundwater remedy is not."
            ),
        )

        assert read_rod(rod["id"])["status"] == "AMENDMENT_REQUIRED"
        assert read_site(site["id"])["cost_posture"] == "RESTRICTED"

    def test_the_contract_stays_construction_complete_because_only_protective_closes_it(self):
        """The smaller closing cascade belongs to a protective determination alone.

        PRD: "A `PROTECTIVE` determination has a smaller cascade of its own: the site's contract sitting in `CONSTRUCTION_COMPLETE` moves to `CLOSED`, with no other field changed — its `completion_date` was already stamped at certification."

        Design: Difficulty/transitive_cascade/not_protective_five_year_review_cascades_three_hops_into_cost_posture
        """
        site, investigation, alt_a, rod, contract = _granite_hollow_om_site()
        record_five_year_review(
            site["id"],
            protectiveness_determination="NOT_PROTECTIVE",
            deletion_recommended=False,
            review_summary=(
                "Plume rebound above the action level; cap remains protective but "
                "groundwater remedy is not."
            ),
        )

        assert read_contract(contract["id"])["status"] == "CONSTRUCTION_COMPLETE"
        selected = [a for a in alternatives_of(investigation["id"]) if a["id"] == alt_a["id"]][0]
        assert selected["selected_by_rod_id"] == rod["id"]
        assert_percentage(selected["remedy_score"], 80.47, "remedy_score")
