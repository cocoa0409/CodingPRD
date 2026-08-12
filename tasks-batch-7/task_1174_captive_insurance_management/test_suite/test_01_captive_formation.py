"""Captive formation, domicile filings, listing/pagination, and response envelope."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_captive,
    assert_domicile_filing,
    assert_operating_unit,
    create_captive,
    create_captive_payload,
    create_domicile_filing,
    create_operating_unit,
    get_captive,
    is_valid_uuid,
    setup_captive_with_draft_filing,
    setup_domicile_filed_captive,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCaptiveCreation:

    def test_captive_creation_with_defaults(self, api, captive_manager_headers):
        """PRD §3.1: "The captive is born in `FORMATION_PENDING` status with
        `governance_score` set to `100`, `solvency_status` set to `ADEQUATE`, and
        `capital_minimum_required` looked up from the regulator-published schedule
        for the chosen domicile."
        PRD §3.1: "an optional `tax_classification` (one of `MICRO_CAPTIVE_831B`,
        `STANDARD_831A`, `NON_ELECTING`; if omitted the captive defaults to
        `MICRO_CAPTIVE_831B`)"
        PRD §2.4: "`version` is an integer starting at 1 and incremented by 1 on
        every mutation of the resource."

        Design: Corner/entities/captive_creation_with_defaults
        """
        payload = create_captive_payload(captive_name="New Captive")
        resp = api.create_captive(payload, captive_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_captive(data)
        assert data["status"] == "FORMATION_PENDING"
        assert data["governance_score"] == 100
        assert data["solvency_status"] == "ADEQUATE"
        assert data["tax_classification"] == "MICRO_CAPTIVE_831B"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        # Read-back agrees with the creation response.
        fetched = get_captive(data["id"])
        assert fetched["status"] == "FORMATION_PENDING"
        assert fetched["governance_score"] == 100

    def test_captive_creation_missing_required_field(self, api, captive_manager_headers):
        """PRD §3.1: "creating a `CaptiveEntity` with `captive_name`,
        `domicile_jurisdiction` (one of `VERMONT`, `BERMUDA`, `CAYMAN`, `GUERNSEY`,
        `LUXEMBOURG`), `formation_date`, `capitalization_amount` in cents" — the
        catalogue's only input-validation error is `ERR_INVALID_REQUEST` (HTTP 400),
        so omitting the required `captive_name` must produce it.

        Design: Corner/entities/captive_creation_missing_required_field
        """
        payload = {
            "domicile_jurisdiction": "VERMONT",
            "formation_date": "2026-01-15T00:00:00Z",
            "capitalization_amount": 500000,
        }
        resp = api.create_captive(payload, captive_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_captive_not_found(self, api, captive_manager_headers):
        """PRD §2.4: "the server first confirms the captive identified by
        `captiveId` exists (else `ERR_CAPTIVE_NOT_FOUND`, HTTP 404)".

        Design: Corner/entities/captive_not_found
        """
        resp = api.get_captive(NON_EXISTENT_UUID, captive_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CAPTIVE_NOT_FOUND)


class TestCaptiveListing:

    def test_captive_list_pagination(self, api, captive_manager_headers):
        """PRD §2.3: "The `meta` block on a successful list response echoes the
        effective `limit` and `offset`, and also reports `total_count` (the total
        number of records matching the filter, before pagination) and `has_more`
        (true when `offset + limit` is less than `total_count`)."

        Design: Corner/entities/captive_list_pagination
        """
        for i in range(3):
            create_captive(captive_name=f"Captive {i + 1}")
        resp = api.list_captives(captive_manager_headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"Expected 2 captives on page, got {len(data)}"
        assert meta["total_count"] == 3, f"Expected total_count 3, got {meta['total_count']}"
        assert meta["has_more"] is True, "has_more must be true when offset + limit < total_count"
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_response_envelope_structure(self, api, captive_manager_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either \"object\" for a single resource
        or \"array\" for a list of resources."

        Design: Corner/endpoints/response_envelope_structure
        """
        captive = create_captive()
        resp = api.get_captive(captive["id"], captive_manager_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert body["data"]["id"] == captive["id"]


class TestOperatingUnits:

    def test_operating_unit_creation_and_retrieval(self, api, captive_manager_headers):
        """PRD §3.5: "The unit is born `ACTIVE`."

        Design: Corner/entities/operating_unit_creation_and_retrieval
        """
        captive = create_captive()
        resp = api.create_operating_unit(
            captive["id"],
            {
                "unit_name": "Sales Division",
                "unit_code": "SD",
                "exposure_basis": "REVENUE",
                "exposure_amount": 5000,
            },
            captive_manager_headers,
        )
        unit = validate_success(resp, expected_status=201)
        assert_operating_unit(unit)
        assert unit["status"] == "ACTIVE"
        # No allocations or claims exist yet, so both running totals are zero.
        assert unit["total_premium_allocated_cents"] == 0
        assert unit["total_claims_incurred_cents"] == 0
        fetched = validate_success(
            api.get_operating_unit(captive["id"], unit["id"], captive_manager_headers)
        )
        assert fetched["id"] == unit["id"]


class TestDomicileFilings:

    def test_filing_submit_without_documents(self, api, captive_manager_headers):
        """PRD §3.1: "Submission requires that the captive is still in
        `FORMATION_PENDING` (else `ERR_CAPTIVE_NOT_IN_FORMATION`), that the filing
        itself is in `DRAFT` (else `ERR_FILING_NOT_DRAFT`), and that at least one
        supporting document has been uploaded (else `ERR_NO_SUPPORTING_DOCUMENTS`,
        HTTP 400)."

        Design: Corner/validations/filing_submit_without_documents
        """
        captive = create_captive()
        filing = create_domicile_filing(captive["id"], supporting_documents=[])
        assert filing["status"] == "DRAFT"
        resp = api.submit_filing(captive["id"], filing["id"], captive_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_SUPPORTING_DOCUMENTS)

    def test_filing_invalid_transition_draft_to_approve(self, api, domicile_regulator_headers):
        """PRD §3.1: "Approval requires the captive to be in `DOMICILE_FILED`
        (else `ERR_CAPTIVE_NOT_DOMICILE_FILED`), the filing to be `UNDER_REVIEW`
        (else `ERR_FILING_NOT_UNDER_REVIEW`), and the captive's
        `capitalization_amount` to be at least the domicile's
        `capital_minimum_required` (else `ERR_CAPITALIZATION_BELOW_MINIMUM`,
        HTTP 400)."

        Design: Corner/state_machines/filing_invalid_transition_draft_to_approve
        """
        # Captive is DOMICILE_FILED (first filing submitted); the second filing
        # under test remains DRAFT, so only the filing-state precondition fails.
        captive, _filing_a = setup_domicile_filed_captive()
        filing_b = create_domicile_filing(captive["id"])
        assert filing_b["status"] == "DRAFT"
        resp = api.approve_filing(captive["id"], filing_b["id"], domicile_regulator_headers)
        validate_error(resp, ApiErrorId.ERR_FILING_NOT_UNDER_REVIEW)

    def test_filings_reverse_reachable_from_captive(self, api, captive_manager_headers):
        """PRD §4: "GET | /api/captives/{captiveId}/domicile-filings | List
        domicile filings for a captive" — the filings of a captive are listed
        under the captive's nested collection.

        Design: Corner/endpoints/filings_reverse_reachable_from_captive
        """
        captive, filing = setup_captive_with_draft_filing()
        resp = api.list_domicile_filings(captive["id"], captive_manager_headers)
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"Expected exactly 1 filing, got {len(data)}"
        assert data[0]["id"] == filing["id"]
        assert_domicile_filing(data[0])
