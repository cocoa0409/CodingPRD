"""Bank onboarding, response envelope, and flat catalog claims.

Covers queue-B instances under entities/endpoints that need no composite
state: creation defaults, not-found, pagination, duplicate charter, and the
success/error envelope shape.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_bank,
    create_bank_payload,
    create_bank,
)


class TestBankOnboarding(object):
    def test_bank_create_success_returns_defaults(self, api, system_operator_headers):
        """PRD §3.1: "A new bank begins life with its pca_bucket at
        ADEQUATELY_CAPITALIZED (a placeholder until its first accepted call
        report), mdba_cents and pending_distribution_cents at zero,
        stressed_capital_buffer_bps null, and supervisory_status at NORMAL."
        PRD §3.1: "omitted, it defaults to STANDARDIZED"

        Design: Corner/entities/bank_create_success_returns_defaults
        """
        res = api.create_bank(
            create_bank_payload(legal_name="DefaultBank", charter_id="CH-DEF-001"),
            system_operator_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_bank(data)
        assert data["version"] == 1, f"version must start at 1, got {data['version']}"
        assert data["pca_bucket"] == "ADEQUATELY_CAPITALIZED"
        assert data["mdba_cents"] == 0
        assert data["pending_distribution_cents"] == 0
        assert data["supervisory_status"] == "NORMAL"
        assert data["rwa_methodology"] == "STANDARDIZED"

    def test_bank_get_not_found_returns_404(self, api, capital_analyst_headers):
        """PRD §2.9: "the first identifier that does not resolve yields
        ERR_NOT_FOUND (HTTP 404); deeper identifiers are never examined once
        an ancestor has failed."

        Design: Corner/entities/bank_get_not_found_returns_404
        """
        res = api.get_bank(NON_EXISTENT_UUID, capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_bank_list_pagination_defaults(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §2.3: "limit sets the maximum number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100. offset sets
        the number of items to skip and defaults to 0. ... and the meta object
        of a list response carries limit, offset, total_count, and has_more."

        Design: Corner/entities/bank_list_pagination_defaults
        """
        for i in range(1, 4):
            get_success_data(api.create_bank(
                create_bank_payload(legal_name=f"B{i}", charter_id=f"CH-LST-{i:03d}"),
                system_operator_headers,
            ))
        res = api.list_banks(capital_analyst_headers)
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3

    def test_bank_duplicate_charter_id_rejected(self, api, system_operator_headers):
        """PRD §3.1: "The charter identifier is unique across banks: an
        attempt to register a second bank with an already-used charter_id is
        rejected with ERR_DUPLICATE_CHARTER_ID (HTTP 409)."

        Design: Corner/entities/bank_duplicate_charter_id_rejected
        """
        get_success_data(api.create_bank(
            create_bank_payload(legal_name="First", charter_id="CH-DUP-001"),
            system_operator_headers,
        ))
        res = api.create_bank(
            create_bank_payload(legal_name="Second", charter_id="CH-DUP-001"),
            system_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CHARTER_ID)

    def test_pca_threshold_event_immutable(self, api, capital_analyst_headers):
        """PRD §2.9: "the first identifier that does not resolve yields
        ERR_NOT_FOUND (HTTP 404); deeper identifiers are never examined once
        an ancestor has failed."

        Design: Corner/entities/pca_threshold_event_immutable
        """
        res = api.list_pca_threshold_events(NON_EXISTENT_UUID, capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestResponseEnvelope(object):
    def test_response_envelope_shape_on_success(self, api, system_operator_headers):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_." and "The
        response_type is either "object" for a single resource or "array" for
        a list of resources."

        Design: Corner/endpoints/response_envelope_shape_on_success
        """
        res = api.create_bank(
            create_bank_payload(legal_name="EnvBank", charter_id="CH-ENV-001"),
            system_operator_headers,
        )
        data = validate_success(res, expected_status=201)
        body = res.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["response_type"] == "object"
        assert isinstance(data, dict) and data["charter_id"] == "CH-ENV-001"

    def test_response_envelope_shape_on_error(self, api, capital_analyst_headers):
        """PRD §2.2: "The error_id is a unique, machine-readable string that
        identifies the specific error." and "The message provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape_on_error
        """
        res = api.get_bank(NON_EXISTENT_UUID, capital_analyst_headers)
        error_data = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(error_data["message"], str) and len(error_data["message"]) > 0
