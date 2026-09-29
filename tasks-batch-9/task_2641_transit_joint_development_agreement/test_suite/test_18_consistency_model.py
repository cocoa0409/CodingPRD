"""Visibility checks: the cascade a write reports in its own response, and what the
very next read shows with no retry in between."""

from test_helpers import (
    assert_money,
    assert_score,
    award_payload,
    build_context,
    close_solicitation,
    create_valuation_payload,
    validate_paginated,
    validate_success,
)

ELDERBERRY_SITE = {
    "site_code": "TJD-C-059",
    "name": "Elderberry Reach Parcel",
    "address_line": "59 Elderberry Rch",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


class TestAwardCascadeIsVisibleImmediately:
    """One award call, then one read of each record it touched — in that order and
    nothing else."""

    def test_every_hop_and_every_derived_figure_shows_on_the_first_read(
            self, api, real_estate_officer, valuation_officer):
        """PRD §3.3 pins the figure the create response itself must carry, in its own
        worked case: "a `GROUND_LEASE` proposal offering 2,400,000 cents of annual
        rent, with 50 affordable units out of 200 total, 600 boardings of ridership
        uplift and a design compliance score of 88, responding to a solicitation with
        a benchmark of 48,500,000 cents and an affordable minimum of 15 percent, from a
        prequalified developer" scores "the `evaluation_score` is 84.79". PRD §3.4 then
        runs the cascade: "The solicitation moves `CLOSED → AWARDED`. The awarded
        proposal moves `SUBMITTED → SELECTED` or `SHORTLISTED → SELECTED` (hop 1).
        Because that proposal became `SELECTED`, a new exclusive negotiation period is
        created over the supplied interval with `status` `ACTIVE`, `extension_count` 0,
        `start_date` from `negotiation_start_date` and `end_date` from
        `negotiation_end_date` (hop 2). Because that period became `ACTIVE`, the site
        moves `SOLICITATION_READY → UNDER_AGREEMENT` with its `version` bumped by 1
        (hop 3)", the ranking having been fixed at close: "Ranks are then assigned as
        contiguous integers starting at 1 with no gaps." The appraisal that follows
        reports its own arithmetic — PRD §3.2 makes the credit "the appraised value
        multiplied by that final rate, rounded half up to a whole cent" and the floor
        "the appraised value less the transit-supportive credit, but never below the
        federal interest floor — whichever of those two figures is larger wins" — and
        the ledger it writes is readable at once: "The site's
        `federal_interest_basis_cents` is set to the appraised value multiplied by
        `federal_interest_pct` and divided by 100, rounded half up, and
        `federal_interest_unencumbered_cents` is recomputed as that basis less whatever
        is already in `federal_interest_encumbered_cents`".

        Design: Corner/consistency_model/corner_award_cascade_visible_in_the_same_response_and_immediate_reads
        """
        ctx = build_context(stage="PROPOSAL",
                            site_overrides=dict(ELDERBERRY_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={
                                "benchmark_value_cents": 48_500_000,
                                "affordable_housing_min_pct": 15})
        site_id = ctx["site"]["id"]
        proposal_id = ctx["proposal"]["id"]
        assert_score(ctx["proposal"]["evaluation_score"], 84.79,
                     "evaluation_score")
        assert close_solicitation(ctx["solicitation"]["id"])["status"] == "CLOSED"

        awarded = validate_success(api.award_solicitation(
            ctx["solicitation"]["id"],
            award_payload(proposal_id, negotiation_start_date="2026-08-15",
                          negotiation_end_date="2027-01-15"),
            real_estate_officer))

        assert awarded["status"] == "AWARDED"
        proposal = validate_success(api.get_proposal(proposal_id,
                                                    real_estate_officer))
        assert proposal["status"] == "SELECTED"
        assert proposal["rank"] == 1
        periods, meta = validate_paginated(api.list_negotiation_periods(
            real_estate_officer, params={"site_id": site_id}))
        assert meta["total_count"] == 1
        assert periods[0]["status"] == "ACTIVE"
        assert periods[0]["end_date"] == "2027-01-15"
        site = validate_success(api.get_site(site_id, real_estate_officer))
        assert site["status"] == "UNDER_AGREEMENT"
        valuation = validate_success(api.create_valuation(
            site_id,
            create_valuation_payload(site["version"],
                                     method="INCOME_APPROACH",
                                     appraised_value_cents=48_500_000,
                                     transit_supportive_use_pct=60,
                                     affordable_units_pct=25,
                                     transfer_basis="TRANSIT_SUPPORTIVE_BELOW_MARKET",
                                     effective_date="2026-08-20"),
            valuation_officer), expected_status=201)
        assert_money(valuation["transit_supportive_credit_cents"], 12_125_000,
                     "transit_supportive_credit_cents")
        assert_money(valuation["permissible_floor_cents"], 36_375_000,
                     "permissible_floor_cents")
        priced = validate_success(api.get_site(site_id, valuation_officer))
        assert_money(priced["federal_interest_basis_cents"], 1_212_500,
                     "federal_interest_basis_cents")
        assert_money(priced["federal_interest_unencumbered_cents"], 1_212_500,
                     "federal_interest_unencumbered_cents")
