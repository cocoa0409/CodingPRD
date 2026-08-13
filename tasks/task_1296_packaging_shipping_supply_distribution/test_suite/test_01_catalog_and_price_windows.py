"""Catalog creation, computed product fields, listing envelope, and
half-open quantity-break price windows."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    CATALOG,
    OPS,
    add_line,
    assert_product,
    assert_quantity_break,
    create_account,
    create_draft_order,
    create_inventory,
    create_product_payload,
    create_quantity_break_payload,
    create_stock_product,
    create_warehouse,
    get_success_data,
    make_buyer_headers,
    NON_EXISTENT_UUID,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProductCreation:
    def test_stock_product_defaults_and_parcel_ship_method(self, api):
        """PRD section 3.2: "The system derives `ship_method` from the oversize
        flag — `PARCEL` when the item is not oversize, `FREIGHT` when it is —
        both at creation and again on any catalog update that changes the flag."
        PRD section 3.2: "`lead_time_days` defaults to zero, must remain zero
        for stock items, and must be strictly positive for custom-print items."

        Design: Corner/entities/entity_creation_product_computed_ship_method_and_defaults
        """
        payload = create_product_payload(sku="TP-1", name="Tape Roll", category="TAPE",
                                         base_price_cents=350, pallet_qty=100,
                                         weight_lbs_per_unit=1)
        data = validate_success(api.create_product(payload, CATALOG), expected_status=201)
        assert_product(data)
        assert data["ship_method"] == "PARCEL"
        assert data["oversize"] is False
        assert data["is_custom_print"] is False
        assert data["lead_time_days"] == 0

    def test_oversize_product_computes_freight_ship_method(self, api):
        """PRD section 3.2: "The system derives `ship_method` from the oversize
        flag — `PARCEL` when the item is not oversize, `FREIGHT` when it is —
        both at creation and again on any catalog update that changes the flag."

        Design: Corner/entities/entity_creation_product_computed_ship_method_and_defaults
        """
        payload = create_product_payload(sku="PL-1", name="Pallet", base_price_cents=9000,
                                         pallet_qty=10, weight_lbs_per_unit=400,
                                         density_pcf=12, oversize=True)
        data = validate_success(api.create_product(payload, CATALOG), expected_status=201)
        assert_product(data)
        assert data["ship_method"] == "FREIGHT"
        assert data["oversize"] is True


class TestProductListPagination:
    def test_products_pagination_envelope(self, api, platform_admin_headers):
        """PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD section 2.3: "The `limit` parameter sets the maximum number of
        items returned; it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter sets the number of items to skip and
        defaults to 0."

        Design: Corner/entities/entity_list_pagination_envelope
        """
        create_stock_product(sku="A-1", base_price_cents=100, pallet_qty=10,
                             weight_lbs_per_unit=1)
        create_stock_product(sku="A-2", base_price_cents=100, pallet_qty=10,
                             weight_lbs_per_unit=1)

        data, meta = validate_paginated(api.list_products(
            platform_admin_headers, params={"limit": 1, "offset": 0}))
        assert len(data) == 1, f"page 1 must hold exactly 1 item, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

        data2, meta2 = validate_paginated(api.list_products(
            platform_admin_headers, params={"limit": 1, "offset": 1}))
        assert len(data2) == 1
        assert meta2["has_more"] is False
        assert data2[0]["id"] != data[0]["id"]


class TestNotFoundAndMalformed:
    def test_get_nonexistent_account_returns_not_found(self, api, platform_admin_headers):
        """PRD section 2.8: "the request is rejected immediately with
        `ERR_NOT_FOUND` (HTTP 404) at the first path segment that does not
        correspond to an existing resource."

        Design: Corner/entities/entity_get_nonexistent_id_returns_not_found
        """
        resp = api.get_account(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_product_create_missing_base_price_rejected(self, api):
        """PRD section 3.2: "Creating a **Product** takes a catalog-unique `sku`,
        a display `name`, a merchandising `category` of `BOXES`, `MAILERS`,
        `TAPE`, `CUSHIONING`, or `LABELS`, a strictly positive `base_price_cents`"
        PRD section 2.9: "Malformed payloads — missing required fields, wrong
        types, enum violations, out-of-range numbers — surface last as
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/entity_product_create_missing_required_field_rejected
        """
        payload = create_product_payload(sku="X-1", name="X", category="TAPE",
                                         pallet_qty=10, weight_lbs_per_unit=1)
        del payload["base_price_cents"]
        resp = api.create_product(payload, CATALOG)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_product_create_invalid_category_enum_rejected(self, api):
        """PRD section 3.2: "a merchandising `category` of `BOXES`, `MAILERS`,
        `TAPE`, `CUSHIONING`, or `LABELS`"
        PRD section 2.9: "Malformed payloads — missing required fields, wrong
        types, enum violations, out-of-range numbers — surface last as
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/entity_enum_constraint_invalid_value_rejected
        """
        payload = create_product_payload(sku="X-9", name="X", category="FURNITURE",
                                         base_price_cents=100, pallet_qty=10,
                                         weight_lbs_per_unit=1)
        resp = api.create_product(payload, CATALOG)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestQuantityBreakResource:
    def test_quantity_break_shape_and_delete(self, api):
        """PRD section 2.4: "Quantity breaks are the single exception: a
        quantity break carries only `id` and `created_at`; both `updated_at`
        and `version` are absent."
        PRD section 3.2: "A product's breaks are listed in ascending `min_qty`
        order, and removing a break returns 204 with no content."

        Design: Corner/entities/entity_quantity_break_common_fields_false_immutability
        """
        prod = create_stock_product(sku="B-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        brk = validate_success(api.create_quantity_break(
            prod["id"],
            create_quantity_break_payload(min_qty=10, unit_price_cents=90, sort_seq=1),
            CATALOG), expected_status=201)
        assert_quantity_break(brk)

        resp = api.delete_quantity_break(brk["id"], CATALOG)
        assert resp.status_code == 204, f"DELETE quantity break must return 204, got {resp.status_code}"

        remaining = get_success_data(api.list_quantity_breaks(prod["id"], CATALOG))
        assert remaining == [], f"expected empty break list after delete, got {remaining}"


class TestPriceWindowOverlap:
    """Half-open [effective_from, effective_to) price windows on one product."""

    def _setup_product_with_adjacent_breaks(self, api):
        prod = create_stock_product(sku="BX-300", name="Mailer Box", category="MAILERS",
                                    base_price_cents=500, pallet_qty=500)
        brk_a = validate_success(api.create_quantity_break(
            prod["id"],
            create_quantity_break_payload(min_qty=50, unit_price_cents=450, sort_seq=1,
                                          effective_from="2026-08-01T00:00:00Z",
                                          effective_to="2026-08-10T00:00:00Z"),
            CATALOG), expected_status=201)
        brk_b = validate_success(api.create_quantity_break(
            prod["id"],
            create_quantity_break_payload(min_qty=50, unit_price_cents=440, sort_seq=2,
                                          effective_from="2026-08-10T00:00:00Z",
                                          effective_to="2026-08-20T00:00:00Z"),
            CATALOG), expected_status=201)
        return prod, brk_a, brk_b

    def test_adjacent_window_allowed_strict_overlap_rejected(self, api):
        """PRD section 3.2: "Two breaks for the same product at the same
        `min_qty` may not have overlapping windows — the attempt is rejected
        with `ERR_OVERLAPPING_PRICE_WINDOW` (HTTP 422) — though pure adjacency,
        where one break's window ends exactly as the next begins, is allowed."

        Design: Difficulty/resource_temporal_overlap/price_window_half_open_overlap_and_adjacency
        """
        prod, brk_a, brk_b = self._setup_product_with_adjacent_breaks(api)
        assert_quantity_break(brk_a)
        assert_quantity_break(brk_b)  # adjacency at 2026-08-10T00:00:00Z is not an overlap

        resp = api.create_quantity_break(
            prod["id"],
            create_quantity_break_payload(min_qty=50, unit_price_cents=430, sort_seq=3,
                                          effective_from="2026-08-05T00:00:00Z",
                                          effective_to="2026-08-12T00:00:00Z"),
            CATALOG)
        validate_error(resp, ApiErrorId.ERR_OVERLAPPING_PRICE_WINDOW)

    def test_exclusive_end_pricing_uses_new_window(self, api):
        """PRD section 3.2: "a half-open effective window from `effective_from`
        (inclusive) to `effective_to` (exclusive); a null `effective_to` means
        the window is open-ended."
        PRD section 3.2: "the candidate set for a line is every break of that
        product whose `min_qty` is at most the line quantity and whose window
        contains the current logical clock; the candidate with the largest
        `min_qty` wins"

        Design: Difficulty/resource_temporal_overlap/price_window_half_open_overlap_and_adjacency
        """
        prod, brk_a, brk_b = self._setup_product_with_adjacent_breaks(api)
        wh = create_warehouse(code="ATL", zone=2)
        acct = create_account()
        create_inventory(prod["id"], wh["id"], 1000)
        set_clock("2026-08-10T12:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5)
        line = add_line(order["id"], acct["id"], prod["id"], 50)
        # Break A's exclusive end 2026-08-10T00:00:00Z has passed; B governs.
        assert line["unit_price_cents"] == 440, (
            f"expected the 08-10 window break price 440, got {line['unit_price_cents']}")
