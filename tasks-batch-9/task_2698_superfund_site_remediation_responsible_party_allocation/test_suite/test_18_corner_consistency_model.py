"""Immediate consistency: the write response already carries the new figures.

Every derived field is current in the body of the write that changed it, so a
posting that crosses an indirect-rate tier ceiling reports the re-rated
assessment and the new ledger totals without any follow-up read.
"""
from test_helpers import api_client, factories
from test_helpers.assertions import (
    assert_ledger_figures,
    assert_oversight_figures,
    assert_percentage,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_waste_in,
    create_party,
    create_site,
    issue_notice,
    list_site_on_npl,
    read_ledger,
    read_party,
    read_site,
    record_election,
    set_clock,
    verify_waste_in,
)
from test_helpers.test_users import TEST_USERS

AUTHOR = TEST_USERS["author_pm_headers"]
COMMUNITY = TEST_USERS["community_headers"]


def _halloran_pit_with_two_verified_claims():
    """Two verified claims, no decree — so the oversight cap rule is dormant."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_site(
        name="Halloran Pit Solvent Recovery", epa_region=6, hrs_score=48.40
    )
    list_site_on_npl(site["id"], "FR-2027-HPS-0201")
    prp_a = create_party(
        site["id"],
        legal_name="Halloran Pit Recovery Co",
        party_type="OWNER_OPERATOR",
        viability_score=74,
    )
    prp_b = create_party(
        site["id"],
        legal_name="Pit Road Degreasing",
        party_type="GENERATOR",
        viability_score=39,
    )
    issue_notice(prp_a["id"], "GNL-2027-8801")
    issue_notice(prp_b["id"], "GNL-2027-8802")
    record_election(prp_a["id"], "PARTICIPATE")
    record_election(prp_b["id"], "PARTICIPATE")
    record_a = add_waste_in(
        site["id"],
        prp_a["id"],
        volume_tons=500,
        toxicity_class="II",
        evidence_grade="A",
        disposal_year=1975,
    )
    verify_waste_in(record_a["id"], 500)
    record_b = add_waste_in(
        site["id"],
        prp_b["id"],
        volume_tons=100,
        toxicity_class="III",
        evidence_grade="B",
        disposal_year=1980,
    )
    verify_waste_in(record_b["id"], 100)
    return site, prp_a, prp_b


def _post_oversight_raw(site_id, incurred_cents, cost_category, incurred_on):
    """Post one oversight cost and return the write response body."""
    return validate_success(
        api_client.post_oversight_cost(
            site_id,
            factories.oversight_cost_payload(
                incurred_cents=incurred_cents,
                cost_category=cost_category,
                incurred_on=incurred_on,
            ),
            AUTHOR,
        )
    )


class TestTheWriteResponseIsAlreadyCurrent:
    def test_the_tier_crossing_posting_returns_its_own_re_rated_assessment(self):
        """No intermediate read is needed to see the new rate and totals.

        PRD: "Second, **the indirect component is recomputed in full on every posting**: when a posting carries the subtotal across a tier ceiling, the entire accumulated subtotal is re-rated at the new rate."

        Design: Corner/consistency_model/corner_every_derived_field_is_current_in_the_same_response
        """
        site, _, _ = _halloran_pit_with_two_verified_claims()

        first = _post_oversight_raw(
            site["id"], 4_000_000, "RI_FS_OVERSIGHT", "2027-02-10"
        )
        assert_oversight_figures(first, 4_000_000, 1550, 620_000, 4_620_000)
        assert first["total_response_cost_cents"] == 4_620_000
        assert first["oversight_cap_utilization_pct"] in (None, "")

        second = _post_oversight_raw(
            site["id"], 5_000_000, "RD_RA_OVERSIGHT", "2027-02-11"
        )
        # The whole 9,000,000 subtotal is re-rated at 1275 bp, so the indirect
        # figure is 1,147,500 rather than 620,000 plus 637,500.
        assert_oversight_figures(second, 9_000_000, 1275, 1_147_500, 10_147_500)
        assert second["total_response_cost_cents"] == 10_147_500
        assert second["oversight_cap_utilization_pct"] in (None, "")

    def test_the_ledger_read_agrees_with_the_last_write_it_saw(self):
        """The reconciliation read repeats what the posting already reported.

        PRD: "The conservation identity that must hold after every write is that `recovered_cost_cents` plus `orphan_write_off_cents` plus `unrecovered_cost_cents` equals `total_response_cost_cents` exactly."

        Design: Corner/consistency_model/corner_every_derived_field_is_current_in_the_same_response
        """
        site, prp_a, prp_b = _halloran_pit_with_two_verified_claims()
        _post_oversight_raw(site["id"], 4_000_000, "RI_FS_OVERSIGHT", "2027-02-10")
        _post_oversight_raw(site["id"], 5_000_000, "RD_RA_OVERSIGHT", "2027-02-11")

        ledger = read_ledger(site["id"], COMMUNITY)
        assert_ledger_figures(ledger, 10_147_500, 0, 0, 10_147_500)
        assert ledger["ledger_balanced"] is True
        assert ledger["oversight_indirect_rate_bp"] == 1275
        assert read_site(site["id"])["total_response_cost_cents"] == 10_147_500

        # The party percentages have not lagged behind either.
        assert_percentage(
            read_party(prp_a["id"])["volumetric_share_pct"], 83.33, "volumetric_share_pct"
        )
        assert_percentage(
            read_party(prp_b["id"])["volumetric_share_pct"], 16.67, "volumetric_share_pct"
        )
        _, meta = validate_paginated(
            api_client.list_site_waste_in_records(site["id"], AUTHOR)
        )
        assert meta["total_count"] == 2
