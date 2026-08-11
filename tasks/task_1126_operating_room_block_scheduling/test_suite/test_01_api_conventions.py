"""API-wide conventions: response envelope, pagination, auth header checks."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_operating_room,
    create_operating_room_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestResponseEnvelope:
    def test_success_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`." and "The `response_type` is either
        "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        res = api.create_operating_room(
            create_operating_room_payload(room_name="OR1"), admin_headers
        )
        body = res.json()
        assert res.status_code == 201
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        room = validate_success(res, 201)
        assert_operating_room(room)
        assert room["room_name"] == "OR1"

    def test_error_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error. The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        res = api.get_block("11111111-2222-3333-4444-555555555555", admin_headers)
        body = res.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        error = validate_error(res, ApiErrorId.ERR_BLOCK_NOT_FOUND)
        assert error["error_id"] == "ERR_BLOCK_NOT_FOUND"
        assert isinstance(error["message"], str) and len(error["message"]) > 0


class TestPagination:
    def test_limit_offset_has_more(self, api, admin_headers):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_pagination_limit_offset_has_more
        """
        for name in ("R1", "R2", "R3"):
            api.create_operating_room(
                create_operating_room_payload(room_name=name), admin_headers
            )

        page1, meta1 = validate_paginated(
            api.list_operating_rooms(admin_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_operating_rooms(admin_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2


class TestAuthHeaderPresence:
    @pytest.mark.parametrize("headers", [None, {}])
    def test_missing_auth_headers_rejected(self, api, headers):
        """PRD §2.1: "A request with a missing header or an undeclared role is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        res = api.list_blocks(headers=headers)
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert res.status_code == 400
