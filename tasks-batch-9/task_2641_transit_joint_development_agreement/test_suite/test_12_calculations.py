"""Arithmetic checks: the worked cases the PRD pins, the constants it names, the
input sets a computation is allowed to see, and where it rounds."""

from test_helpers import (
    assert_money,
    assert_score,
    build_assessment,
    build_context,
    build_developer,
    build_site,
    certify_assessment,
    create_fee_proposal_payload,
    create_proposal_payload,
    create_valuation_payload,
    make_developer_headers,
    read_site,
    set_logical_clock,
    shortlist_proposal,
    validate_success,
)

CEDAR_HILL_SITE = {
    "site_code": "TJD-C-014",
    "name": "Cedar Hill Parcel",
    "address_line": "14 Cedar Hill",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


class TestProposalEvaluationScore:
    """The PRD's own worked proposal, and the same proposal from a developer who
    never prequalified."""

    def test_the_worked_proposal_scores_the_published_figure(
            self, api, real_estate_officer):
        """PRD §3.3 works this exact case: "a `GROUND_LEASE` proposal offering
        2,400,000 cents of annual rent, with 50 affordable units out of 200 total,
        600 boardings of ridership uplift and a design compliance score of 88,
        responding to a solicitation with a benchmark of 48,500,000 cents and an
        affordable minimum of 15 percent, from a prequalified developer. Its
        `affordable_pct` is 25.00; value points are 39.59 (below the 40.00 cap);
        affordable points are 15.00 plus half a point for each of the ten
        percentage points of headroom, giving 20.00; ridership points are 12.00;
        design points are 13.20; the raw sum is 84.79, the penalty is 0.00, and
        the `evaluation_score` is 84.79." PRD §3.3 adds where the record lands: "A
        submitted proposal lands in `SUBMITTED` with `rank` null, and the parent
        solicitation's `responsive_proposal_count` is incremented by 1."

        Design: Corner/calculations/corner_proposal_evaluation_score_correct_result
        """
        ctx = build_context(stage="SOLICITATION_ISSUED",
                            site_overrides=dict(CEDAR_HILL_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={
                                "benchmark_value_cents": 48_500_000,
                                "affordable_housing_min_pct": 15})

        response = api.create_proposal(
            ctx["solicitation"]["id"],
            create_proposal_payload(ctx["developer"]["id"],
                                    proposed_structure="GROUND_LEASE",
                                    proposed_annual_rent_cents=2_400_000,
                                    affordable_units=50, total_units=200,
                                    transit_ridership_uplift=600,
                                    design_compliance_score=88,
                                    joint_use_committed=False),
            make_developer_headers(ctx["developer"]["id"]))

        proposal = validate_success(response, expected_status=201)
        assert_score(proposal["affordable_pct"], 25.00, "affordable_pct")
        assert_score(proposal["evaluation_score"], 84.79, "evaluation_score")
        assert proposal["rank"] is None
        assert proposal["status"] == "SUBMITTED"
        solicitation = validate_success(api.get_solicitation(
            ctx["solicitation"]["id"], real_estate_officer))
        assert solicitation["responsive_proposal_count"] == 1

    def test_the_same_proposal_from_an_unprequalified_developer_loses_ten_points(
            self, api):
        """PRD §3.3: "From that raw sum a flat penalty of ten points is subtracted
        when the developer's `prequalified` flag is false, and nothing is
        subtracted when it is true; the difference is rounded half up to two
        decimal places, and a negative result is recorded as 0.00." The raw sum for
        these inputs is the PRD's own 84.79 — "the raw sum is 84.79, the penalty is
        0.00, and the `evaluation_score` is 84.79" — so the unprequalified partner
        scores 74.79 from identical inputs.

        Design: Corner/calculations/corner_prequalification_penalty_constant_applied
        """
        ctx = build_context(stage="SOLICITATION_ISSUED",
                            site_overrides=dict(CEDAR_HILL_SITE),
                            developer_overrides={
                                "legal_name": "Elm Gateway Partners LLC",
                                "contact_email": "dev-e@example.com",
                                "prequalified": False,
                                "debarment_status": "CLEAR"},
                            solicitation_overrides={
                                "benchmark_value_cents": 48_500_000,
                                "affordable_housing_min_pct": 15})
        assert ctx["developer"]["prequalified"] is False

        response = api.create_proposal(
            ctx["solicitation"]["id"],
            create_proposal_payload(ctx["developer"]["id"],
                                    proposed_structure="GROUND_LEASE",
                                    proposed_annual_rent_cents=2_400_000,
                                    affordable_units=50, total_units=200,
                                    transit_ridership_uplift=600,
                                    design_compliance_score=88,
                                    joint_use_committed=False),
            make_developer_headers(ctx["developer"]["id"]))

        proposal = validate_success(response, expected_status=201)
        assert_score(proposal["affordable_pct"], 25.00, "affordable_pct")
        assert_score(proposal["evaluation_score"], 74.79, "evaluation_score")


class TestProposalRanking:
    """Which proposals are candidates for a rank, and in what order."""

    def test_a_shortlisted_proposal_stays_in_the_candidate_set_and_ranks_second(
            self, api, real_estate_officer):
        """PRD §3.4: "On success the solicitation moves `ISSUED → CLOSED` and every
        responsive proposal is assigned a `rank`. The candidate set is exactly
        those proposals whose status is `SUBMITTED` or `SHORTLISTED`; proposals
        already `SELECTED` or `REJECTED` at close time are excluded and keep `rank`
        null. Candidates are ordered by `evaluation_score` descending; ties are
        broken by `affordable_pct` descending; remaining ties are broken by
        `created_at` ascending. The UUID `id` never participates in the ordering
        under any circumstance. Ranks are then assigned as contiguous integers
        starting at 1 with no gaps." PRD §3.4 also fixes the count: "The system
        first recomputes `responsive_proposal_count` as the number of this
        solicitation's proposals whose status is `SUBMITTED` or `SHORTLISTED`", and
        PRD §3.3 confirms a shortlisted proposal still counts: "a `SHORTLISTED`
        proposal is still counted as responsive."

        Design: Corner/calculations/corner_proposal_ranking_candidate_set_includes_shortlisted
        """
        ctx = build_context(stage="SOLICITATION_ISSUED",
                            site_overrides=dict(CEDAR_HILL_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={
                                "benchmark_value_cents": 48_500_000,
                                "affordable_housing_min_pct": 15,
                                "min_proposals_required": 1})
        solicitation_id = ctx["solicitation"]["id"]
        developer_b = build_developer(legal_name="Birch Union Development Co",
                                      contact_email="dev-b@example.com",
                                      prequalified=True,
                                      debarment_status="CLEAR")
        developer_c = build_developer(legal_name="Cypress Transit Holdings LLC",
                                      contact_email="dev-c@example.com",
                                      prequalified=True,
                                      debarment_status="CLEAR")
        proposal_a = validate_success(api.create_proposal(
            solicitation_id,
            create_proposal_payload(ctx["developer"]["id"],
                                    proposed_annual_rent_cents=2_400_000,
                                    affordable_units=50, total_units=200,
                                    transit_ridership_uplift=600,
                                    design_compliance_score=88,
                                    joint_use_committed=False),
            make_developer_headers(ctx["developer"]["id"])), expected_status=201)
        proposal_b = validate_success(api.create_proposal(
            solicitation_id,
            create_fee_proposal_payload(developer_b["id"],
                                        proposed_purchase_price_cents=42_000_000,
                                        affordable_units=36, total_units=180,
                                        transit_ridership_uplift=1200,
                                        design_compliance_score=70,
                                        joint_use_committed=False),
            make_developer_headers(developer_b["id"])), expected_status=201)
        proposal_c = validate_success(api.create_proposal(
            solicitation_id,
            create_proposal_payload(developer_c["id"],
                                    proposed_annual_rent_cents=1_800_000,
                                    affordable_units=30, total_units=150,
                                    transit_ridership_uplift=400,
                                    design_compliance_score=65,
                                    joint_use_committed=False),
            make_developer_headers(developer_c["id"])), expected_status=201)
        assert_score(proposal_a["evaluation_score"], 84.79, "evaluation_score")
        assert_score(proposal_b["evaluation_score"], 82.64, "evaluation_score")
        assert_score(proposal_c["evaluation_score"], 64.94, "evaluation_score")
        assert shortlist_proposal(proposal_b["id"])["status"] == "SHORTLISTED"

        closed = validate_success(api.close_solicitation(solicitation_id,
                                                        real_estate_officer))

        assert closed["status"] == "CLOSED"
        assert closed["responsive_proposal_count"] == 3
        ranks = {}
        for proposal in (proposal_a, proposal_b, proposal_c):
            ranks[proposal["id"]] = validate_success(api.get_proposal(
                proposal["id"], real_estate_officer))["rank"]
        assert ranks[proposal_a["id"]] == 1
        assert ranks[proposal_b["id"]] == 2
        assert ranks[proposal_c["id"]] == 3


class TestPermissibleFloorCreditRate:
    """The credit rate lookup at its cap, and below its lowest tier."""

    def test_the_affordable_bonus_cannot_push_the_rate_past_its_cap(
            self, api, valuation_officer):
        """PRD §3.2: "A `transit_supportive_use_pct` of at least 75 earns a rate of
        thirty hundredths ... Second, an affordable-housing bonus of five hundredths
        is added to that rate whenever `affordable_units_pct` is at least 20, and
        the resulting rate is then capped at thirty hundredths — so a project
        already in the top tier gains nothing from the affordable bonus." The credit
        is then "the appraised value multiplied by that final rate, rounded half up
        to a whole cent", and `federal_interest_floor_cents` is "the appraised value
        multiplied by the site's `federal_interest_pct` and divided by 100". PRD
        §3.2 fixes the floor: "Under `TRANSIT_SUPPORTIVE_BELOW_MARKET` the floor is
        the appraised value less the transit-supportive credit, but never below the
        federal interest floor — whichever of those two figures is larger wins." PRD
        §3.2 adds that "A determination is created in `DRAFT` with `certified_at`
        null".

        Design: Corner/calculations/corner_permissible_floor_credit_rate_hits_declared_cap
        """
        ctx = build_context(stage="ASSESSED",
                            site_overrides=dict(CEDAR_HILL_SITE))

        response = api.create_valuation(
            ctx["site"]["id"],
            create_valuation_payload(ctx["site"]["version"],
                                     method="INCOME_APPROACH",
                                     appraised_value_cents=48_500_000,
                                     transit_supportive_use_pct=80,
                                     affordable_units_pct=25,
                                     transfer_basis="TRANSIT_SUPPORTIVE_BELOW_MARKET",
                                     effective_date="2026-08-20"),
            valuation_officer)

        valuation = validate_success(response, expected_status=201)
        assert_money(valuation["transit_supportive_credit_cents"], 14_550_000,
                     "transit_supportive_credit_cents")
        assert_money(valuation["federal_interest_floor_cents"], 1_212_500,
                     "federal_interest_floor_cents")
        assert_money(valuation["permissible_floor_cents"], 33_950_000,
                     "permissible_floor_cents")
        assert valuation["status"] == "DRAFT"
        assert valuation["transfer_basis"] == "TRANSIT_SUPPORTIVE_BELOW_MARKET"

    def test_a_project_below_the_lowest_tier_earns_no_credit_at_all(
            self, api, valuation_officer):
        """PRD §3.2: "A `transit_supportive_use_pct` of at least 75 earns a rate of
        thirty hundredths; at least 50 but below 75 earns twenty hundredths; at
        least 25 but below 50 earns ten hundredths; anything below 25 earns nothing
        at all", and the affordable bonus applies only "whenever
        `affordable_units_pct` is at least 20". With a rate of nothing the credit is
        nothing, and PRD §3.2's below-market floor — "the appraised value less the
        transit-supportive credit, but never below the federal interest floor" —
        collapses onto the full appraisal.

        Design: Corner/calculations/corner_permissible_floor_below_lowest_tier_gives_zero_credit
        """
        ctx = build_context(stage="ASSESSED",
                            site_overrides=dict(CEDAR_HILL_SITE))

        response = api.create_valuation(
            ctx["site"]["id"],
            create_valuation_payload(ctx["site"]["version"],
                                     method="COST_APPROACH",
                                     appraised_value_cents=48_500_000,
                                     transit_supportive_use_pct=20,
                                     affordable_units_pct=10,
                                     transfer_basis="TRANSIT_SUPPORTIVE_BELOW_MARKET",
                                     effective_date="2026-08-20"),
            valuation_officer)

        valuation = validate_success(response, expected_status=201)
        assert_money(valuation["transit_supportive_credit_cents"], 0,
                     "transit_supportive_credit_cents")
        assert_money(valuation["permissible_floor_cents"], 48_500_000,
                     "permissible_floor_cents")
        assert_money(valuation["appraised_value_cents"], 48_500_000,
                     "appraised_value_cents")


class TestReadinessRounding:
    """Where the single rounding step lands when the raw score is a hair under the
    READY boundary."""

    def test_a_raw_score_of_sixty_nine_point_nine_nine_five_rounds_up_to_ready(
            self, api, real_estate_officer):
        """PRD §3.1: "The weighted sum and both penalties are computed on unrounded
        operands; the two subtractions happen first, the result is rounded half up
        to two decimal places exactly once". The weighted sum of 80, 75, 70 and 60
        is 73.25, one encumbrance costs "three points for each recorded
        encumbrance", and the federal interest penalty is "one tenth of a point for
        each whole percent of `federal_interest_pct` on the parcel" — the PRD's own
        worked case pins that scale, since "sub-scores of 80, 75, 70 and 60 with one
        encumbrance on a parcel whose federal interest is two and a half percent
        yield a preliminary score of 71.25 and a certified score of 70.00". At 2.55
        percent the raw result is 69.995, which rounds half up to 70.00, and PRD
        §3.1 says "A score of at least 70.00 is `READY`" while "The `READY`
        boundary is inclusive on the lower side, so exactly 70.00 qualifies and
        69.99 does not". A `READY` parcel may then go to market: "Releasing a site
        for solicitation advances it `ASSESSED → SOLICITATION_READY`".

        Design: Corner/calculations/corner_readiness_score_round_half_up_at_third_decimal
        """
        set_logical_clock()
        site = build_site(site_code="TJD-C-015", name="Cedar Vale Parcel",
                          address_line="15 Cedar Vale", parcel_area_sqft=61000,
                          acquisition_funding_source="FEDERAL_GRANT",
                          federal_interest_pct=2.55,
                          transit_facility_present=False)
        assessment = build_assessment(site["id"], environmental_score=80,
                                      utility_score=75, access_score=70,
                                      entitlement_score=60, encumbrance_count=1)

        certified = validate_success(api.certify_assessment(assessment["id"],
                                                           real_estate_officer))

        assert certified["composite_score"] == 70.00
        assert certified["tier"] == "READY"
        released = validate_success(api.release_site_for_solicitation(
            site["id"], real_estate_officer))
        assert released["status"] == "SOLICITATION_READY"
        assert read_site(site["id"])["readiness_composite_score"] == 70.00
