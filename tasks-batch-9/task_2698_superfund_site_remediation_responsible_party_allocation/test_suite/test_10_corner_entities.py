"""Entity-level probes: creation defaults, reads, listings, shape gates.

These exercise the record contract itself — what a freshly created row looks
like, what a read of a missing row returns, how a roster paginates, which
request bodies are malformed, and which rows carry no update surface at all.
"""
import pytest

from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import (
    assert_identifier_conventions,
    assert_pagination_meta,
    assert_version_starts_at_one,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_ownership_period,
    create_listed_site,
    create_party,
    read_party,
    read_site,
    set_clock,
)
from test_helpers.test_users import TEST_USERS

AUTHOR = TEST_USERS["author_pm_headers"]
UNKNOWN_SITE_ID = "8f14e45f-ceea-467a-9a36-dedd4bea2543"
UNKNOWN_PRP_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


class TestSiteCreationEnvelope:
    def test_a_bare_site_create_defaults_every_derived_figure_to_zero(self):
        """A proposed site starts open, unlisted and with an empty ledger.

        PRD: "A newly proposed site begins in `PROPOSED` with its `cost_posture` at `OPEN`, its `listing_reference` empty, and every derived cost, volume and share figure at zero."

        Design: Corner/entities/corner_create_site_returns_envelope_with_every_derived_field_defaulted
        """
        set_clock("2027-01-04T08:00:00Z")
        response = api_client.create_site(
            factories.site_payload(
                name="Pellet Creek Battery Breaking", epa_region=9, hrs_score=34.50
            ),
            AUTHOR,
        )
        site = validate_success(response, 201)
        meta = response.json()["meta"]
        assert meta["api_request_id"]
        assert meta["api_request_timestamp"]

        assert_identifier_conventions(site)
        assert_version_starts_at_one(site)
        assert site["name"] == "Pellet Creek Battery Breaking"
        assert site["epa_region"] == 9
        assert site["hrs_score"] == pytest.approx(34.50, abs=0.01)
        assert site["listing_status"] == "PROPOSED"
        assert site["cost_posture"] == "OPEN"
        assert site["listing_reference"] in (None, "")
        for field in (
            "oversight_direct_cents",
            "oversight_indirect_cents",
            "oversight_billed_cents",
            "total_response_cost_cents",
            "recovered_cost_cents",
            "orphan_write_off_cents",
            "unrecovered_cost_cents",
        ):
            assert site[field] == 0, f"{field} should default to 0"
        assert site["verified_waste_volume_tons"] == pytest.approx(0, abs=0.01)
        assert site["adopted_round_id"] in (None, "")
        assert site["construction_complete_at"] in (None, "")
        assert site["five_year_review_due_at"] in (None, "")


class TestUnknownIdentifierReads:
    def test_a_valid_uuid_naming_no_site_is_a_not_found_error(self):
        """The path existence gate answers with the site's own error.

        PRD: "The error reported is the one belonging to the first identifier in the path that does not resolve — `ERR_SITE_NOT_FOUND`, `ERR_PRP_NOT_FOUND`, `ERR_WASTE_IN_RECORD_NOT_FOUND`, `ERR_REMEDIAL_INVESTIGATION_NOT_FOUND`, `ERR_RECORD_OF_DECISION_NOT_FOUND`, `ERR_ALLOCATION_ROUND_NOT_FOUND`, `ERR_CONSENT_DECREE_NOT_FOUND`, `ERR_REMEDIATION_CONTRACT_NOT_FOUND` or `ERR_COST_RECOVERY_ACTION_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/corner_get_site_with_unknown_id_not_found
        """
        set_clock("2027-01-04T08:00:00Z")
        assert is_valid_uuid(UNKNOWN_SITE_ID)

        response = api_client.get_site(UNKNOWN_SITE_ID, AUTHOR)
        body = validate_error(response, ApiErrorId.ERR_SITE_NOT_FOUND.value, 404)
        assert isinstance(body["message"], str) and body["message"]
        assert "id" not in body


class TestPartyRosterListing:
    def test_the_roster_paginates_in_creation_order_with_a_stable_total(self):
        """Pages report the pre-pagination total and whether more remain.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the filter before pagination is applied and `has_more` indicates whether records remain beyond the current page."

        Design: Corner/entities/corner_list_site_prps_paginates_with_total_count_and_has_more
        """
        set_clock("2027-01-04T08:00:00Z")
        site = create_listed_site(
            name="Otter Slough Galvanizing", epa_region=5, hrs_score=33.10
        )
        prp_1 = create_party(
            site["id"],
            legal_name="Otter Galvanizing Co",
            party_type="OWNER_OPERATOR",
            viability_score=70,
        )
        prp_2 = create_party(
            site["id"],
            legal_name="Slough Plating LLC",
            party_type="GENERATOR",
            viability_score=40,
        )
        prp_3 = create_party(
            site["id"],
            legal_name="Riverbend Trucking",
            party_type="TRANSPORTER",
            viability_score=20,
        )

        first, meta = validate_paginated(
            api_client.list_site_prps(site["id"], AUTHOR, {"limit": 2, "offset": 0})
        )
        assert_pagination_meta(meta, total_count=3, has_more=True, limit=2, offset=0)
        assert [row["id"] for row in first] == [prp_1["id"], prp_2["id"]]

        second, meta = validate_paginated(
            api_client.list_site_prps(site["id"], AUTHOR, {"limit": 2, "offset": 2})
        )
        assert_pagination_meta(meta, total_count=3, has_more=False, offset=2)
        assert [row["id"] for row in second] == [prp_3["id"]]

        filtered, meta = validate_paginated(
            api_client.list_site_prps(site["id"], AUTHOR, {"status": "IDENTIFIED"})
        )
        assert_pagination_meta(meta, total_count=3, has_more=False)
        assert len(filtered) == 3


class TestPartyCreationShapeGates:
    def test_omitting_the_ability_to_pay_score_is_a_malformed_request(self):
        """A required input with no default cannot be left out.

        PRD: "Request shape: required fields present, types correct, enumerated values in range, integers within their declared bounds, monetary amounts supplied as integer counts of cents and never as decimal strings, decimal fields within their declared scale, arrays non-empty and free of duplicates, pagination within range — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/corner_create_prp_missing_viability_score_returns_4XX
        """
        set_clock("2027-01-04T08:00:00Z")
        site = create_listed_site(name="Larkspur Foundry", epa_region=6, hrs_score=30.60)

        validate_error(
            api_client.create_prp(
                site["id"],
                {"legal_name": "Larkspur Castings Inc", "party_type": "OWNER_OPERATOR"},
                AUTHOR,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )
        _, meta = validate_paginated(api_client.list_site_prps(site["id"], AUTHOR))
        assert_pagination_meta(meta, total_count=0)

    def test_a_party_type_outside_the_closed_enumeration_is_refused(self):
        """Only the four recognised roles of liability may be recorded.

        PRD: "Against a listed site, the manager names each potentially responsible party discovered by site-history research, supplying the party's `legal_name`, its `party_type` — one of `OWNER_OPERATOR`, `GENERATOR`, `TRANSPORTER` or `ARRANGER` — and its `viability_score`, an integer from 0 through 100 produced by the ability-to-pay screen."

        Design: Corner/entities/corner_create_prp_with_unknown_party_type_enum_returns_4XX
        """
        set_clock("2027-01-04T08:00:00Z")
        site = create_listed_site(
            name="Vetch Hollow Scrapyard", epa_region=7, hrs_score=31.40
        )

        validate_error(
            api_client.create_prp(
                site["id"],
                factories.prp_payload(
                    legal_name="Hollow Land Trust",
                    party_type="LANDLORD",
                    viability_score=55,
                ),
                AUTHOR,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )
        _, meta = validate_paginated(api_client.list_site_prps(site["id"], AUTHOR))
        assert_pagination_meta(meta, total_count=0)


class TestBodyReferenceExistence:
    def test_a_waste_in_claim_naming_no_party_is_a_not_found_error(self):
        """An identifier inside the body is resolved, not silently stored.

        PRD: "Body reference existence: every identifier carried inside a request body must resolve — `prp_id`, `remedial_investigation_id`, `record_of_decision_id`, `alternative_id`, `respondent_prp_id`, `claimant_prp_id` and each element of `party_prp_ids`."

        Design: Corner/entities/corner_waste_in_record_naming_an_unknown_prp_not_found
        """
        set_clock("2027-01-04T08:00:00Z")
        site = create_listed_site(
            name="Quill Ridge Wood Treating", epa_region=4, hrs_score=37.20
        )

        validate_error(
            api_client.create_waste_in_record(
                site["id"],
                factories.waste_in_payload(
                    prp_id=UNKNOWN_PRP_ID,
                    volume_tons=500,
                    toxicity_class="II",
                    evidence_grade="B",
                    disposal_year=1979,
                ),
                AUTHOR,
            ),
            ApiErrorId.ERR_PRP_NOT_FOUND.value,
            404,
        )
        _, meta = validate_paginated(
            api_client.list_site_waste_in_records(site["id"], AUTHOR)
        )
        assert_pagination_meta(meta, total_count=0)
        assert read_site(site["id"])["verified_waste_volume_tons"] == pytest.approx(
            0, abs=0.01
        )


class TestChainOfTitleImmutability:
    def test_an_ownership_period_row_exposes_no_version_and_no_updated_at(self):
        """The chain of title is append-only and carries no update surface.

        PRD: "Three record types are immutable once written and therefore carry **only** `id` and `created_at`: the ownership periods that make up a site's chain of title, the analytical results attached to an investigation, and the field-work windows scheduled against a contract."

        Design: Corner/entities/corner_ownership_period_row_carries_no_version_or_update_surface
        """
        set_clock("2027-01-04T08:00:00Z")
        site = create_listed_site(
            name="Bittern Point Shipbreaking", epa_region=1, hrs_score=42.20
        )
        prp_a = create_party(
            site["id"],
            legal_name="Bittern Marine Works",
            party_type="OWNER_OPERATOR",
            viability_score=61,
        )
        op1 = add_ownership_period(
            site["id"], prp_a["id"], "1955-01-01", "1960-01-01", "PURCHASE"
        )

        rows, meta = validate_paginated(
            api_client.list_site_ownership_periods(site["id"], AUTHOR)
        )
        assert_pagination_meta(meta, total_count=1)
        row = rows[0]
        assert row["id"] == op1["id"]
        for field in (
            "site_id",
            "prp_id",
            "start_date",
            "end_date",
            "acquisition_type",
            "ownership_days",
        ):
            assert field in row, f"immutable row should expose {field}"
        assert "version" not in row
        assert "updated_at" not in row
        assert row["ownership_days"] == 1826
        assert read_party(prp_a["id"])["ownership_days_total"] == 1826
