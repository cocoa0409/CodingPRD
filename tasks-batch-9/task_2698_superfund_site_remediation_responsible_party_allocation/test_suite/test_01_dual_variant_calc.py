"""Two named variants of one calculation, computed from the same rows.

The allocation share is computed provisionally and finally over the same
waste-in records, and the risk assessment is computed at central tendency and at
the reasonable maximum exposure over the same sample set.
"""
import pytest

from test_helpers.assertions import (
    assert_epc,
    assert_percentage,
    assert_percentages_sum_to_100,
    assert_seven_decimal_risk,
    assert_share_totals,
)
from test_helpers.fixtures import (
    add_ownership_period,
    add_sample,
    add_waste_in,
    cast_ballot,
    create_investigation,
    create_listed_site,
    create_participating_party,
    open_balloting,
    open_round,
    read_investigation,
    read_party,
    read_round,
    read_site,
    reject_waste_in,
    set_clock,
    share_for,
    submit_investigation,
    verify_waste_in,
)


def _buckeye_scenario():
    """Four parties ballot on provisional shares that verification then rewrites.

    The round is moved to BALLOTING while every claim is still SUBMITTED, so the
    provisional percentages are frozen against claimed volumes. Verification
    afterwards cuts one claim, confirms two and rejects one, so the final
    percentages computed at adoption differ from the ones balloted on.
    """
    set_clock("2027-01-04T09:00:00Z")
    site = create_listed_site(
        name="Buckeye Drum Yard", epa_region=5, hrs_score=42.75
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
    w1 = add_waste_in(site["id"], prp1["id"], 4000, "II", "A", 1971)
    w2 = add_waste_in(site["id"], prp2["id"], 1000, "I", "A", 1983)
    w3 = add_waste_in(site["id"], prp3["id"], 500, "IV", "C", 1988)
    w4 = add_waste_in(site["id"], prp4["id"], 40, "IV", "B", 1990)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="Groundwater plume delineation, OU-1",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    open_balloting(allocation_round["id"])
    verify_waste_in(
        w1["id"], 3600, verification_note="Manifest tonnage reconciled; 400 t unsupported."
    )
    verify_waste_in(w2["id"], 1000)
    reject_waste_in(w3["id"], verification_note="No manifest, no witness statement.")
    verify_waste_in(w4["id"], 40)
    return {
        "site": site,
        "prp1": prp1,
        "prp2": prp2,
        "prp3": prp3,
        "prp4": prp4,
        "round": allocation_round,
    }


class TestAllocationShareProvisionalVersusFinal:
    def test_provisional_percentages_are_frozen_at_balloting_against_claimed_volumes(self):
        """The balloted percentages value still-submitted claims at claimed volume.

        PRD: "The provisional variant counts every waste-in record of the site whose `status` is `SUBMITTED` or `VERIFIED`, valued at `effective_volume_tons` — so an unverified submission counts at its full claimed volume and a party whose claim is later cut keeps its full negotiating weight until then."

        Design: Difficulty/dual_variant_calc/allocation_share_provisional_vs_final_diverge_on_waste_in_verification
        """
        scenario = _buckeye_scenario()
        round_id = scenario["round"]["id"]

        assert_percentage(
            share_for(round_id, scenario["prp1"]["id"])["provisional_pct"], 65.56
        )
        assert_percentage(
            share_for(round_id, scenario["prp2"]["id"])["provisional_pct"], 28.91
        )
        assert_percentage(
            share_for(round_id, scenario["prp3"]["id"])["provisional_pct"], 5.12
        )
        assert_percentage(
            share_for(round_id, scenario["prp4"]["id"])["provisional_pct"], 0.41
        )
        assert_percentages_sum_to_100(
            share["provisional_pct"]
            for share in [
                share_for(round_id, scenario[key]["id"])
                for key in ("prp1", "prp2", "prp3", "prp4")
            ]
        )

    def test_final_percentages_at_adoption_diverge_from_the_balloted_provisional_set(self):
        """Adoption recomputes on verified volumes, so the two variants diverge.

        PRD: "The provisional variant writes `provisional_pct`; the final variant writes `final_pct` and runs exactly once, at adoption."

        Design: Difficulty/dual_variant_calc/allocation_share_provisional_vs_final_diverge_on_waste_in_verification
        """
        scenario = _buckeye_scenario()
        round_id = scenario["round"]["id"]
        for key in ("prp1", "prp2", "prp3", "prp4"):
            cast_ballot(round_id, scenario[key]["id"], "ACCEPT")

        adopted = read_round(round_id)
        assert adopted["status"] == "ADOPTED"
        assert adopted["share_count"] == 4
        assert adopted["balloted_count"] == 4
        assert_percentage(adopted["accept_share_pct"], 100.00, "accept_share_pct")

        share1 = share_for(round_id, scenario["prp1"]["id"])
        share2 = share_for(round_id, scenario["prp2"]["id"])
        share3 = share_for(round_id, scenario["prp3"]["id"])
        share4 = share_for(round_id, scenario["prp4"]["id"])
        assert_percentage(share1["final_pct"], 67.95, "final_pct")
        assert_percentage(share2["final_pct"], 31.57, "final_pct")
        assert_percentage(share3["final_pct"], 0.00, "final_pct")
        assert_percentage(share4["final_pct"], 0.48, "final_pct")
        assert share1["final_pct"] != share1["provisional_pct"]
        assert_percentages_sum_to_100(
            share["final_pct"] for share in (share1, share2, share3, share4)
        )
        assert_share_totals(adopted, 100.00, 0.00, 0.00)

    def test_a_rejected_claim_zeroes_the_percentage_without_removing_the_party(self):
        """A party whose only claim was rejected is still bound by the allocation.

        PRD: "The final variant of the share arithmetic runs, and every share belonging to a party whose `status` is `PARTICIPATING` or `RECALCITRANT` receives its `final_pct` with `disposition` `ALLOCATED`."

        Design: Difficulty/dual_variant_calc/allocation_share_provisional_vs_final_diverge_on_waste_in_verification
        """
        scenario = _buckeye_scenario()
        round_id = scenario["round"]["id"]
        for key in ("prp1", "prp2", "prp3", "prp4"):
            cast_ballot(round_id, scenario[key]["id"], "ACCEPT")

        share3 = share_for(round_id, scenario["prp3"]["id"])
        assert_percentage(share3["final_pct"], 0.00, "final_pct")
        assert share3["disposition"] == "ALLOCATED"

    def test_verification_totals_reconcile_on_the_party_and_on_the_site(self):
        """Verified tonnage rolls up to the party and to the site.

        PRD: "The site's `verified_waste_volume_tons` is re-derived as the sum of `verified_volume_tons` over every verified record of the site."

        Design: Difficulty/dual_variant_calc/allocation_share_provisional_vs_final_diverge_on_waste_in_verification
        """
        scenario = _buckeye_scenario()

        prp1 = read_party(scenario["prp1"]["id"])
        assert prp1["verified_volume_tons"] == pytest.approx(3600, abs=0.01)
        assert prp1["submitted_volume_tons"] == pytest.approx(3600, abs=0.01)

        site = read_site(scenario["site"]["id"])
        assert site["verified_waste_volume_tons"] == pytest.approx(4640, abs=0.01)


def _willow_creek_investigation():
    """One groundwater study whose five samples exercise every qualification rule."""
    set_clock("2027-02-01T08:00:00Z")
    site = create_listed_site(
        name="Willow Creek Solvent Recovery", epa_region=4, hrs_score=51.20
    )
    investigation = create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 groundwater risk assessment",
    )
    add_sample(
        investigation["id"], "GROUNDWATER", "TRICHLOROETHENE", 24.0, "VALID",
        "2027-01-11T14:00:00Z", "LAB-A-0001",
    )
    add_sample(
        investigation["id"], "GROUNDWATER", "TETRACHLOROETHENE", 16.0, "VALID",
        "2027-01-11T15:00:00Z", "LAB-A-0002",
    )
    add_sample(
        investigation["id"], "GROUNDWATER", "VINYL_CHLORIDE", 60.0, "ESTIMATED",
        "2027-01-12T09:00:00Z", "LAB-A-0003",
    )
    add_sample(
        investigation["id"], "SOIL", "TRICHLOROETHENE", 900.0, "VALID",
        "2027-01-12T10:00:00Z", "LAB-A-0004",
    )
    add_sample(
        investigation["id"], "GROUNDWATER", "VINYL_CHLORIDE", 500.0, "REJECTED",
        "2027-01-12T11:00:00Z", "LAB-A-0005",
    )
    return site, investigation


class TestRiskAssessmentCentralTendencyVersusRme:
    def test_central_tendency_averages_valid_samples_only(self):
        """The central-tendency concentration is the mean over valid samples.

        PRD: "The `central_tendency_epc_ug_per_l` is the arithmetic mean of `concentration_ug_per_l` over the central-tendency set, rounded half up to three decimal places."

        Design: Difficulty/dual_variant_calc/risk_assessment_central_tendency_vs_rme_diverge_on_same_sample_set
        """
        _, investigation = _willow_creek_investigation()
        submitted = submit_investigation(investigation["id"])

        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["valid_sample_count"] == 2
        assert_epc(
            submitted["central_tendency_epc_ug_per_l"], 20.000, "central_tendency_epc_ug_per_l"
        )
        assert_seven_decimal_risk(
            submitted["central_tendency_risk"], 0.0001000, "central_tendency_risk"
        )

    def test_reasonable_maximum_takes_the_maximum_over_valid_and_estimated(self):
        """The reasonable-maximum concentration is three times the mean here.

        PRD: "The `rme_epc_ug_per_l` is instead the single largest `concentration_ug_per_l` in the reasonable-maximum-exposure set, taken as reported rather than averaged."

        Design: Difficulty/dual_variant_calc/risk_assessment_central_tendency_vs_rme_diverge_on_same_sample_set
        """
        _, investigation = _willow_creek_investigation()
        submitted = submit_investigation(investigation["id"])

        assert submitted["rme_epc_ug_per_l"] == pytest.approx(60.0, abs=0.05)
        assert_seven_decimal_risk(submitted["rme_risk"], 0.0003000, "rme_risk")
        assert submitted["rme_risk"] == pytest.approx(
            3 * submitted["central_tendency_risk"], abs=0.00000005
        )

    def test_hazard_index_and_action_level_follow_the_reasonable_maximum(self):
        """The hazard index divides the reasonable-maximum concentration.

        PRD: "The `hazard_index` is the reasonable-maximum concentration divided by the reference concentration of 5.0 micrograms per litre, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/risk_assessment_central_tendency_vs_rme_diverge_on_same_sample_set
        """
        _, investigation = _willow_creek_investigation()
        submit_investigation(investigation["id"])

        reread = read_investigation(investigation["id"])
        assert reread["hazard_index"] == pytest.approx(12.00, abs=0.01)
        assert reread["action_level_exceeded"] is True
