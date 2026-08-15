"""Work orders: release rules, computed weight, listing, scrap lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_work_order,
    create_work_order_payload,
    setup_shop,
    release_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWorkOrderRelease:
    def test_workorder_missing_required_field_returns_invalid_request(
        self, api, shop_manager_headers
    ):
        """PRD §2.11: "Request shape is next — required fields present, types valid,
        enum members valid, scalar ranges respected (masses strictly positive,
        percentages within their stated ranges, quantity at least 1, a period end
        strictly after its start) — with violations reported as `ERR_INVALID_REQUEST`."
        PRD §3.3: "A `ShopManager` releases a work order with a unique
        `work_order_no`, the `part_number` being fabricated, the `mold_id` of the
        tool, the `ply_book_id` of the approved book, a `quantity` of at least 1,
        and a `due_date`."

        Design: Corner/entities/workorder_missing_required_field_returns_invalid_request
        """
        shop = setup_shop(
            set_clock_to=None,
            mold_overrides={"mold_code": "MOLD-D2", "tooling_phase": "PRODUCTION"},
        )
        payload = create_work_order_payload(
            shop["mold"]["id"], shop["ply_book"]["id"], work_order_no="WO-D2"
        )
        del payload["quantity"]
        res = api.create_work_order(payload, shop_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_theoretical_weight_computed_at_creation(self, api, shop_manager_headers):
        """PRD §3.3: "At release, the order is born `RELEASED`, and the theoretical
        part weight is computed from the pinned revision: the sum, over every ply, of
        that ply's `areal_weight_g_m2` multiplied by `part_area_m2`, divided by
        `target_fiber_volume_pct`, rounded half-up to one decimal place and stored as
        `target_part_weight_g`."
        PRD §3.3: "each work order captures the book's `version` at its own creation
        into `pinned_ply_book_version`".
        PN-100 rev A: (200 + 300) g/m2 * 2.0 m2 / 0.5 = 2000.0 g.

        Design: Corner/calculations/theoretical_weight_computed_at_creation
        """
        shop = setup_shop(
            set_clock_to=None,
            mold_overrides={"mold_code": "MOLD-TW1", "tooling_phase": "PRODUCTION"},
        )
        order = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    shop["mold"]["id"],
                    shop["ply_book"]["id"],
                    work_order_no="WO-TW1",
                    quantity=4,
                ),
                shop_manager_headers,
            ),
            201,
        )
        assert_work_order(order)
        assert order["target_part_weight_g"] == pytest.approx(2000.0)
        assert order["pinned_ply_book_version"] == shop["ply_book"]["version"]

    def test_prototype_quantity_cap_rejected(self, api, shop_manager_headers):
        """PRD §3.3: "on a tool in `PROTOTYPE` or `TRANSITION` phase the `quantity`
        may not exceed 5 — the prototype lot-size cap — with larger lots refused as
        `ERR_PROTOTYPE_QUANTITY_CAP`."

        Design: Corner/validations/prototype_quantity_cap_rejected
        """
        shop = setup_shop(set_clock_to=None, mold_overrides={"mold_code": "MOLD-QC1"})
        res = api.create_work_order(
            create_work_order_payload(
                shop["mold"]["id"],
                shop["ply_book"]["id"],
                work_order_no="WO-QC1",
                quantity=6,
            ),
            shop_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_PROTOTYPE_QUANTITY_CAP, expected_status=409)


class TestWorkOrderListing:
    def test_workorder_list_pagination_and_filter(self, api, shop_manager_headers):
        """PRD §2.3: "All list endpoints return resources sorted by creation
        timestamp in ascending order, and every list response carries `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §3.3: "The work order list may be filtered by `mold_id`, `ply_book_id`,
        or `status`, with `limit` and `offset` paging as described in §2.3."

        Design: Corner/endpoints/workorder_list_pagination_and_filter
        """
        shop = setup_shop(
            set_clock_to=None,
            mold_overrides={"mold_code": "MOLD-PG1", "tooling_phase": "PRODUCTION"},
        )
        from test_helpers import create_mold

        mold2 = create_mold(mold_code="MOLD-PG2", tooling_phase="PRODUCTION")
        wo1 = release_work_order(shop, work_order_no="WO-PG1")
        wo2 = release_work_order(shop, work_order_no="WO-PG2")
        validate_success(
            api.create_work_order(
                create_work_order_payload(
                    mold2["id"], shop["ply_book"]["id"], work_order_no="WO-PG3"
                ),
                shop_manager_headers,
            ),
            201,
        )

        data1, meta1 = validate_paginated(
            api.list_work_orders(
                shop_manager_headers, params={"mold_id": shop["mold"]["id"], "limit": 1, "offset": 0}
            )
        )
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_work_orders(
                shop_manager_headers, params={"mold_id": shop["mold"]["id"], "limit": 1, "offset": 1}
            )
        )
        assert len(data2) == 1
        assert meta2["has_more"] is False

        assert data1[0]["id"] != data2[0]["id"]
        assert {data1[0]["id"], data2[0]["id"]} == {wo1["id"], wo2["id"]}
        assert data1[0]["mold_id"] == shop["mold"]["id"]
        assert data2[0]["mold_id"] == shop["mold"]["id"]


class TestScrapLockdown:
    def test_scrapped_workorder_rejects_start_layup(self, api, shop_manager_headers, laminator_headers):
        """PRD §3.7: "`ACCEPTED` and `SCRAPPED` are terminal: no further transition
        exists from either, and attempts are refused with `ERR_INVALID_STATE`."
        PRD §3.7: "always recording `scrap_reason` as `MANUAL`".

        Design: Corner/state_machines/scrapped_workorder_rejects_start_layup
        """
        shop = setup_shop(
            mold_overrides={"mold_code": "MOLD-SC1", "tooling_phase": "PRODUCTION"}
        )
        order = release_work_order(shop, work_order_no="WO-SC1")
        scrapped = validate_success(
            api.scrap_work_order(order["id"], shop_manager_headers), 200
        )
        assert scrapped["status"] == "SCRAPPED"
        assert scrapped["scrap_reason"] == "MANUAL"
        res = api.start_layup(order["id"], laminator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
