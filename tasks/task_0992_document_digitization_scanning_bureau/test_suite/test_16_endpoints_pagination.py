"""Endpoint shape: pagination envelope, defaults."""
import pytest

from test_helpers import (
    api_client, validate_paginated, get_success_data,
    create_client_with_agreement, create_batch,
    make_intake_clerk_headers,
    CLERK,
)


class TestListBatchesPaginationDefaultsAndEnvelope:
    """Corner: list_batches_pagination_defaults_and_envelope."""

    def test_default_limit_offset_and_meta_fields(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and
        `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
        100; `offset` defaults to 0. Results are always sorted by `created_at`
        ascending. The `meta` block of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`." PRD §2.2:
        "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/endpoints/list_batches_pagination_defaults_and_envelope
        """
        client, _ = create_client_with_agreement(name="Page Co", hipaa_covered=False)
        create_batch(client["id"])
        create_batch(client["id"])
        resp = api_client.list_client_batches(client["id"], make_intake_clerk_headers(CLERK))
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        body = resp.json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"]
