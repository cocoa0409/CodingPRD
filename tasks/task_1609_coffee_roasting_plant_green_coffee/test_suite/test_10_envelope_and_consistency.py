"""Response envelope shape, pagination, and immediate-consistency checks."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_counterparty,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

TRADER = TEST_USERS["trader_headers"]


class TestPagination:
    def test_list_counterparties_pagination(self, api):
        """PRD §2.3: "List endpoints are paginated through two query
        parameters. The `limit` parameter caps the number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of
        100. The `offset` parameter skips a number of items and defaults
        to 0."
        PRD §2.3: "The `meta` object of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/list_counterparties_pagination
        """
        set_clock()
        create_counterparty(ref="P1", legal_name="P1 Co", kind="SUPPLIER",
                             credit_limit_usd=1000)
        create_counterparty(ref="P2", legal_name="P2 Co", kind="SUPPLIER",
                             credit_limit_usd=1000)
        create_counterparty(ref="P3", legal_name="P3 Co", kind="CUSTOMER",
                             credit_limit_usd=1000)
        resp = api.list_counterparties(TRADER, params={"limit": 2, "offset": 0})
        # Envelope-level inspection
        body = resp.json()
        assert "meta" in body
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2


class TestErrorEnvelope:
    def test_response_envelope_error_shape(self, api):
        """PRD §2.2 (Standard Error Response Format): "The `meta` object
        for error responses contains only `api_request_id` and
        `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error. The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        set_clock()
        resp = api.get_counterparty(NON_EXISTENT_UUID, TRADER)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        # validate_error returns the error data dict.
        assert err["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err.get("message"), str) and err["message"], (
            "error message must be a non-empty string"
        )
        body = resp.json()
        assert body["response_type"] == "error"
        # Error meta contains only the request id + timestamp.
        assert set(body["meta"].keys()) == {"api_request_id",
                                            "api_request_timestamp"}


class TestImmediateConsistency:
    def test_immediate_consistency_writes_visible_in_same_request(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource
        object in the data field."
        PRD §3.1: "A new counterparty arrives with `counterparty_status`
        `ACTIVE` and `open_exposure_usd` zero."

        Design: Corner/consistency_model/immediate_consistency_writes_visible_in_same_request
        """
        set_clock()
        resp = api.create_counterparty(
            {"counterparty_ref": "SUP-IC", "legal_name": "ImmCo",
             "counterparty_kind": "SUPPLIER", "credit_limit_usd": 5000},
            TRADER,
        )
        data = validate_success(resp, 201)
        # The POST response already carries the server-populated fields.
        assert data["counterparty_status"] == "ACTIVE"
        assert data["version"] == 1
        assert data["id"]
