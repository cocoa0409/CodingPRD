"""List endpoints, pagination envelope, and reverse-reachability reads
(PRD §2.3, §4).
"""
from test_helpers import (
    TEST_USERS,
    make_category,
    make_sku,
    set_clock,
    validate_paginated,
)

ANON = TEST_USERS["anonymous_headers"]


class TestListPaginationDefaults:
    def test_list_categories_pagination_defaults(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit`
        and `offset`. The default value of `limit` is 10, with a minimum of 1
        and a maximum of 100; the default value of `offset` is 0. List
        endpoints sort results by `created_at` ascending unless otherwise
        specified. The `meta` block of every list response carries four
        pagination fields — `limit`, `offset`, `total_count`, and `has_more` —
        so clients can page deterministically without recomputing totals."

        Design: Corner/endpoints/list_categories_pagination_defaults
        """
        set_clock()
        for code in ("p1", "p2", "p3"):
            make_category(code=code, display_name=code.upper())
        data, meta = validate_paginated(api.list_categories(ANON))
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3
        assert {c["code"] for c in data} == {"p1", "p2", "p3"}

    def test_list_skus_limit_offset_interaction(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit`
        and `offset`. The default value of `limit` is 10, with a minimum of 1
        and a maximum of 100; the default value of `offset` is 0. List
        endpoints sort results by `created_at` ascending unless otherwise
        specified. The `meta` block of every list response carries four
        pagination fields — `limit`, `offset`, `total_count`, and `has_more` —
        so clients can page deterministically without recomputing totals."

        Design: Corner/cross_cutting_layers/pagination_limit_offset_interaction
        """
        set_clock()
        category = make_category(code="cpg", display_name="CPG")
        for code in ("pg1", "pg2", "pg3"):
            make_sku(category["id"], sku_code=code, base_price_cents=100)
        data, meta = validate_paginated(
            api.list_skus(ANON, params={"limit": 2, "offset": 1})
        )
        assert meta["limit"] == 2
        assert meta["offset"] == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 2
        # Three rows created under one logical-clock value share created_at;
        # the second page must hold two of the three created SKUs and exclude
        # whichever row sorted first.
        returned = {s["sku_code"] for s in data}
        assert len(returned) == 2
        assert returned <= {"pg1", "pg2", "pg3"}


class TestReverseReachability:
    def test_skus_under_category_returns_only_children(self, api):
        """PRD §4: "| GET | `/nabs/categories/{id}/skus` | SKUs under a
        category | PlatformAdmin, ShopStaff, Member, Anonymous |"
        PRD §3.1: "A `SKU` is filed under exactly one category via its
        `category_id`."

        Design: Corner/endpoints/reverse_reachability_skus_under_category
        """
        set_clock()
        c1 = make_category(code="rr1", display_name="RR1")
        c2 = make_category(code="rr2", display_name="RR2")
        make_sku(c1["id"], sku_code="rs1")
        make_sku(c2["id"], sku_code="rs2")
        data, meta = validate_paginated(api.list_category_skus(c1["id"], ANON))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["sku_code"] == "rs1"
        assert data[0]["category_id"] == c1["id"]
