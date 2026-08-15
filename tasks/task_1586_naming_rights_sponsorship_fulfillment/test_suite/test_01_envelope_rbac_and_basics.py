"""Envelope shape, authentication, RBAC denials, and basic entity rules."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_asset,
    assert_venue,
    create_active_sponsor,
    create_asset,
    create_asset_payload,
    create_contract_payload,
    create_draft_contract,
    create_venue,
    is_valid_uuid,
    make_sponsor_contact_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, FINANCE, SALES


class TestVenueDefaults:
    def test_venue_create_applies_epoch_default(self, api):
        """PRD §2.4: "Each venue maintains its own epoch in `current_season`,
        initialized to 2026 when the venue is created and advanced by exactly
        one season each time a `VenueAdmin` runs the advance-season checkpoint."
        PRD §2.10: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource"

        Design: Corner/entities/venue_create_applies_epoch_default
        """
        resp = api.create_venue({"display_name": "Vector Arena",
                                 "city": "Austin"}, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_venue(data)
        assert data["current_season"] == 2026
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])


class TestRequestShape:
    def test_contract_create_missing_required_returns_invalid_request(self, api):
        """PRD §2.12: "**Request shape** — all required input fields present, no
        undeclared fields, enum values within their declared constraint sets,
        integer and date fields parseable (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/contract_create_missing_required_returns_invalid_request
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        payload = create_contract_payload(venue["id"], sponsor["id"],
                                          term_last_season=2028,
                                          escalator_pct=0.03)
        del payload["escalator_mode"]
        resp = api.create_contract(payload, SALES)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        listed, meta = validate_paginated(api.list_contracts(
            SALES, params={"sponsor_id": sponsor["id"]}))
        assert listed == [], "nothing should be persisted on a 400 rejection"

    def test_asset_create_invalid_enum_rejected(self, api):
        """PRD §2.12: "**Request shape** — all required input fields present, no
        undeclared fields, enum values within their declared constraint sets,
        integer and date fields parseable (`ERR_INVALID_REQUEST`)."
        PRD §3.1: "an `asset_class` of `SIGNAGE`, `DIGITAL`, or `HOSPITALITY`"

        Design: Corner/entities/asset_create_invalid_enum_rejected
        """
        venue = create_venue()
        payload = create_asset_payload(venue["id"], name="Radio Booth",
                                       asset_class="RADIO")
        resp = api.create_asset(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestExistence:
    def test_sponsor_get_not_found_returns_404(self, api):
        """PRD §2.12: "**Existence** — path identifiers exist, validated left to
        right, and body references such as `venue_id`, `sponsor_id`,
        `contract_id`, `asset_id`, and `deliverable_id` resolve to existing
        resources (`ERR_NOT_FOUND`)."

        Design: Corner/entities/sponsor_get_not_found_returns_404
        """
        resp = api.get_sponsor(NON_EXISTENT_UUID, SALES)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestPagination:
    def test_asset_list_pagination_envelope(self, api):
        """PRD §2.3: "`limit` sets the maximum number of records returned; when
        omitted it defaults to 10, and it accepts a minimum of 1 and a maximum
        of 100. `offset` sets how many records are skipped and defaults to 0.
        Every list response is sorted by `created_at` in ascending order; the
        ordering is stable and deterministic, and `id` is never used as an
        ordering key. The `meta` object of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/asset_list_pagination_envelope
        """
        venue = create_venue()
        a1 = create_asset(venue["id"], name="A1")
        create_asset(venue["id"], name="A2", asset_class="DIGITAL",
                     rate_card_unit_cents=80_000,
                     avg_impressions_per_unit=200_000, cpm_cents=3_000)
        create_asset(venue["id"], name="A3", asset_class="HOSPITALITY",
                     rate_card_unit_cents=250_000, avg_impressions_per_unit=1,
                     cpm_cents=1)

        page1, meta1 = validate_paginated(api.list_assets(
            ADMIN, params={"venue_id": venue["id"], "limit": 2}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2
        assert page1[0]["id"] == a1["id"], "created_at ASC ordering"

        page2, meta2 = validate_paginated(api.list_assets(
            ADMIN, params={"venue_id": venue["id"], "limit": 2, "offset": 2}))
        assert meta2["has_more"] is False
        assert len(page2) == 1


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or naming a role outside
        this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.12: "A request that fails authentication never reaches shape
        validation"

        Design: Corner/errors/missing_auth_headers_returns_401
        """
        # Strip the auth headers entirely; keep only content-type.
        resp = api.create_venue({"display_name": "Vector Arena",
                                 "city": "Austin"},
                                {"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED,
                       expected_status=401)

    def test_error_envelope_shape_on_rejection(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error.
        The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/errors/error_envelope_shape_on_rejection
        """
        resp = api.get_sponsor(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        assert isinstance(err["message"], str) and err["message"].strip()
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestRbacDenials:
    def test_sponsor_contact_cannot_manage_assets(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint — or, for a sponsor contact, whose target lies outside their
        sponsorship scope — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /assets is authorized for VenueAdmin only.

        Design: Corner/roles/sponsor_contact_cannot_manage_assets
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        payload = create_asset_payload(venue["id"], name="Rogue")
        resp = api.create_asset(payload,
                                make_sponsor_contact_headers(sponsor["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_finance_manager_cannot_drive_contract_pipeline(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint — or, for a sponsor contact, whose target lies outside their
        sponsorship scope — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /contracts/{contract_id}/transition is authorized for
        SponsorshipSales only.

        Design: Corner/roles/finance_manager_cannot_drive_contract_pipeline
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        contract = create_draft_contract(venue["id"], sponsor["id"],
                                         term_last_season=2028)
        resp = api.transition_contract(contract["id"], {"action": "PROPOSE"},
                                       FINANCE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_sponsor_contact_scoped_reads_hide_other_sponsors(self, api):
        """PRD §2.1: "every read performed by a sponsor contact is scoped to
        resources whose contract chain leads back to their own sponsor account
        — anything outside that scope is rejected with `ERR_FORBIDDEN`."

        Design: Corner/roles/sponsor_contact_scoped_reads_hide_other_sponsors
        """
        venue = create_venue()
        s1 = create_active_sponsor(legal_name="FizzCo Beverages LLC")
        s2 = create_active_sponsor(legal_name="SparkWater Inc",
                                   display_name="SparkWater")
        c1 = create_draft_contract(venue["id"], s1["id"], title="C1",
                                   term_last_season=2028)
        c2 = create_draft_contract(venue["id"], s2["id"], title="C2",
                                   term_last_season=2028, base_fee_cents=2_000_000)

        resp = api.get_contract(c1["id"], make_sponsor_contact_headers(s2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        listed, meta = validate_paginated(api.list_contracts(
            make_sponsor_contact_headers(s2["id"]), params={}))
        assert len(listed) == 1
        assert listed[0]["id"] == c2["id"]


class TestImmediateConsistency:
    def test_immediate_read_after_write_visibility(self, api):
        """PRD §2.8: "Two totals on each contract are never written directly;
        they are recomputed from child records whenever a relevant event lands,
        synchronously within the triggering request."
        PRD §3.1: "An asset's `asset_status` starts `AVAILABLE`"

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        venue = create_venue()
        resp = api.create_asset(
            create_asset_payload(venue["id"], name="Bowl LED Ribbon"), ADMIN)
        created = validate_success(resp, expected_status=201)
        assert_asset(created)
        assert created["rate_card_unit_cents"] == 50_000

        fetched = validate_success(api.get_asset(created["id"], ADMIN))
        assert fetched["rate_card_unit_cents"] == 50_000
        assert fetched["asset_status"] == "AVAILABLE"
