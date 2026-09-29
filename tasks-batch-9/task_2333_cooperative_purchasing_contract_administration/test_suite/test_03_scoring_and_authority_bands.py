"""Weighted evaluation scoring and the doctrine-dependent authority bands."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    OFFICER_CONDUCTOR,
    assert_deduction_detail,
    assert_instant,
    assert_score,
)
from test_helpers.factories import CA_RULE, ID_RULE, OK_RULE, OR_RULE, TX_RULE
from test_helpers.fixtures import (
    determine_analysis,
    open_analysis,
    read_response,
    read_solicitation,
    setup_active_contract,
    setup_active_member,
    setup_evaluated_solicitation,
)

RIVERSIDE = dict(
    legal_name="Riverside Unified School District",
    state_code="CA",
    member_category="K12_DISTRICT",
    governing_body_resolution_number="RES-2026-114",
)
CASCADE = dict(
    legal_name="Cascade Regional Library District",
    state_code="OR",
    member_category="SPECIAL_DISTRICT",
    governing_body_resolution_number="RES-OR-2026-041",
)
SAWTOOTH = dict(
    legal_name="Sawtooth Joint School District",
    state_code="ID",
    member_category="K12_DISTRICT",
    governing_body_resolution_number="RES-ID-2026-052",
)
RED_DIRT = dict(
    legal_name="Red Dirt County",
    state_code="OK",
    member_category="COUNTY",
    governing_body_resolution_number="RES-OK-2026-063",
)


def _scored_field(api):
    """Two responsive bids on a 40/60 weighted solicitation, scored by the recommendation."""
    world = setup_evaluated_solicitation(
        api,
        value_a=1000000,
        value_b=712900,
        title="Grounds Maintenance Equipment",
        solicitation_number="COOP-2026-002",
        technical_weight_pct=40.00,
        price_weight_pct=60.00,
        specification_document_ref="SPEC-COOP-2026-002",
        method_justification_ref="METH-COOP-2026-002",
    )
    get_success_data(
        api.response_review(
            world["response_a"]["id"],
            {"action": "MARK_RESPONSIVE", "technical_score": 88.43},
            OFFICER_CONDUCTOR,
        )
    )
    get_success_data(
        api.response_review(
            world["response_b"]["id"],
            {"action": "MARK_RESPONSIVE", "technical_score": 70.00},
            OFFICER_CONDUCTOR,
        )
    )
    world["solicitation"] = get_success_data(
        api.solicitation_lifecycle(
            world["solicitation"]["id"], {"action": "RECOMMEND_AWARD"}, OFFICER_CONDUCTOR
        )
    )
    return world


def _two_doctrine_world(api):
    """The TX-led award seen from a strict state and from a reciprocity state."""
    world = setup_active_contract(api, rules=(TX_RULE, CA_RULE, OR_RULE))
    world["riverside"] = setup_active_member(api, **RIVERSIDE)
    world["cascade"] = setup_active_member(api, **CASCADE)
    return world


def _band_edge_world(api):
    """Three members tuned onto the two inclusive band edges and below them."""
    world = setup_active_contract(api, rules=(TX_RULE, OR_RULE, ID_RULE, OK_RULE))
    world["cascade"] = setup_active_member(api, **CASCADE)
    world["sawtooth"] = setup_active_member(api, **SAWTOOTH)
    world["red_dirt"] = setup_active_member(api, **RED_DIRT)
    return world


def _determined(api, world, member_key):
    member = world[member_key]
    analysis = open_analysis(api, member["id"], world["contract"]["id"])
    return determine_analysis(api, analysis["id"])


class TestWeightedCompositeScoring:
    def test_01_the_cheapest_responsive_bid_anchors_the_price_score(self, api):
        """PRD §3.2: "Then, walking the set in ascending `created_at` order, give each
        response a `price_score` of one hundred multiplied by that smallest proposed
        value and divided by this response's own `proposed_annual_value_cents`, rounded
        half up to two decimals — so the cheapest bid scores 100.00 and a bid twice as
        expensive scores 50.00."

        Design: Difficulty/combinatorial_formula/composite_score_rounds_each_weighted_component_before_summing
        """
        world = _scored_field(api)

        cheapest = read_response(api, world["response_b"]["id"])
        dearest = read_response(api, world["response_a"]["id"])
        assert_score(cheapest["price_score"], 100.00, "price_score")
        assert_score(dearest["price_score"], 71.29, "price_score")

    def test_02_each_weighted_component_is_rounded_before_the_two_are_added(self, api):
        """PRD §3.2: "`composite_score` is the sum of those two *already-rounded*
        components, rounded half up to two decimals."

        Design: Difficulty/combinatorial_formula/composite_score_rounds_each_weighted_component_before_summing
        """
        world = _scored_field(api)

        dearest = read_response(api, world["response_a"]["id"])
        assert_score(dearest["composite_score"], 78.14, "composite_score")

    def test_03_summing_the_unrounded_products_is_explicitly_not_the_rule(self, api):
        """PRD §3.2: "Rounding each component first and adding afterwards is the rule;
        adding the two unrounded products and rounding once at the end is explicitly not
        the rule and differs by one hundredth whenever both products carry a third
        decimal digit that rounds up together."

        Design: Difficulty/combinatorial_formula/composite_score_rounds_each_weighted_component_before_summing
        """
        world = _scored_field(api)

        dearest = read_response(api, world["response_a"]["id"])
        assert dearest["composite_score"] != 78.15, dearest["composite_score"]
        assert_score(dearest["composite_score"], 78.14, "composite_score")

    def test_04_the_field_is_ranked_by_composite_score_descending(self, api):
        """PRD §3.2: "Finally rank the same responsive set by `composite_score`
        descending, breaking ties by `created_at` ascending and never by `id`, and write
        `award_rank` as 1 through N."

        Design: Difficulty/combinatorial_formula/composite_score_rounds_each_weighted_component_before_summing
        """
        world = _scored_field(api)

        cheapest = read_response(api, world["response_b"]["id"])
        dearest = read_response(api, world["response_a"]["id"])
        assert_score(cheapest["composite_score"], 88.00, "composite_score")
        assert cheapest["award_rank"] == 1
        assert dearest["award_rank"] == 2
        assert read_solicitation(api, world["solicitation"]["id"])["responsive_response_count"] == 2


class TestDoctrineDivergence:
    def test_05_a_strict_state_charges_thirty_points_for_an_out_of_state_lead(self, api):
        """PRD §3.5: "Under `STATUTORY_STRICT`, the four tests fire in this sequence: if
        the state sets `requires_lead_agency_in_state` to true and the solicitation's
        `lead_agency_state_code` differs from the member's `state_code`, append
        `OUT_OF_STATE_LEAD` worth 30.00; if the solicitation's frozen `notice_days` is
        strictly below the state's `min_notice_days`, append `SHORT_NOTICE` worth the
        smaller of 25.00 and five points for each day of shortfall (the shortfall being
        `min_notice_days` minus `notice_days`); if the contract's total term in months
        exceeds the state's `max_contract_term_months`, append `TERM_EXCEEDS_STATE_MAX`
        worth 20.00; and if the member's `member_category` is `NONPROFIT_501C3` while the
        state's `allows_nonprofit_participation` is false, append
        `NONPROFIT_NOT_PERMITTED` worth 40.00."

        Design: Difficulty/dual_variant_calc/piggyback_authority_strict_versus_liberal_determination_band_divergence
        """
        world = _two_doctrine_world(api)
        assert read_solicitation(api, world["solicitation"]["id"])["notice_days"] == 21

        analysis = _determined(api, world, "riverside")

        assert analysis["doctrine_applied"] == "STATUTORY_STRICT"
        assert_deduction_detail(analysis["deduction_detail"], [("OUT_OF_STATE_LEAD", 30.00)])
        assert_score(analysis["authority_score"], 70.00, "authority_score")
        assert analysis["determination"] == "CONDITIONAL"

    def test_06_a_reciprocity_state_charges_fifteen_for_the_identical_fact(self, api):
        """PRD §3.5: "Under `RECIPROCITY_LIBERAL` the same four tests fire in the same
        sequence but score differently, and the first one changes shape: if the
        solicitation's `lead_agency_state_code` differs from the member's `state_code`
        *and* is not listed in the state's `reciprocity_state_codes`, append
        `OUT_OF_STATE_LEAD` worth 15.00 — a lead state that appears in the reciprocity
        list costs nothing at all, and `requires_lead_agency_in_state` is not consulted."

        Design: Difficulty/dual_variant_calc/piggyback_authority_strict_versus_liberal_determination_band_divergence
        """
        world = _two_doctrine_world(api)

        analysis = _determined(api, world, "cascade")

        assert analysis["doctrine_applied"] == "RECIPROCITY_LIBERAL"
        assert_deduction_detail(analysis["deduction_detail"], [("OUT_OF_STATE_LEAD", 15.00)])
        assert_score(analysis["authority_score"], 85.00, "authority_score")
        assert analysis["determination"] == "AUTHORIZED"

    def test_07_identical_contract_facts_land_in_two_different_bands(self, api):
        """PRD §3.5: "Identical member and contract facts therefore land in different
        bands under the two doctrines, which is the point."

        Design: Difficulty/dual_variant_calc/piggyback_authority_strict_versus_liberal_determination_band_divergence
        """
        world = _two_doctrine_world(api)

        strict = _determined(api, world, "riverside")
        liberal = _determined(api, world, "cascade")

        assert strict["determination"] == "CONDITIONAL"
        assert liberal["determination"] == "AUTHORIZED"
        assert_instant(strict["expires_on"], "2027-09-01T00:00:00Z", "expires_on")
        assert liberal["local_waiver_required"] is False


class TestInclusiveAuthorityBands:
    def test_08_exactly_eighty_five_points_is_authorized(self, api):
        """PRD §3.5: "`determination` bands the score with two inclusive thresholds: a
        score of 85.00 or more is `AUTHORIZED`, a score of 60.00 or more but below 85.00
        is `CONDITIONAL`, and anything below 60.00 is `DENIED` — so exactly 85.00 is
        `AUTHORIZED` and exactly 60.00 is `CONDITIONAL`."

        Design: Difficulty/boundary_precision_check/authority_bands_are_inclusive_at_exactly_eighty_five_and_sixty
        """
        world = _band_edge_world(api)

        analysis = _determined(api, world, "cascade")

        assert_score(analysis["authority_score"], 85.00, "authority_score")
        assert analysis["determination"] == "AUTHORIZED"
        assert analysis["doctrine_applied"] == "RECIPROCITY_LIBERAL"
        assert_deduction_detail(analysis["deduction_detail"], [("OUT_OF_STATE_LEAD", 15.00)])

    def test_09_exactly_sixty_points_is_conditional(self, api):
        """PRD §3.5: "`authority_score` is 100.00 less the sum of the appended points,
        floored at 0.00 and carried to two decimals with half-up rounding."

        Design: Difficulty/boundary_precision_check/authority_bands_are_inclusive_at_exactly_eighty_five_and_sixty
        """
        world = _band_edge_world(api)

        analysis = _determined(api, world, "sawtooth")

        assert_deduction_detail(
            analysis["deduction_detail"],
            [("OUT_OF_STATE_LEAD", 30.00), ("SHORT_NOTICE", 10.00)],
        )
        assert_score(analysis["authority_score"], 60.00, "authority_score")
        assert analysis["determination"] == "CONDITIONAL"
        assert analysis["doctrine_applied"] == "STATUTORY_STRICT"

    def test_10_the_strict_notice_penalty_is_clamped_at_twenty_five_points(self, api):
        """PRD §3.5: "if the solicitation's frozen `notice_days` is strictly below the
        state's `min_notice_days`, append `SHORT_NOTICE` worth the smaller of 25.00 and
        five points for each day of shortfall (the shortfall being `min_notice_days`
        minus `notice_days`)"

        Design: Difficulty/boundary_precision_check/authority_bands_are_inclusive_at_exactly_eighty_five_and_sixty
        """
        world = _band_edge_world(api)

        analysis = _determined(api, world, "red_dirt")

        assert_deduction_detail(
            analysis["deduction_detail"],
            [("OUT_OF_STATE_LEAD", 30.00), ("SHORT_NOTICE", 25.00)],
        )
        assert_score(analysis["authority_score"], 45.00, "authority_score")
        assert analysis["determination"] == "DENIED"
