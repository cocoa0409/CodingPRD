"""Derived-figure probes: thresholds, input-set filters, remainders, branches.

These exercise the arithmetic the service performs on its own — which inputs a
formula is allowed to see, where an inclusive constant sits, who absorbs the
rounding remainder, whether a repeat assessment recomputes or accumulates, and
which weighting branch a composite score takes.
"""
from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import (
    assert_epc,
    assert_percentage,
    assert_percentages_sum_to_100,
    assert_seven_decimal_risk,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_alternative,
    add_sample,
    add_verified_waste_in,
    add_waste_in,
    adopt_round,
    alternatives_of,
    create_decree,
    create_investigation,
    create_participating_party,
    create_site,
    enter_decree,
    list_site_on_npl,
    lodge_decree,
    open_round,
    read_decree,
    read_investigation,
    read_site,
    record_penalty_assessment,
    record_violation,
    reject_waste_in,
    set_clock,
    share_for,
    shares_of,
    submit_investigation,
    verify_waste_in,
)
from test_helpers.test_users import TEST_USERS

AUTHOR = TEST_USERS["author_pm_headers"]


class TestHrsListingThreshold:
    def test_a_site_scoring_exactly_the_threshold_lists(self):
        """The listing threshold is inclusive at 28.50.

        PRD: "Listing is permitted only from `PROPOSED`, and only when the site's `hrs_score` is at least 28.50 — a score of exactly 28.50 qualifies."

        Design: Corner/calculations/corner_hrs_score_exactly_at_the_listing_threshold_lists_while_one_hundredth_below_returns_4XX
        """
        set_clock("2027-01-04T08:00:00Z")
        site = create_site(
            name="Marlin Point Drum Reconditioning", epa_region=2, hrs_score=28.50
        )
        listed = validate_success(
            api_client.list_on_npl(
                site["id"],
                factories.listing_payload(listing_reference="FR-2027-MPD-0104"),
                AUTHOR,
            )
        )
        assert listed["listing_status"] == "LISTED"
        assert listed["listing_reference"] == "FR-2027-MPD-0104"

    def test_a_site_one_hundredth_below_the_threshold_is_refused(self):
        """One hundredth below the threshold does not qualify.

        PRD: "A score below that threshold is refused with `ERR_HRS_SCORE_BELOW_THRESHOLD`."

        Design: Corner/calculations/corner_hrs_score_exactly_at_the_listing_threshold_lists_while_one_hundredth_below_returns_4XX
        """
        set_clock("2027-01-04T08:00:00Z")
        site = create_site(
            name="Larkin Hollow Scrapyard", epa_region=2, hrs_score=28.49
        )
        refusal = api_client.list_on_npl(
            site["id"],
            factories.listing_payload(listing_reference="FR-2027-LHS-0104"),
            AUTHOR,
        )
        validate_error(refusal, ApiErrorId.ERR_HRS_SCORE_BELOW_THRESHOLD, 409)

        after = read_site(site["id"])
        assert after["listing_status"] == "PROPOSED"
        assert after["listing_reference"] in (None, "")


def _wrenfield_mixed_record_states():
    """Three parties, all class IV, in the three waste-in record states.

    Party A holds 600 verified tons, party B a still-unverified 300-ton claim
    and party C a rejected 900-ton claim — the largest number on the site.
    """
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Wrenfield Drum Storage", epa_region=8, hrs_score=39.20)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-WDS-0201")
    prp_a = create_participating_party(
        site["id"],
        legal_name="Wrenfield Drum Co",
        party_type="OWNER_OPERATOR",
        viability_score=64,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Halloway Solvent Recovery",
        party_type="GENERATOR",
        viability_score=52,
    )
    prp_c = create_participating_party(
        site["id"],
        legal_name="Pike Hauling Partners",
        party_type="TRANSPORTER",
        viability_score=29,
    )
    record_a = add_waste_in(
        site["id"],
        prp_a["id"],
        volume_tons=600,
        toxicity_class="IV",
        evidence_grade="A",
        disposal_year=1974,
    )
    add_waste_in(
        site["id"],
        prp_b["id"],
        volume_tons=300,
        toxicity_class="IV",
        evidence_grade="C",
        disposal_year=1976,
    )
    record_c = add_waste_in(
        site["id"],
        prp_c["id"],
        volume_tons=900,
        toxicity_class="IV",
        evidence_grade="C",
        disposal_year=1979,
    )
    verify_waste_in(record_a["id"], 600)
    reject_waste_in(
        record_c["id"],
        verification_note="Manifest is a photocopy of another site's ledger.",
    )
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 solvent plume",
    )
    allocation_round = open_round(site["id"], weights=(6000, 4000, 0))
    return {
        "site": site,
        "prp_a": prp_a,
        "prp_b": prp_b,
        "prp_c": prp_c,
        "round": allocation_round,
    }


class TestProvisionalRecordSetFilter:
    def test_a_submitted_claim_counts_in_full_and_a_rejected_claim_not_at_all(self):
        """The provisional basis is 900 tons, not the 1,800 the raw claims total.

        PRD: "The provisional variant counts every waste-in record of the site whose `status` is `SUBMITTED` or `VERIFIED`, valued at `effective_volume_tons` — so an unverified submission counts at its full claimed volume and a party whose claim is later cut keeps its full negotiating weight until then."

        Design: Corner/calculations/corner_provisional_share_ignores_rejected_records_and_counts_submitted_at_claimed_volume
        """
        world = _wrenfield_mixed_record_states()
        round_id = world["round"]["id"]
        assert world["round"]["status"] == "DRAFTING"
        assert world["round"]["share_count"] == 3

        assert_percentage(
            share_for(round_id, world["prp_a"]["id"])["provisional_pct"],
            66.67,
            "provisional_pct A",
        )
        assert_percentage(
            share_for(round_id, world["prp_b"]["id"])["provisional_pct"],
            33.33,
            "provisional_pct B",
        )
        assert_percentage(
            share_for(round_id, world["prp_c"]["id"])["provisional_pct"],
            0.00,
            "provisional_pct C",
        )
        assert_percentages_sum_to_100(
            [share["provisional_pct"] for share in shares_of(round_id)]
        )

        # Had the rejected 900-ton record been counted the basis would have been
        # 1,800 tons and party A would read 33.33, so the filter is observable.
        assert share_for(round_id, world["prp_a"]["id"])["provisional_pct"] != 33.33

    def test_only_the_verified_record_moves_the_site_volume_total(self):
        """The site total sums verified volumes alone.

        PRD: "The site's `verified_waste_volume_tons` is re-derived as the sum of `verified_volume_tons` over every verified record of the site."

        Design: Corner/calculations/corner_provisional_share_ignores_rejected_records_and_counts_submitted_at_claimed_volume
        """
        world = _wrenfield_mixed_record_states()
        site = read_site(world["site"]["id"])
        assert site["verified_waste_volume_tons"] == 600


def _ashcombe_repeating_decimal_round():
    """Three parties each with 100 verified tons; only the toxicity class differs.

    Weights of 6250 and 3750 basis points over volume and toxicity make every
    unrounded share a repeating decimal, so the rounded shares total 99.99.
    """
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Ashcombe Plating Works", epa_region=3, hrs_score=42.10)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-APW-0201")
    prp_a = create_participating_party(
        site["id"],
        legal_name="Ashcombe Plating Inc",
        party_type="OWNER_OPERATOR",
        viability_score=71,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Brightwater Anodizing",
        party_type="GENERATOR",
        viability_score=48,
    )
    prp_c = create_participating_party(
        site["id"],
        legal_name="Cobb Drum Service",
        party_type="TRANSPORTER",
        viability_score=34,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 100, "II", "A", 1968)
    add_verified_waste_in(site["id"], prp_b["id"], 100, "II", "A", 1971)
    add_verified_waste_in(site["id"], prp_c["id"], 100, "III", "B", 1975)
    create_investigation(
        site["id"],
        exposure_medium="SOIL",
        scope_summary="OU-1 hexavalent chromium in soil",
    )
    allocation_round = open_round(site["id"], weights=(6250, 3750, 0))
    return {
        "site": site,
        "prp_a": prp_a,
        "prp_b": prp_b,
        "prp_c": prp_c,
        "round": allocation_round,
    }


class TestShareRemainderAssignment:
    def test_the_remaining_hundredth_lands_on_one_party_so_the_round_totals_100(self):
        """Naive per-party rounding stops at 99.99; the residual closes the gap.

        PRD: "The residual, computed as 100.00 minus the sum of the rounded party percentages, is assigned in full to **one** party: the party with the largest volumetric contribution."

        Design: Corner/calculations/corner_share_remainder_hundredth_goes_to_the_largest_volume_party
        """
        world = _ashcombe_repeating_decimal_round()
        round_id = world["round"]["id"]
        assert world["round"]["share_count"] == 3

        percentages = [share["provisional_pct"] for share in shares_of(round_id)]
        assert_percentages_sum_to_100(percentages)
        assert sum(percentages) != 99.99

        assert_percentage(
            share_for(round_id, world["prp_c"]["id"])["provisional_pct"],
            28.33,
            "provisional_pct C",
        )

    def test_the_volume_and_ownership_ties_hand_the_remainder_to_the_earliest_party(
        self,
    ):
        """Identical inputs are separated by creation order alone.

        PRD: "Should two parties tie on that, the one with the larger ownership contribution takes the residual; should they still tie, the party created earliest takes it, ordered by `created_at` and never by `id`."

        Design: Corner/calculations/corner_share_remainder_hundredth_goes_to_the_largest_volume_party
        """
        world = _ashcombe_repeating_decimal_round()
        round_id = world["round"]["id"]

        # A and B have identical volume and identical (zero) ownership days, so
        # the residual falls to whichever was created first.
        assert_percentage(
            share_for(round_id, world["prp_a"]["id"])["provisional_pct"],
            35.84,
            "provisional_pct A",
        )
        assert_percentage(
            share_for(round_id, world["prp_b"]["id"])["provisional_pct"],
            35.83,
            "provisional_pct B",
        )


def _dunmore_penalty_accruing_decree():
    """An entered decree with one open violation effective 2027-04-05.

    The oversight cap of 100,000,000 cents puts the penalty ceiling at
    10,000,000 cents, and the flat rate is 250,000 cents a day.
    """
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Dunmore Chemical Works", epa_region=3, hrs_score=55.20)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-DCW-0201")
    prp_a = create_participating_party(
        site["id"],
        legal_name="Dunmore Chemical Co",
        party_type="OWNER_OPERATOR",
        viability_score=88,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Kestrel Reagents LLC",
        party_type="GENERATOR",
        viability_score=45,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1969)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1988)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 chlorinated solvents",
    )
    allocation_round = open_round(site["id"])
    adopt_round(allocation_round["id"], [prp_a["id"], prp_b["id"]])
    decree = create_decree(
        site["id"],
        [prp_a["id"], prp_b["id"]],
        scope_type="RD_RA_CONSENT_DECREE",
        scope_summary="RD/RA with stipulated penalties",
        oversight_cost_cap_cents=100_000_000,
        stipulated_penalty_per_day_cents=250_000,
        performance_deadline="2028-06-30",
    )
    set_clock("2027-03-01T10:00:00Z")
    lodge_decree(decree["id"])
    set_clock("2027-04-01T09:00:00Z")
    enter_decree(decree["id"], court_docket_number="3:27-cv-00812-DCW")
    record_violation(decree["id"], "2027-04-05T00:00:00Z")
    return {"site": site, "decree": decree}


class TestStipulatedPenaltyRecomputation:
    def test_the_first_assessment_charges_thirty_flat_days_and_nothing_escalated(self):
        """Thirty inclusive days sit exactly on the flat-rate boundary.

        PRD: "The first 30 of those days accrue at the flat `stipulated_penalty_per_day_cents` rate; specifically, the flat day count is whichever is smaller of `days_in_violation` and 30. Any days beyond the thirtieth accrue at an escalated rate — the escalated day count is `days_in_violation` less 30, or zero if that would be negative — and the escalated daily rate is `stipulated_penalty_per_day_cents` multiplied by 15,000 basis points, divided by 10,000, rounded half up to whole cents, which is one and a half times the flat rate."

        Design: Corner/calculations/corner_stipulated_penalty_recomputes_from_first_noncompliance_without_double_stepping
        """
        world = _dunmore_penalty_accruing_decree()
        decree_id = world["decree"]["id"]

        set_clock("2027-05-04T08:00:00Z")
        assessed = record_penalty_assessment(decree_id, "2027-05-04T00:00:00Z")

        assert assessed["days_in_violation"] == 30
        assert assessed["accrued_penalty_cents"] == 7_500_000
        assert assessed["penalty_capped"] is False
        assert assessed["penalty_cap_cents"] == 10_000_000

    def test_a_second_assessment_recomputes_instead_of_adding(self):
        """One more day adds one escalated day, not a second thirty-day step.

        PRD: "**Repeat assessments recompute the whole accrual from `first_noncompliance_date`; they never add to the previous figure.**"

        Design: Corner/calculations/corner_stipulated_penalty_recomputes_from_first_noncompliance_without_double_stepping
        """
        world = _dunmore_penalty_accruing_decree()
        decree_id = world["decree"]["id"]

        set_clock("2027-05-04T08:00:00Z")
        record_penalty_assessment(decree_id, "2027-05-04T00:00:00Z")
        set_clock("2027-05-05T08:00:00Z")
        second = record_penalty_assessment(decree_id, "2027-05-05T00:00:00Z")

        assert second["days_in_violation"] == 31
        assert second["accrued_penalty_cents"] == 7_875_000
        # Adding the two accruals would give 15,375,000 and clamping would give
        # the 10,000,000 cap; neither is what a recomputation produces.
        assert second["accrued_penalty_cents"] != 15_375_000
        assert second["accrued_penalty_cents"] != 10_000_000
        assert second["penalty_capped"] is False

        decree = read_decree(decree_id)
        assert decree["compliance_status"] == "PENALTY_ACCRUING"
        assert decree["first_noncompliance_date"] == "2027-04-05"
        assert decree["last_assessment_at"].startswith("2027-05-05T00:00:00")
        assert decree["open_violation_count"] == 1
        assert read_site(world["site"]["id"])["cost_posture"] == "FROZEN"


def _rushmere_two_alternatives():
    """One draft groundwater investigation with two costed alternatives.

    Alternative P discounts to 1,000,000,000 cents for a cost score of 80.00 and
    alternative Q to 2,500,000,000 for 50.00, while Q is the more effective and
    P by far the more implementable.
    """
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(name="Rushmere Solvent Terminal", epa_region=6, hrs_score=47.40)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-RST-0201")
    investigation = create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 TCE plume beneath the tank farm",
    )
    add_sample(
        investigation["id"],
        medium="GROUNDWATER",
        contaminant="TRICHLOROETHENE",
        concentration_ug_per_l=25.0,
        qa_status="VALID",
        collected_at="2027-01-20T14:00:00Z",
        lab_reference="LAB-RST-0001",
    )
    alt_p = add_alternative(
        investigation["id"],
        label="P - pump and treat with MNA",
        capital_cost_cents=938_888_889,
        annual_om_cost_cents=40_000_000,
        om_years=2,
        discount_rate_bp=2000,
        effectiveness_score=62,
        implementability_score=95,
    )
    alt_q = add_alternative(
        investigation["id"],
        label="Q - in situ thermal treatment",
        capital_cost_cents=2_438_888_889,
        annual_om_cost_cents=40_000_000,
        om_years=2,
        discount_rate_bp=2000,
        effectiveness_score=90,
        implementability_score=40,
    )
    return {
        "site": site,
        "investigation": investigation,
        "alt_p": alt_p,
        "alt_q": alt_q,
    }


def _by_id(rows):
    return {row["id"]: row for row in rows}


class TestRemedyScoreWeightingBranch:
    def test_the_normal_branch_ranks_the_cheap_implementable_alternative_first(self):
        """While the action level is unexceeded, implementability carries real weight.

        PRD: "When the action level has not been exceeded, the score is 0.45 times the `effectiveness_score`, plus 0.35 times the `implementability_score`, plus 0.20 times the `cost_score`, again rounded half up to two decimal places."

        Design: Corner/calculations/corner_remedy_score_branch_flips_the_ranking_when_the_action_level_is_exceeded
        """
        world = _rushmere_two_alternatives()
        scored = _by_id(alternatives_of(world["investigation"]["id"]))
        alt_p = scored[world["alt_p"]["id"]]
        alt_q = scored[world["alt_q"]["id"]]

        assert alt_p["npv_cents"] == 1_000_000_000
        assert_percentage(alt_p["cost_score"], 80.00, "cost_score P")
        assert alt_q["npv_cents"] == 2_500_000_000
        assert_percentage(alt_q["cost_score"], 50.00, "cost_score Q")

        assert_percentage(alt_p["remedy_score"], 77.15, "remedy_score P")
        assert_percentage(alt_q["remedy_score"], 64.50, "remedy_score Q")
        assert alt_p["remedy_score"] > alt_q["remedy_score"]

    def test_submission_flips_the_branch_and_reverses_the_ranking(self):
        """The same pair swaps places once the action level is exceeded.

        PRD: "The two branches are emphatically not a rescaling of one another: the same pair of alternatives can rank in opposite orders under the two weightings, which is why re-submitting an investigation re-scores every one of its alternatives rather than only the newly added one."

        Design: Corner/calculations/corner_remedy_score_branch_flips_the_ranking_when_the_action_level_is_exceeded
        """
        world = _rushmere_two_alternatives()
        ri_id = world["investigation"]["id"]

        submitted = submit_investigation(ri_id)
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["action_level_exceeded"] is True

        investigation = read_investigation(ri_id)
        assert_epc(
            investigation["central_tendency_epc_ug_per_l"],
            25.000,
            "central_tendency_epc_ug_per_l",
        )
        assert_epc(investigation["rme_epc_ug_per_l"], 25.0, "rme_epc_ug_per_l")
        assert_seven_decimal_risk(investigation["rme_risk"], 0.0001250, "rme_risk")
        assert_percentage(investigation["hazard_index"], 5.00, "hazard_index")

        rescored = _by_id(alternatives_of(ri_id))
        alt_p = rescored[world["alt_p"]["id"]]
        alt_q = rescored[world["alt_q"]["id"]]
        assert_percentage(alt_p["remedy_score"], 71.30, "remedy_score P")
        assert_percentage(alt_q["remedy_score"], 74.00, "remedy_score Q")
        assert alt_q["remedy_score"] > alt_p["remedy_score"]

        # Only the weighting branch moved: the cost inputs are immutable.
        assert alt_p["npv_cents"] == 1_000_000_000
        assert alt_q["npv_cents"] == 2_500_000_000
        assert_percentage(alt_p["cost_score"], 80.00, "cost_score P")
        assert_percentage(alt_q["cost_score"], 50.00, "cost_score Q")
