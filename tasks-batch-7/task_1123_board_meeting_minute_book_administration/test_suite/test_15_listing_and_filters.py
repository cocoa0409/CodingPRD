"""Listing and pagination: envelope shape, default limit, filter+pagination
interaction."""
from test_helpers import (
    add_director,
    add_directors,
    create_corporation,
    validate_paginated,
    SECRETARY,
)
from test_helpers import api_client


class TestListPaginationDefaults:
    def test_list_pagination_defaults_and_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10 when omitted, accepts a minimum of 1, and is bounded
        above at 100. The `offset` parameter says how many items to skip and
        defaults to 0. ... The `meta` object of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_defaults_and_envelope
        """
        corp = create_corporation(name="Corp L1")
        add_directors(corp["id"], 12, email_prefix="d")
        resp = api.list_directors(SECRETARY, params={"corporation_id": corp["id"]})
        data, meta = validate_paginated(resp)
        assert len(data) == 10, f"expected default limit 10, got {len(data)}"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True

    def test_list_envelope_includes_request_id(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/list_pagination_defaults_and_envelope
        """
        corp = create_corporation(name="Corp L1b")
        add_director(corp["id"], "D1", "d1@x.com")
        resp = api.list_directors(SECRETARY, params={"corporation_id": corp["id"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("response_type") == "array"
        api_request_id = body.get("meta", {}).get("api_request_id", "")
        assert isinstance(api_request_id, str) and api_request_id.startswith("req_"), (
            f"expected api_request_id starting with 'req_', got {api_request_id!r}"
        )


class TestListFilterByStatus:
    def test_list_filter_by_status_after_resignation(self, api):
        """PRD §3.2: "Directors may be listed with `corporation_id`, `status`,
        and `independence_status` filters." Filtered total_count reflects the
        filter, not the table.

        Design: Corner/endpoints/list_filter_by_status_after_resignation
        """
        corp = create_corporation(name="Corp L2")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        d2 = add_director(corp["id"], "D2", "d2@x.com")
        add_director(corp["id"], "D3", "d3@x.com")
        api.resign_director(d2["id"], SECRETARY)

        resp_resigned = api.list_directors(
            SECRETARY, params={"corporation_id": corp["id"], "status": "RESIGNED"}
        )
        data_r, meta_r = validate_paginated(resp_resigned)
        assert meta_r["total_count"] == 1
        assert len(data_r) == 1
        assert data_r[0]["id"] == d2["id"]

        resp_active = api.list_directors(
            SECRETARY, params={"corporation_id": corp["id"], "status": "ACTIVE"}
        )
        _data_a, meta_a = validate_paginated(resp_active)
        assert meta_a["total_count"] == 2
