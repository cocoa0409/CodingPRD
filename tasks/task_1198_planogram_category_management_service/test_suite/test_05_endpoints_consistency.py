"""Endpoint-level and consistency corner tests."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_category_payload,
    create_planogram_payload,
    create_retailer_payload,
    setup_draft_planogram_with_line,
    validate_paginated,
    validate_success,
)


class TestCategoryListing:
    def test_list_categories_returns_paginated(self, api, platform_admin_headers, category_manager_headers):
        """PRD §2.3: "The `meta` object of any list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.1: "categories can be listed under their retailer".

        Design: Corner/endpoints/list_categories_returns_paginated
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        validate_success(
            api.create_category(
                rid,
                create_category_payload(code="A", role="ROUTINE"),
                category_manager_headers,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_category(
                rid,
                create_category_payload(code="B", role="DESTINATION"),
                category_manager_headers,
            ),
            expected_status=201,
        )
        resp = api.list_categories(rid, category_manager_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert len(data) == 2
        assert meta["total_count"] == 2


class TestPlanogramLineDelete:
    def test_delete_planogram_line_returns_204(self, api, category_manager_headers):
        """PRD §4: "the single deletion operation in the API, removing a
        planogram line, returns `204 No Content`."
        PRD §3.4: "While a planogram remains in `DRAFT`, its author may also
        remove a line entirely; deletion answers with no content".

        Design: Corner/endpoints/delete_planogram_line_returns_204
        """
        retailer, category, supplier, product, pg, line = setup_draft_planogram_with_line()
        rid, cid, pgid, lid = retailer["id"], category["id"], pg["id"], line["id"]
        resp = api.delete_planogram_line(rid, cid, pgid, lid, category_manager_headers)
        assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"


class TestImmediateConsistency:
    def test_immediate_visibility_after_create(self, api, platform_admin_headers, category_manager_headers):
        """PRD §2.5: "Alongside the nested paths, the platform exposes flat
        retrieval: every resource type can be fetched by its bare `id` through
        a top-level single-resource path."

        Design: Corner/consistency_model/immediate_visibility_after_create
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        created = validate_success(
            api.create_category(rid, create_category_payload(code="C"), category_manager_headers),
            expected_status=201,
        )
        cid = created["id"]
        got = validate_success(api.get_category(rid, cid, category_manager_headers))
        assert got["code"] == "C"
        assert got["id"] == cid
