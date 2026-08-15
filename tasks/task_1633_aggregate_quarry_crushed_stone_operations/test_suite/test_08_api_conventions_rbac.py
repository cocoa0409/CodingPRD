"""Cross-cutting API conventions: the response envelope, pagination, and
role-based access control."""
import pytest  # noqa: F401

from test_helpers import (
    ADMIN,
    FINANCE,
    MANAGER,
    ApiErrorId,
    create_bench,
    create_site,
    create_site_payload,
    set_clock,
    validate_error,
    validate_paginated,
)


class TestAuthEnforcement:
    def test_unauthenticated_missing_auth_header_returns_401(self, api):
        """PRD 2.1: "A request whose `X-User-Role` header is missing or
        names no declared role, or whose `X-User-ID` header is missing or
        empty, is rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/unauthenticated_missing_auth_header_returns_401
        """
        resp = api.list_sites(None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_finance_clerk_cannot_create_bench(self, api):
        """PRD 2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (403)."
        PRD 4: POST /benches is authorized for SiteManager.

        Design: Corner/rbac/finance_clerk_cannot_create_bench
        """
        site = create_site()
        payload = {"site_id": site["id"], "bench_label": "B1",
                   "elevation_ft": 1400, "acreage": 5.0}
        resp = api.create_bench(payload, FINANCE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        data, _meta = validate_paginated(
            api.list_benches(MANAGER, params={"site_id": site["id"]}))
        assert data == []

    def test_site_manager_cannot_set_clock(self, api):
        """PRD 2.4: "An administrator-only test-driving capability,
        restricted to `QuarryAdmin`, sets the logical clock to a supplied
        `to_iso8601` instant and reports the resulting `current_utc`."
        PRD 2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (403)."

        Design: Corner/rbac/site_manager_cannot_set_clock
        """
        resp = api.set_clock("2026-08-01T10:00:00Z", MANAGER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestPagination:
    def test_pagination_defaults_and_envelope(self, api):
        """PRD 2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10, with a minimum of 1 and a maximum of
        100. The `offset` parameter sets the number of items to skip and
        defaults to 0. ... List responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the
        envelope."
        PRD 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/pagination_defaults_and_envelope
        """
        create_site()
        resp = api.list_sites(MANAGER)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(data) == 1

    def test_pagination_limit_offset_with_filter(self, api):
        """PRD 2.3: "The `limit` parameter sets the maximum number of items
        returned ... The `offset` parameter sets the number of items to
        skip and defaults to 0. Unless otherwise specified, every list
        endpoint returns its resources sorted by `created_at` in ascending
        order."

        Design: Corner/endpoints/pagination_limit_offset_with_filter
        """
        site = create_site()
        # Advance the logical clock between creations so created_at is
        # strictly increasing; then created_at-ascending order is uniquely
        # determined (PRD 2.4 makes the logical clock the sole source of
        # every recorded timestamp, and PRD 2.3 is silent on tie-breaks).
        b1 = create_bench(site["id"], bench_label="B1", elevation_ft=1400,
                          acreage=5.0)
        set_clock("2026-08-01T00:01:00Z")
        create_bench(site["id"], bench_label="B2", elevation_ft=1380,
                     acreage=3.0)
        set_clock("2026-08-01T00:02:00Z")
        b3 = create_bench(site["id"], bench_label="B3", elevation_ft=1360,
                          acreage=2.0)
        data, meta = validate_paginated(api.list_benches(
            MANAGER, params={"site_id": site["id"], "limit": 2}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        data, meta = validate_paginated(api.list_benches(
            MANAGER, params={"site_id": site["id"], "limit": 2,
                             "offset": 2}))
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        # created_at ascending: the last-created bench lands on page 2.
        assert data[0]["id"] == b3["id"]
        assert b1["id"] != b3["id"]
