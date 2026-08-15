"""Program setup defaults, catalog basics, pagination, and FK-filtered listing."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_merch_program,
    assert_preorder_campaign,
    create_active_program,
    create_approved_design,
    create_design_payload,
    create_event,
    create_open_campaign,
    create_open_event,
    create_pos_order,
    create_program,
    create_program_payload,
    create_variant,
    open_drawer,
    place_preorder,
    setup_open_campaign_shop,
    setup_storefront,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestProgramDefaults:
    def test_create_program_applies_documented_defaults(self, api):
        """PRD §3.1: "A new program starts in `SETUP` with
        `undistributed_profit_cents` and `distributed_profit_cents` both at 0
        and `ops_run_index` at 0."
        PRD §3.1: "optionally overriding five policy knobs:
        `over_short_tolerance_cents` (default 500 — five dollars of drawer
        slack), `exchange_window_days` (default 14), `pickup_window_days`
        (default 7), `register_buffer_minutes` (default 30), and
        `deposit_floor_cents` (default 500)."

        Design: Corner/entities/create_program_applies_documented_defaults
        """
        program = validate_success(
            api.create_program(
                create_program_payload(
                    name="Spirit 2026",
                    school_year="2026-2027",
                    valuation_method="FIFO",
                ),
                DIRECTOR,
            ),
            201,
        )
        assert_merch_program(program)
        assert program["status"] == "SETUP"
        assert program["over_short_tolerance_cents"] == 500
        assert program["exchange_window_days"] == 14
        assert program["pickup_window_days"] == 7
        assert program["register_buffer_minutes"] == 30
        assert program["deposit_floor_cents"] == 500
        assert program["undistributed_profit_cents"] == 0
        assert program["distributed_profit_cents"] == 0
        assert program["ops_run_index"] == 0

    def test_get_nonexistent_program_returns_404(self, api):
        """PRD §2.8: "Path identifiers are validated left to right — the
        program first, then the resource within it — and the first missing
        identifier yields its own 404: `ERR_PROGRAM_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`,
        `ERR_VARIANT_NOT_FOUND`, `ERR_DROP_NOT_FOUND`, `ERR_PO_NOT_FOUND`,
        `ERR_CAMPAIGN_NOT_FOUND`, `ERR_PREORDER_NOT_FOUND`,
        `ERR_EVENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_EXCHANGE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, or
        `ERR_ALLOCATION_RUN_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_program_returns_404
        """
        res = api.get_program(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_FOUND, 404)

    def test_list_programs_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items:
        it defaults to 10 when omitted, accepts a minimum of 1, and is capped
        at a maximum of 100."
        PRD §2.3: "every list response includes `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_programs_pagination_envelope
        """
        for name in ("P1", "P2", "P3"):
            create_program(name=name)

        data, meta = validate_paginated(api.list_programs(DIRECTOR, params={"limit": 2}))
        assert len(data) == 2, f"limit=2 must return exactly 2 items, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        data2, meta2 = validate_paginated(
            api.list_programs(DIRECTOR, params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        data3, meta3 = validate_paginated(api.list_programs(DIRECTOR))
        assert meta3["limit"] == 10, "default limit is 10 when omitted"
        assert len(data3) == 3


class TestCatalogBasics:
    def test_variant_starts_with_zero_inventory_and_computed_defaults(self, api):
        """PRD §2.9: "`on_hand_qty` is the physical units on the shelf: it
        starts at 0, grows with purchase-order receipts, shrinks with
        point-of-sale sales, preorder fulfillments, and exchange swaps, and
        grows back when an online reservation expires."
        PRD §2.9: "a variant is `sellable` when its program is `ACTIVE`, its
        design is `APPROVED`, and it either belongs to no seasonal drop or its
        drop is currently `OPEN`."
        PRD §2.9: "A variant's `landed_unit_cost_cents` — the full per-unit
        cost including amortized licensing — is 0 until the first receipt
        against a purchase order for that variant (§3.5)."

        Design: Corner/entities/variant_starts_with_zero_inventory_and_computed_defaults
        """
        program = create_active_program()
        design = create_approved_design(program["id"])
        variant = validate_success(
            api.create_product_variant(
                {
                    "program_id": program["id"],
                    "design_id": design["id"],
                    "size": "M",
                    "unit_price_cents": 2500,
                },
                MANAGER,
            ),
            201,
        )
        assert variant["on_hand_qty"] == 0
        assert variant["reserved_online_qty"] == 0
        assert variant["available_qty"] == 0
        assert variant["landed_unit_cost_cents"] == 0
        assert variant["sellable"] is True

    def test_design_royalty_pct_out_of_range_rejected(self, api):
        """PRD §3.2: "a `royalty_pct` (the licensor's cut as a fraction of the
        sales price, between 0 and 1 inclusive)"
        PRD §2.8: "Required fields are present, enum values are valid, and
        ranges hold: `qty` at least 1, percentage fields between 0 and 1
        inclusive, `closes_at` strictly after `opens_at`, `ends_at` strictly
        after `starts_at`, `amount_cents` at least 1. Violations are
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/design_royalty_pct_out_of_range_rejected
        """
        program = create_program()
        res = api.create_design(
            create_design_payload(program["id"], name="Bad", royalty_pct=1.5),
            MANAGER,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_vendor_missing_required_name_returns_invalid_request(self, api):
        """PRD §3.2: "A `StoreManager` registers each **Vendor** under its
        program with a `name` and `contact_email`, optionally seeding its
        `quotes` at the same time."
        PRD §2.8: "Required fields are present, enum values are valid, and
        ranges hold: `qty` at least 1, percentage fields between 0 and 1
        inclusive, `closes_at` strictly after `opens_at`, `ends_at` strictly
        after `starts_at`, `amount_cents` at least 1. Violations are
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_vendor_missing_required_name_returns_invalid_request
        """
        program = create_program()
        res = api.create_vendor(
            {"program_id": program["id"], "contact_email": "x@co.com"}, MANAGER
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_design_created_in_draft_initial_state(self, api):
        """PRD §3.2: "New designs start in `DRAFT` with `revision_count` at 0."

        Design: Corner/entities/design_created_in_draft_initial_state
        """
        program = create_active_program()
        design = validate_success(
            api.create_design(
                create_design_payload(
                    program["id"], royalty_pct=0.05, licensing_fee_cents=1000
                ),
                MANAGER,
            ),
            201,
        )
        assert design["status"] == "DRAFT"
        assert design["revision_count"] == 0

    def test_duplicate_variant_rejected(self, api):
        """PRD §3.3: "The pair of design and size is unique within a program —
        a second variant with the same `design_id` and `size` is rejected with
        `ERR_DUPLICATE_VARIANT`."

        Design: Corner/errors/duplicate_variant_rejected
        """
        program = create_active_program()
        design = create_approved_design(program["id"])
        create_variant(program["id"], design["id"], size="M", unit_price_cents=2500)

        res = api.create_product_variant(
            {
                "program_id": program["id"],
                "design_id": design["id"],
                "size": "M",
                "unit_price_cents": 2600,
            },
            MANAGER,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_VARIANT, 409)

        ok = validate_success(
            api.create_product_variant(
                {
                    "program_id": program["id"],
                    "design_id": design["id"],
                    "size": "L",
                    "unit_price_cents": 2600,
                },
                MANAGER,
            ),
            201,
        )
        assert ok["id"], "a different size for the same design must be accepted"


class TestForeignKeyFilteredListing:
    def test_filtered_list_orders_by_event(self, api):
        """PRD §2.3: "List endpoints also accept optional foreign-key filters
        that restrict results to matching records — `program_id`, `design_id`,
        `drop_id`, `variant_id`, `vendor_id`, `campaign_id`,
        `selected_vendor_id`, `event_id`, `customer_user_id`, `order_id`,
        `original_variant_id`, and `new_variant_id`"

        Design: Corner/endpoints/filtered_list_orders_by_event
        """
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        variant_id = shop["variant"]["id"]
        event1 = create_open_event(program_id, register="GYM-1", name="E1")
        event2 = create_event(program_id, register="GYM-2", name="E2")
        open_drawer(event2["id"], cashier_id="cashier-02")
        order1 = create_pos_order(
            program_id, event1["id"], variant_id, 1, customer_user_id="w1"
        )
        create_pos_order(
            program_id,
            event2["id"],
            variant_id,
            2,
            customer_user_id="w2",
            cashier_id="cashier-02",
        )

        data, meta = validate_paginated(
            api.list_orders(TREASURER, params={"event_id": event1["id"]})
        )
        assert meta["total_count"] == 1, f"expected exactly 1 order, got {meta}"
        assert data[0]["id"] == order1["id"]
        assert data[0]["event_id"] == event1["id"]

    def test_reverse_reachability_preorders_by_campaign(self, api):
        """PRD §2.3: "List endpoints also accept optional foreign-key filters
        that restrict results to matching records — `program_id`, `design_id`,
        `drop_id`, `variant_id`, `vendor_id`, `campaign_id`,
        `selected_vendor_id`, `event_id`, `customer_user_id`, `order_id`,
        `original_variant_id`, and `new_variant_id`"

        Design: Corner/endpoints/reverse_reachability_preorders_by_campaign
        """
        shop = setup_open_campaign_shop(goal_units=10)
        program_id = shop["program"]["id"]
        campaign_id = shop["campaign"]["id"]
        variant_id = shop["variant"]["id"]
        p1 = place_preorder(program_id, campaign_id, variant_id, "cust-71", 1)
        p2 = place_preorder(program_id, campaign_id, variant_id, "cust-72", 2)

        data, meta = validate_paginated(
            api.list_preorders(TREASURER, params={"campaign_id": campaign_id})
        )
        ids = {row["id"] for row in data}
        assert meta["total_count"] == 2
        assert ids == {p1["id"], p2["id"]}
