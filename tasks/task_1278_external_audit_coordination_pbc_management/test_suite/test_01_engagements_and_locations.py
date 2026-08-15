"""Engagement registration, retrieval, listing, and location materiality."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_engagement,
    assert_engagement_counters,
    create_engagement,
    create_engagement_payload,
    create_location_payload,
    get_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CONTROLLER = TEST_USERS["controller_headers"]
PREPARER = TEST_USERS["preparer_headers"]


class TestEngagementCreation:

    def test_engagement_creation_returns_all_fields(self):
        """PRD §3.1: "A new engagement starts in `PLANNING` status with
        `posture` derived as `OPEN`, `total_fee_cents` equal to
        `base_fee_cents`, and all three derived counters — `open_pbc_count`,
        `open_query_count`, and `passed_adjustment_total_cents` — at zero."

        Design: Corner/entities/engagement_creation_returns_all_fields
        """
        resp = api_client.create_engagement(
            create_engagement_payload(
                client_name="AlphaCo", base_fee_cents=500_000,
                materiality_cents=50_000),
            CONTROLLER,
        )
        data = validate_success(resp, expected_status=201)
        assert_engagement(data)
        assert_engagement_counters(data)
        assert data["status"] == "PLANNING"
        assert data["posture"] == "OPEN"
        assert data["total_fee_cents"] == 500_000, (
            f"initial total_fee_cents must equal base_fee_cents, "
            f"got {data['total_fee_cents']}"
        )
        assert data["open_pbc_count"] == 0
        assert data["open_query_count"] == 0
        assert data["passed_adjustment_total_cents"] == 0


class TestEngagementRetrieval:

    def test_engagement_get_by_id_returns_persisted_fields(self):
        """PRD §2.2: "The `data` field contains the resource object or an
        array of resource objects."
        PRD §3.1: "A `Controller` opens an engagement by supplying the audited
        entity's legal `client_name`, its `fiscal_year_end` date, the
        negotiated `base_fee_cents` (which must be greater than zero), the
        overall engagement `materiality_cents` (likewise greater than zero),
        and the `filing_deadline` date that will discipline the whole
        timeline."

        Design: Corner/entities/engagement_get_by_id_returns_persisted_fields
        """
        eng = create_engagement(
            client_name="BetaCo", base_fee_cents=700_000,
            materiality_cents=75_000)
        resp = api_client.get_engagement(eng["id"], PREPARER)
        data = validate_success(resp)
        assert_engagement(data)
        assert data["id"] == eng["id"]
        assert data["client_name"] == "BetaCo"
        assert data["base_fee_cents"] == 700_000
        assert data["materiality_cents"] == 75_000
        assert data["filing_deadline"] == "2026-12-31"

    def test_engagement_not_found_returns_404(self):
        """PRD §2.5: "The server confirms the existence of each identifier in
        path order and rejects the request immediately with the 404 error
        corresponding to the first identifier that does not resolve:
        `ERR_ENGAGEMENT_NOT_FOUND` for engagements".

        Design: Corner/entities/engagement_not_found_returns_404
        """
        resp = api_client.get_engagement(NON_EXISTENT_UUID, CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND)


class TestEngagementListing:

    def test_engagement_list_pagination_envelope(self):
        """PRD §2.3: "The `meta` object of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/entities/engagement_list_pagination_envelope
        """
        create_engagement(client_name="C1", base_fee_cents=100_000,
                          materiality_cents=10_000)
        create_engagement(client_name="C2", base_fee_cents=100_000,
                          materiality_cents=10_000)
        resp = api_client.list_engagements(CONTROLLER)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert resp.json()["meta"]["api_request_id"], \
            "meta.api_request_id must be present"
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta.{field} missing from list envelope"
        assert meta["total_count"] == 2
        assert len(data) == 2
        for item in data:
            assert_engagement(item)


class TestLocationMateriality:

    def test_location_materiality_must_not_exceed_engagement(self):
        """PRD §3.1: "a location-level `materiality_cents` that must be
        greater than zero and no greater than the engagement's own
        `materiality_cents`; a location whose materiality exceeds the
        engagement's is rejected with `ERR_LOCATION_MATERIALITY_TOO_HIGH`."

        Design: Corner/entities/location_materiality_must_not_exceed_engagement
        """
        eng = create_engagement(client_name="C", base_fee_cents=500_000,
                                materiality_cents=50_000)
        resp = api_client.create_location(
            create_location_payload(eng["id"], materiality_cents=75_000),
            CONTROLLER,
        )
        validate_error(resp, ApiErrorId.ERR_LOCATION_MATERIALITY_TOO_HIGH)
