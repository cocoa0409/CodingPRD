"""Read surface: not-found behavior, parent scoping, and pagination."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_PAGE_LIMIT,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_draft_holdback,
    create_holdback_payload,
    set_logical_clock,
    setup_active_holdback,
    setup_escrow_file,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestNotFound:
    def test_holdback_get_unknown_id_returns_not_found(self, api):
        """PRD §2.9: "Existence: every identifier in the path must exist, and any sub-resource identifier must belong to the parent named in the path — otherwise `ERR_NOT_FOUND` (HTTP 404)."

        The error envelope shape is validated alongside the id.

        Design: Corner/entities/holdback_get_unknown_id_returns_not_found
        """
        set_logical_clock()
        resp = api.get_holdback(NON_EXISTENT_UUID, OFFICER)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["message"].strip(), "error carries a human-readable message"


class TestParentScoping:
    def test_subresource_lists_scoped_to_parent(self, api):
        """PRD §4: "GET | `/escrow/files/{id}/holdbacks` | List the holdbacks of an escrow file"
        PRD §2.10: "Requests that target nested resources are validated left to right along the path: each identifier must exist before the next is examined, and a sub-resource identifier must actually belong to the parent named in the path."

        The reverse list under file A returns exactly A's holdback; file B's
        holdback never leaks in.

        Design: Corner/entities/subresource_lists_scoped_to_parent
        """
        set_logical_clock()
        file_a = setup_escrow_file(property_address="1 Harbor Way")
        hb_a = create_draft_holdback(file_a["id"], repair_scope="Roof")
        file_b = setup_escrow_file(property_address="2 Cedar Ln")
        hb_b = create_draft_holdback(
            file_b["id"], repair_scope="Fence", repair_estimate_cents=50000,
            contingency_pct=10, funding_source="BUYER_DEPOSIT",
            overrun_responsibility="SELLER", expiration_terms="RELEASE_TO_BUYER",
            exterior_work_flag=False)

        data, meta = validate_paginated(api.list_file_holdbacks(file_a["id"], OFFICER))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == hb_a["id"]
        assert data[0]["repair_scope"] == "Roof"
        assert hb_b["id"] not in [h["id"] for h in data]

        data_b, meta_b = validate_paginated(api.list_file_holdbacks(file_b["id"], OFFICER))
        assert meta_b["total_count"] == 1 and data_b[0]["id"] == hb_b["id"]


class TestPagination:
    def test_bid_list_pagination_defaults(self, api):
        """PRD §2.3: "When `limit` is omitted it defaults to 10; its minimum is 1 and its maximum is 100. `offset` defaults to 0 and counts the number of items skipped. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        With 11 bids the default page holds 10 rows with has_more true; offset
        10 returns the final row with has_more false.

        Design: Corner/endpoints/bid_list_pagination_defaults
        """
        ctx = setup_active_holdback(repair_estimate_cents=2000000)
        hb_id = ctx["holdback"]["id"]
        for i in range(1, 12):
            submit_bid(hb_id, contractor_user_id=f"contr_p{i:02d}",
                       amount_cents=2000000 + i, scope_text=f"b{i:02d}")

        page1, meta1 = validate_paginated(api.list_bids(hb_id, OFFICER))
        assert len(page1) == DEFAULT_PAGE_LIMIT == 10
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_bids(hb_id, OFFICER, params={"offset": 10}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 11

        body = api.list_bids(hb_id, OFFICER).json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
