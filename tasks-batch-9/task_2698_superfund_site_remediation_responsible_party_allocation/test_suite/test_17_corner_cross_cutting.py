"""Cross-cutting layers: the version guards that stand in front of a supersede.

Both mandatory guards are exercised on the endpoints that carry them — the
site's version in front of an allocation round, and the respondent party's
version in front of a recovery action — because on both the create legitimately
destroys an instrument the caller may never have seen.
"""
from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import (
    assert_pagination_meta,
    assert_percentage,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_waste_in,
    adopt_round,
    create_investigation,
    create_party,
    create_site,
    issue_notice,
    list_site_on_npl,
    open_round,
    post_oversight,
    prp_version,
    read_action,
    read_party,
    read_round,
    record_election,
    respond_to_action,
    set_clock,
    site_version,
    verify_waste_in,
)
from test_helpers.test_users import TEST_USERS

AUTHOR = TEST_USERS["author_pm_headers"]
FACILITATOR = TEST_USERS["facilitator_headers"]
COUNSEL = TEST_USERS["counsel_headers"]


def _kestrel_yard_with_one_drafting_round():
    """A round already open, and the site version the client read before it."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(
        name="Kestrel Yard Drum Reconditioning", epa_region=5, hrs_score=52.80
    )
    list_site_on_npl(site["id"], "FR-2027-KYD-0201")
    prp_a = create_party(
        site["id"],
        legal_name="Kestrel Yard Drum Co",
        party_type="OWNER_OPERATOR",
        viability_score=80,
    )
    prp_b = create_party(
        site["id"],
        legal_name="Yard Street Solvents",
        party_type="GENERATOR",
        viability_score=49,
    )
    issue_notice(prp_a["id"], "GNL-2027-8501")
    issue_notice(prp_b["id"], "GNL-2027-8502")
    record_election(prp_a["id"], "PARTICIPATE")
    record_election(prp_b["id"], "PARTICIPATE")
    record_a = add_waste_in(
        site["id"],
        prp_a["id"],
        volume_tons=3960,
        toxicity_class="II",
        evidence_grade="A",
        disposal_year=1971,
    )
    record_b = add_waste_in(
        site["id"],
        prp_b["id"],
        volume_tons=40,
        toxicity_class="IV",
        evidence_grade="B",
        disposal_year=1984,
    )
    verify_waste_in(record_a["id"], 3960)
    verify_waste_in(record_b["id"], 40)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 drum wash pad and dry well",
    )
    read_version = site_version(site["id"], FACILITATOR)
    first_round = open_round(
        site["id"], weights=(5000, 3000, 2000), expected_version=read_version
    )
    return site, read_version, first_round


class TestTheSiteVersionGuardsTheRoundThatWouldSupersede:
    def test_replaying_the_version_that_opened_the_round_is_refused(self):
        """The value that was current on the first create is stale on the second.

        PRD: "If any writer has advanced the site's `version` since the client last read the site, the create is refused with `ERR_STALE_SITE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_site_version_on_round_create_returns_4XX
        """
        site, read_version, first_round = _kestrel_yard_with_one_drafting_round()
        assert first_round["status"] == "DRAFTING"
        assert first_round["round_number"] == 1
        assert first_round["share_count"] == 2

        # Both weight triples sum to 10000 bp, so nothing but the version can
        # be the reason for the refusal.
        validate_error(
            api_client.create_allocation_round(
                site["id"],
                factories.allocation_round_payload(
                    expected_site_version=read_version,
                    weight_volume_bp=4000,
                    weight_toxicity_bp=4000,
                    weight_ownership_bp=2000,
                ),
                FACILITATOR,
            ),
            ApiErrorId.ERR_STALE_SITE_VERSION.value,
            412,
        )

        assert read_round(first_round["id"])["status"] == "DRAFTING"
        _, meta = validate_paginated(
            api_client.list_site_allocation_rounds(site["id"], FACILITATOR)
        )
        assert_pagination_meta(meta, total_count=1)

    def test_a_re_read_version_opens_the_second_round_and_supersedes_the_first(self):
        """Opening the round moved the version it was guarded by.

        PRD: "Opening a round increments the site's own `version`, and it supersedes whatever open round the site already had: a round in `DRAFTING`, `BALLOTING` or `FAILED` moves to `SUPERSEDED`."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_site_version_on_round_create_returns_4XX
        """
        site, read_version, first_round = _kestrel_yard_with_one_drafting_round()

        refreshed = site_version(site["id"], FACILITATOR)
        assert refreshed > read_version

        second_round = open_round(
            site["id"], weights=(4000, 4000, 2000), expected_version=refreshed
        )
        assert second_round["status"] == "DRAFTING"
        assert second_round["round_number"] == 2
        assert read_round(first_round["id"])["status"] == "SUPERSEDED"
        _, meta = validate_paginated(
            api_client.list_site_allocation_rounds(site["id"], FACILITATOR)
        )
        assert_pagination_meta(meta, total_count=2)


class TestTheRespondentVersionGuardsTheOfferThatWouldSupersede:
    def test_an_offer_built_on_the_pre_rejection_view_of_the_party_is_refused(self):
        """The respondent itself advanced the version the offer was priced from.

        PRD: "Issuing a recovery action against a party requires `expected_prp_version` as a mandatory, non-optional field, matching the **respondent party's** current `version` — not the site's. A mismatch is refused with `ERR_STALE_PRP_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_prp_version_on_cost_recovery_create_returns_4XX
        """
        set_clock("2027-02-01T09:00:00Z")
        site = create_site(
            name="Dunmore Flats Battery Breaking", epa_region=4, hrs_score=56.10
        )
        list_site_on_npl(site["id"], "FR-2027-DFB-0201")
        prp_a = create_party(
            site["id"],
            legal_name="Dunmore Flats Battery Co",
            party_type="OWNER_OPERATOR",
            viability_score=85,
        )
        prp_b = create_party(
            site["id"],
            legal_name="Flats Metal Recovery",
            party_type="GENERATOR",
            viability_score=58,
        )
        issue_notice(prp_a["id"], "GNL-2027-8601")
        issue_notice(prp_b["id"], "GNL-2027-8602")
        record_election(prp_a["id"], "PARTICIPATE")
        record_election(prp_b["id"], "PARTICIPATE")
        record_a = add_waste_in(
            site["id"],
            prp_a["id"],
            volume_tons=3960,
            toxicity_class="II",
            evidence_grade="A",
            disposal_year=1973,
        )
        record_b = add_waste_in(
            site["id"],
            prp_b["id"],
            volume_tons=40,
            toxicity_class="IV",
            evidence_grade="B",
            disposal_year=1987,
        )
        verify_waste_in(record_a["id"], 3960)
        verify_waste_in(record_b["id"], 40)
        create_investigation(
            site["id"], exposure_medium="SOIL", scope_summary="OU-1 lead in surface soil"
        )
        allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
        adopt_round(allocation_round["id"], [prp_a["id"], prp_b["id"]])
        post_oversight(
            site["id"],
            4_000_000,
            cost_category="RI_FS_OVERSIGHT",
            incurred_on="2027-02-20",
        )
        read_version = prp_version(prp_a["id"], COUNSEL)

        first_demand = validate_success(
            api_client.create_cost_recovery_action(
                site["id"],
                factories.cost_recovery_action_payload(
                    respondent_prp_id=prp_a["id"],
                    demanded_cents=4_586_736,
                    expected_prp_version=read_version,
                ),
                COUNSEL,
            ),
            201,
        )
        assert first_demand["status"] == "OFFERED"
        assert_percentage(
            first_demand["respondent_share_pct_at_offer"],
            99.28,
            "respondent_share_pct_at_offer",
        )

        rejected = respond_to_action(
            first_demand["id"], prp_a["id"], "REJECT", "Share disputed."
        )
        assert rejected["status"] == "REJECTED"
        assert read_party(prp_a["id"])["status"] == "RECALCITRANT"

        validate_error(
            api_client.create_cost_recovery_action(
                site["id"],
                factories.cost_recovery_action_payload(
                    respondent_prp_id=prp_a["id"],
                    demanded_cents=4_000_000,
                    expected_prp_version=read_version,
                ),
                COUNSEL,
            ),
            ApiErrorId.ERR_STALE_PRP_VERSION.value,
            412,
        )
        _, meta = validate_paginated(
            api_client.list_cost_recovery_actions(COUNSEL, {"site_id": site["id"]})
        )
        assert_pagination_meta(meta, total_count=1)
        assert read_action(first_demand["id"])["status"] == "REJECTED"

        refreshed = prp_version(prp_a["id"], COUNSEL)
        assert refreshed > read_version
        second_demand = validate_success(
            api_client.create_cost_recovery_action(
                site["id"],
                factories.cost_recovery_action_payload(
                    respondent_prp_id=prp_a["id"],
                    demanded_cents=4_000_000,
                    expected_prp_version=refreshed,
                ),
                COUNSEL,
            ),
            201,
        )
        assert second_demand["status"] == "OFFERED"
        assert_percentage(
            second_demand["respondent_share_pct_at_offer"],
            99.28,
            "respondent_share_pct_at_offer",
        )
