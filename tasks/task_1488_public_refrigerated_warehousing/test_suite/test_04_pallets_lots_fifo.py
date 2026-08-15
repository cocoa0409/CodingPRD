"""Pallet reads, list pagination, and FIFO allocation ordering."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    allocate_order,
    create_customer_with_card,
    create_order,
    create_zone,
    list_order_allocations,
    receive_stock,
    setup_stocked_account,
    submit_order,
    validate_error,
    validate_paginated,
)

OPERATOR = TEST_USERS["warehouse_operator_headers"]


class TestPalletNotFound:
    def test_get_nonexistent_pallet_returns_not_found(self, api):
        """PRD §2.9: "Existence, applied to all resource endpoints: path
        identifiers and foreign-key references in the body are resolved in
        left-to-right order, and the first reference that does not exist yields
        `ERR_NOT_FOUND`."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/get_nonexistent_pallet_returns_not_found
        """
        resp = api.get_pallet(NON_EXISTENT_UUID, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)


class TestPalletPagination:
    def test_default_limit_and_offset_pagination(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return. If not provided, it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies the number of items to
        skip and defaults to 0."
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/entities/pallet_list_pagination_defaults_and_filter
        """
        sc = setup_stocked_account(customer_name="Page Co", zone_code="FZ-PG",
                                   capacity_pallets=20, pallets=12)
        page1, meta1 = validate_paginated(
            api.list_pallets(OPERATOR, params={"lot_id": sc["lot_id"]}))
        assert len(page1) == 10, f"default limit is 10, got {len(page1)}"
        assert meta1["limit"] == 10 and meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_pallets(OPERATOR, params={"lot_id": sc["lot_id"],
                                               "offset": 10}))
        assert len(page2) == 2, f"offset 10 returns the remaining 2, got {len(page2)}"
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

        ids1 = {p["id"] for p in page1}
        ids2 = {p["id"] for p in page2}
        assert ids1.isdisjoint(ids2), "pages must be disjoint"
        assert len(ids1 | ids2) == 12, "pages together cover all 12 pallets"


class TestFifoAllocationOrder:
    def test_oldest_production_date_drains_first(self, api):
        """PRD §3.5: "Candidates are ordered by their lot's `production_date`
        ascending, then by the pallet's `received_at` ascending, then by
        `created_at` ascending — the pallet identifier is never used as an
        ordering key."
        PRD §3.5: "When the fill is complete, meaning `allocated_pallets` now
        equals `requested_pallets`, the order advances to `ALLOCATED`; a partial
        or empty fill leaves it at `SHORTED`."

        Design: Corner/calculations/fifo_allocation_oldest_production_date_first
        """
        customer, _card = create_customer_with_card("Fifo Co")
        zone = create_zone("FZ-FF", capacity_pallets=10, dock_doors=2)
        # NEWA: newer production date, received EARLIER (2026-08-02).
        newer = receive_stock(customer["id"], zone["id"], 2, lot_code="NEWA",
                              production_date="2026-01-10",
                              window_start="2026-08-02T08:00:00Z",
                              window_end="2026-08-02T10:00:00Z")
        # OLDB: older production date, received LATER (2026-08-03).
        older = receive_stock(customer["id"], zone["id"], 2, lot_code="OLDB",
                              production_date="2026-01-05",
                              window_start="2026-08-03T08:00:00Z",
                              window_end="2026-08-03T10:00:00Z")
        order = submit_order(create_order(customer["id"], requested_pallets=3)["id"],
                             customer["id"])
        allocate_order(order["id"])

        allocations = list_order_allocations(order["id"])
        assert len(allocations) == 3
        lot_ids = [a["lot_id"] for a in allocations]
        assert lot_ids.count(older["lot_id"]) == 2, (
            "the older-production lot drains first (both of its pallets)")
        assert lot_ids.count(newer["lot_id"]) == 1, (
            "only one pallet from the newer lot despite its earlier receipt")
        # Allocations list sorted created_at ASC: the first two picks are OLDB.
        assert lot_ids[0] == older["lot_id"] and lot_ids[1] == older["lot_id"]
        assert lot_ids[2] == newer["lot_id"]
