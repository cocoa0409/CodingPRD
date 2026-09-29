"""Endpoint-surface probes: composed list queries, action writes, derived reads.

These exercise the endpoints themselves — how filters compose with paging on the
site index, what an action write leaves behind when it accepts less than was
claimed, and what the single reconciliation read reports before any allocation
has been adopted.
"""
from test_helpers import api_client, factories
from test_helpers.assertions import (
    assert_ids_in_order,
    assert_ledger_figures,
    assert_pagination_meta,
    assert_percentage,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_waste_in,
    create_participating_party,
    create_site,
    list_site_on_npl,
    read_ledger,
    read_party,
    read_site,
    set_clock,
)
from test_helpers.test_users import AUTHOR_PM_ID, TEST_USERS, make_project_manager_headers

AUTHOR = TEST_USERS["author_pm_headers"]
COMMUNITY = TEST_USERS["community_headers"]


def _three_sites_in_a_known_order():
    """Three sites created a minute apart: two in region 5, one in region 9.

    Only the region 5 site scoring 40.00 and the region 9 site are listed; the
    region 5 site scoring 30.00 stays proposed.
    """
    set_clock("2027-01-04T08:00:00Z")
    site_1 = create_site(name="Alder Bay Shipyard", epa_region=5, hrs_score=40.00)
    set_clock("2027-01-04T08:01:00Z")
    site_2 = create_site(
        name="Bramble Lane Dry Cleaner", epa_region=5, hrs_score=30.00
    )
    set_clock("2027-01-04T08:02:00Z")
    site_3 = create_site(
        name="Cinnabar Mesa Mill Tailings", epa_region=9, hrs_score=60.00
    )
    list_site_on_npl(site_1["id"], listing_reference="FR-2027-ABS-0104")
    list_site_on_npl(site_3["id"], listing_reference="FR-2027-CMM-0104")
    return {"site_1": site_1, "site_2": site_2, "site_3": site_3}


class TestSiteListFiltersAndPagination:
    def test_two_filters_compose_and_total_count_is_the_filtered_population(self):
        """The listed region 5 site is the only row that satisfies both filters.

        PRD: "Sites can be narrowed by `listing_status`, `epa_region` or `cost_posture`."

        Design: Corner/endpoints/corner_site_list_filters_combine_with_pagination
        """
        world = _three_sites_in_a_known_order()

        rows, meta = validate_paginated(
            api_client.list_sites(
                AUTHOR, {"listing_status": "LISTED", "epa_region": 5}
            )
        )
        assert_ids_in_order(rows, [world["site_1"]["id"]])
        assert_pagination_meta(meta, total_count=1, has_more=False)

        # Every site is OPEN: none has a governing decree, an over-utilised cap
        # or a pending amendment.
        open_rows, open_meta = validate_paginated(
            api_client.list_sites(AUTHOR, {"cost_posture": "OPEN", "limit": 100})
        )
        assert open_meta["total_count"] == 3
        assert len(open_rows) == 3

    def test_the_first_page_of_the_unfiltered_index_is_newest_first(self):
        """The site index deviates from the default ordering.

        PRD: "The top-level site list is ordered by `created_at` **descending**, with `name` ascending as the tie-break."

        Design: Corner/endpoints/corner_site_list_filters_combine_with_pagination
        """
        world = _three_sites_in_a_known_order()

        response = api_client.list_sites(AUTHOR, {"limit": 2, "offset": 0})
        rows, meta = validate_paginated(response)
        assert_ids_in_order(rows, [world["site_3"]["id"], world["site_2"]["id"]])
        assert_pagination_meta(
            meta, total_count=3, has_more=True, limit=2, offset=0
        )
        assert response.json()["meta"]["api_request_id"]


def _draper_hollow_submitted_claim():
    """One participating party with a single unverified 500-ton class III claim."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(
        name="Draper Hollow Pigment Works", epa_region=3, hrs_score=41.90
    )
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-DHP-0201")
    party = create_participating_party(
        site["id"],
        legal_name="Draper Pigment Co",
        party_type="OWNER_OPERATOR",
        viability_score=66,
    )
    record = add_waste_in(
        site["id"],
        party["id"],
        volume_tons=500,
        toxicity_class="III",
        evidence_grade="B",
        disposal_year=1980,
        transporter_name="Havers Bulk Haulage",
    )
    return {"site": site, "party": party, "record": record}


def _verify_at_three_hundred(record_id):
    return validate_success(
        api_client.verify_waste_in_record(
            record_id,
            factories.verification_payload(
                decision="VERIFIED",
                verified_volume_tons=300,
                verification_note="Two of five manifests were duplicates.",
            ),
            make_project_manager_headers(AUTHOR_PM_ID),
        )
    )


class TestVerificationAtAReducedVolume:
    def test_a_verification_below_the_claim_is_accepted(self):
        """Three hundred tons against a five-hundred-ton claim is allowed.

        PRD: "A verification must carry `verified_volume_tons`, which must be strictly positive and no greater than the record's claimed `volume_tons` — verification may accept less volume than was claimed, but never more."

        Design: Corner/endpoints/corner_verification_at_a_reduced_volume_rewrites_the_derived_totals
        """
        world = _draper_hollow_submitted_claim()

        verified = _verify_at_three_hundred(world["record"]["id"])
        assert verified["status"] == "VERIFIED"
        assert verified["verified_volume_tons"] == 300
        assert verified["volume_tons"] == 500
        assert verified["effective_volume_tons"] == 300
        assert verified["verified_by_user_id"] == AUTHOR_PM_ID

        assert read_site(world["site"]["id"])["verified_waste_volume_tons"] == 300

    def test_the_party_totals_follow_the_verified_figure_not_the_claim(self):
        """The party's own totals are re-derived from its verified records.

        PRD: "The attributed party's `submitted_volume_tons` is re-derived as the sum of `effective_volume_tons` over its records that are either submitted or verified; its `verified_volume_tons` as the sum of `verified_volume_tons` over its verified records only; its `max_toxicity_class` as the most hazardous class across its verified records, where class `I` outranks `II`, which outranks `III`, which outranks `IV`, and which is left empty when the party holds no verified record at all."

        Design: Corner/endpoints/corner_verification_at_a_reduced_volume_rewrites_the_derived_totals
        """
        world = _draper_hollow_submitted_claim()
        _verify_at_three_hundred(world["record"]["id"])

        party = read_party(world["party"]["id"])
        assert party["verified_volume_tons"] == 300
        assert party["submitted_volume_tons"] == 300
        assert party["max_toxicity_class"] == "III"
        assert_percentage(
            party["volumetric_share_pct"], 100.00, "volumetric_share_pct"
        )

    def test_the_sole_contributor_is_not_de_minimis_eligible(self):
        """The class test passes but both quantitative ceilings fail.

        PRD: "A party qualifies as `de_minimis_eligible` only when all of the following hold together: its `volumetric_share_pct` is at most 1.00 percent, its `max_toxicity_class` is either `III` or `IV`, its `verified_volume_tons` is at most 110.00 tons, and its `max_toxicity_class` is not empty — which is to say a party holding no verified record is never eligible, however small its claim."

        Design: Corner/endpoints/corner_verification_at_a_reduced_volume_rewrites_the_derived_totals
        """
        world = _draper_hollow_submitted_claim()
        _verify_at_three_hundred(world["record"]["id"])

        party = read_party(world["party"]["id"])
        assert party["de_minimis_eligible"] is False
        assert party["volumetric_share_pct"] > 1.00
        assert party["verified_volume_tons"] > 110.00


def _sorrel_gap_single_posting():
    """A listed site whose only cost event is one oversight posting."""
    set_clock("2027-05-19T08:00:00Z")
    site = create_site(name="Sorrel Gap Uranium Mill", epa_region=8, hrs_score=57.60)
    site = list_site_on_npl(site["id"], listing_reference="FR-2027-SGU-0519")
    validate_success(
        api_client.post_oversight_cost(
            site["id"],
            factories.oversight_cost_payload(
                incurred_cents=9_000_000,
                cost_category="RI_FS_OVERSIGHT",
                incurred_on="2027-05-19",
            ),
            AUTHOR,
        )
    )
    return site


class TestCostLedgerRead:
    def test_the_reconciliation_read_reports_all_thirteen_figures(self):
        """One posting, no contract and no decree still reconciles.

        PRD: "That read returns `total_response_cost_cents`, `recovered_cost_cents`, `orphan_write_off_cents`, `unrecovered_cost_cents`, `oversight_direct_cents`, `oversight_indirect_rate_bp`, `oversight_indirect_cents`, `oversight_billed_cents`, `oversight_cap_utilization_pct`, `allocated_share_total_pct`, `orphan_share_pct`, `settled_share_pct`, and a boolean `ledger_balanced` asserting that the conservation identity currently holds."

        Design: Corner/endpoints/corner_cost_ledger_read_balances_before_any_round_is_adopted
        """
        site = _sorrel_gap_single_posting()
        version_before = read_site(site["id"])["version"]

        ledger = read_ledger(site["id"], COMMUNITY)
        assert ledger["oversight_direct_cents"] == 9_000_000
        assert ledger["oversight_indirect_rate_bp"] == 1275
        assert ledger["oversight_indirect_cents"] == 1_147_500
        assert ledger["oversight_billed_cents"] == 10_147_500
        assert ledger["oversight_cap_utilization_pct"] is None
        assert_ledger_figures(
            ledger,
            total=10_147_500,
            recovered=0,
            orphan=0,
            unrecovered=10_147_500,
        )

        # The read derives; it does not write.
        assert read_site(site["id"])["version"] == version_before

    def test_the_share_triple_reads_zero_until_a_round_is_adopted(self):
        """The share identity only exists once a round has been adopted.

        PRD: "On the allocation side there is a matching identity: for an adopted round, `allocated_share_total_pct` plus `orphan_share_pct` plus `settled_share_pct` equals exactly 100.00."

        Design: Corner/endpoints/corner_cost_ledger_read_balances_before_any_round_is_adopted
        """
        site = _sorrel_gap_single_posting()

        ledger = read_ledger(site["id"])
        assert_percentage(
            ledger["allocated_share_total_pct"], 0.00, "allocated_share_total_pct"
        )
        assert_percentage(ledger["orphan_share_pct"], 0.00, "orphan_share_pct")
        assert_percentage(ledger["settled_share_pct"], 0.00, "settled_share_pct")
        assert ledger["ledger_balanced"] is True
