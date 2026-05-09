"""Pagination + response envelope checks."""
import pytest
from test_helpers import (
    api_client, validate_paginated, validate_success, validate_error,
    create_community, create_supplier, create_active_leader,
    create_group_buy_campaign, find_commission_entry,
    setup_picked_up_order,
    create_community_payload,
    ADMIN,
)


class TestPagination:

    def test_list_communities_pagination_limit(self, api):
        """PRD §2.3: "The limit parameter defaults to 10, has a minimum of
        1, and a maximum of 100".

        Claim: passing limit=2 returns at most 2 entries.
        """
        for i in range(3):
            create_community(name=f"C-PAG-{i}", region_code="RC1")
        data, meta = validate_paginated(api.list_communities(ADMIN, params={"limit": 2}))
        assert meta["limit"] == 2
        assert len(data) <= 2

    def test_list_communities_invalid_limit_rejected(self, api):
        """PRD §2.3: "A request with limit outside its bounds is rejected
        with ERR_VALIDATION_FAILED and HTTP 400."

        Claim: limit=0 (below minimum) is rejected with ERR_VALIDATION_FAILED.
        """
        res = api.list_communities(ADMIN, params={"limit": 0})
        validate_error(res, "ERR_VALIDATION_FAILED")


class TestEnvelopeShape:

    def test_success_response_has_envelope(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body".

        Claim: a successful response carries meta + response_type + data.
        """
        res = api.create_community(create_community_payload(name="C-ENV", region_code="RC1"), ADMIN)
        body = res.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_")
