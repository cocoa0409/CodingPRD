"""Catalog and account foundations: creation defaults, computed fields,
not-found handling, list pagination envelope, and the account tier ledger
(boundary thresholds + ratchet)."""
from test_helpers import (
    ApiErrorId,
    MGR,
    assert_account,
    assert_branch,
    assert_stock_lot,
    create_confirmed_order,
    invoice_order,
    is_valid_uuid,
    make_account,
    make_branch,
    make_lot,
    make_order,
    make_product,
    order_line,
    setup_branch_account_product_lot,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

COUNTER = TEST_USERS["counter_rep_headers"]
WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


class TestCreationDefaults:
    def test_branch_create_defaults_applied(self, api):
        """PRD §3.1: "An optional `willcall_cutoff_minutes` governs the morning-rush protocol described in §3.6 and defaults to 90 when omitted."
        PRD §3.1: "A new branch begins with `status` `OPEN`, `posture` `NORMAL`, and a `seasonal_pool_units` of zero."
        PRD §2.4: "Every primary resource — Branch, Account, Product, StockLot, SeasonalProgram, SeasonalCommitment, SalesOrder, BackorderRequest, ServiceCenter, WarrantyClaim, and ReturnAuthorization — carries a standard quartet of system-managed fields: `id`, a server-minted UUID with no type prefix"

        Design: Corner/entities/branch_create_defaults_applied
        """
        resp = api.create_branch(
            {
                "branch_code": "PHX-12",
                "hazmat_storage_certified": True,
                "peak_season_start": "04-01",
                "peak_season_end": "09-30",
            },
            MGR,
        )
        data = validate_success(resp, 201)
        assert_branch(data)
        assert data["willcall_cutoff_minutes"] == 90, (
            f"omitted willcall_cutoff_minutes must default to 90: {data}"
        )
        assert data["status"] == "OPEN", f"new branch begins OPEN: {data}"
        assert data["posture"] == "NORMAL", f"new branch begins NORMAL: {data}"
        assert data["seasonal_pool_units"] == 0, f"new branch pool starts at zero: {data}"
        assert is_valid_uuid(data["id"]) and "-" in data["id"], "id must be a bare UUID"
        assert isinstance(data["version"], int), "version must be an integer"

    def test_account_computed_tier_input_ignored(self, api):
        """PRD §3.2: "New accounts begin `ACTIVE` at tier `PRO` with `ytd_volume_cents` zero."
        PRD §3.2: "Optional onboarding fields are the `hazmat_delivery_license_expiry` date, the `willcall_authorized` flag (default true), and the `credit_hold` flag (default false)."
        PRD §2.11: "New accounts start at `PRO` with a zeroed ledger."

        Design: Corner/entities/account_computed_tier_input_ignored
        """
        resp = api.create_account(
            {"account_number": "DLR-1", "account_type": "DEALER"}, MGR
        )
        data = validate_success(resp, 201)
        assert_account(data)
        assert data["tier"] == "PRO", f"tier is computed; new account is always PRO: {data}"
        assert data["ytd_volume_cents"] == 0, f"ledger starts zeroed: {data}"
        assert data["credit_hold"] is False, f"credit_hold defaults false: {data}"
        assert data["willcall_authorized"] is True, f"willcall_authorized defaults true: {data}"
        assert data["status"] == "ACTIVE", f"new accounts begin ACTIVE: {data}"

    def test_stock_lot_hazmat_class_copied_and_available_computed(self, api):
        """PRD §3.1: "At receipt the lot's `qty_available` equals its `qty_on_hand`, and its `hazmat_storage_class` is copied from the product's `hazmat_class` and frozen forever after."
        PRD §3.1: "Availability is a three-bucket ledger: `qty_reserved_willcall` counts units held for confirmed counter orders not yet picked up or released, `qty_reserved_route` counts units held for confirmed truck orders not yet shipped or released, and `qty_available` is what remains of `qty_on_hand` after both reservation buckets — it may never go negative."

        Design: Corner/entities/stock_lot_hazmat_class_copied_and_available_computed
        """
        branch = make_branch(api, branch_code="PHX-12", hazmat_storage_certified=True)
        product = make_product(
            api,
            sku="ACID-4X1",
            product_family="CHEMICAL",
            hazmat_class="CORROSIVE_8",
            base_price_cents=4000,
        )
        resp = api.create_stock_lot(
            {
                "branch_id": branch["id"],
                "product_id": product["id"],
                "lot_code": "L1",
                "qty_on_hand": 12,
            },
            WAREHOUSE,
        )
        lot = validate_success(resp, 201)
        assert_stock_lot(lot)
        assert lot["hazmat_storage_class"] == "CORROSIVE_8", (
            f"hazmat_storage_class must be copied from the product: {lot}"
        )
        assert lot["qty_available"] == 12, f"at receipt qty_available == qty_on_hand: {lot}"
        assert lot["qty_reserved_willcall"] == 0
        assert lot["qty_reserved_route"] == 0


class TestRetrievalAndListing:
    def test_product_get_not_found(self, api):
        """PRD §2.9: "Next, existence: every path- or body-referenced id — branch, account, product, lot, program, commitment, order, claim, center, or RMA — must resolve, else `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/product_get_not_found
        """
        resp = api.get_product("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", MGR)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    def test_order_line_immutable_no_update_endpoint(self, api):
        """PRD §2.9: "Next, existence: every path- or body-referenced id — branch, account, product, lot, program, commitment, order, claim, center, or RMA — must resolve, else `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."
        PRD §2.4: "OrderLine is the sole exception: as a lightweight child record it carries only `id` and `created_at` — both `updated_at` and `version` are absent from it."

        Design: Corner/entities/order_line_immutable_no_update_endpoint
        """
        # Lines exist only under a parent order; an unknown order id must route
        # through the lines listing and resolve as a 404.
        resp = api.list_order_lines(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", MGR
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    def test_orders_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and is clamped at a maximum of 100."
        PRD §2.3: "All list responses are sorted by `created_at` in ascending order, and the `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/orders_list_pagination_envelope
        """
        branch = make_branch(api, hazmat_storage_certified=False)
        account = make_account(api, account_number="DLR-2")
        product = make_product(api, sku="NET-1", product_family="PARTS", base_price_cents=900)
        make_order(
            api,
            branch_id=branch["id"],
            account_id=account["id"],
            channel="WILL_CALL",
            lines=[order_line(product["id"], 1)],
        )
        resp = api.list_orders(COUNTER, params={"branch_id": branch["id"]})
        assert resp.status_code == 200, f"list orders must succeed: {resp.text}"
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["response_type"] == "array", f"list responses are arrays: {body}"
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, f"one order exists on this branch: {meta}"
        assert meta["has_more"] is False
        assert meta["limit"] == 10, f"default limit is 10: {meta}"
        assert meta["offset"] == 0
        assert len(data) == 1


class TestAccountTierBoundary:
    def test_tier_threshold_exact_boundary_is_elite(self, api):
        """PRD §2.11: "An account's `tier` — one of `PRO`, `ELITE`, or `PREMIER` — is derived from this ledger: at least 5,000,000 cents ($50,000) earns `PREMIER`, at least 2,000,000 cents ($20,000) earns `ELITE`, and anything below earns `PRO`."
        PRD §2.11: "The boundary is inclusive — an invoice landing exactly on 2,000,000 cents makes the account `ELITE`."

        Design: Difficulty/boundary_precision_check/tier_threshold_exact_boundary_is_elite
        """
        branch, account, p1, _lot1 = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-700"},
            product_over={
                "sku": "HEATER-A",
                "product_family": "EQUIPMENT",
                "base_price_cents": 1_999_999,
            },
            lot_over={"qty_on_hand": 5},
        )
        p2 = make_product(api, sku="SCREW-1", product_family="PARTS", base_price_cents=1)
        make_lot(api, branch_id=branch["id"], product_id=p2["id"], qty_on_hand=100)

        # Order 1: subtotal 1,999,999 — one cent below the ELITE threshold.
        o1 = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(p1["id"], 1)],
        )
        invoice_order(o1["id"], api)
        acct = validate_success(api.get_account(account["id"], MGR))
        assert acct["ytd_volume_cents"] == 1_999_999
        assert acct["tier"] == "PRO", f"1,999,999 cents is below the ELITE boundary: {acct}"

        # Order 2: +1 cent lands the ledger exactly on 2,000,000.
        o2 = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(p2["id"], 1)],
        )
        invoice_order(o2["id"], api)
        acct = validate_success(api.get_account(account["id"], MGR))
        assert acct["ytd_volume_cents"] == 2_000_000
        assert acct["tier"] == "ELITE", (
            f"an invoice landing exactly on 2,000,000 cents makes the account ELITE: {acct}"
        )

    def test_tier_threshold_exact_boundary_is_premier(self, api):
        """PRD §2.11: "An account's `tier` — one of `PRO`, `ELITE`, or `PREMIER` — is derived from this ledger: at least 5,000,000 cents ($50,000) earns `PREMIER`, at least 2,000,000 cents ($20,000) earns `ELITE`, and anything below earns `PRO`."
        PRD §2.11: "The boundary is inclusive — an invoice landing exactly on 2,000,000 cents makes the account `ELITE`."

        Design: Difficulty/boundary_precision_check/tier_threshold_exact_boundary_is_elite
        """
        branch, account, p1, _lot1 = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            product_over={
                "sku": "HEATER-B",
                "product_family": "EQUIPMENT",
                "base_price_cents": 4_999_999,
            },
            lot_over={"qty_on_hand": 5},
        )
        p2 = make_product(api, sku="SCREW-9", product_family="PARTS", base_price_cents=1)
        make_lot(api, branch_id=branch["id"], product_id=p2["id"], qty_on_hand=100)

        o1 = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(p1["id"], 1)],
        )
        invoice_order(o1["id"], api)
        acct = validate_success(api.get_account(account["id"], MGR))
        assert acct["ytd_volume_cents"] == 4_999_999
        assert acct["tier"] == "ELITE", (
            f"4,999,999 is one cent below PREMIER but at/above ELITE: {acct}"
        )

        o2 = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(p2["id"], 1)],
        )
        invoice_order(o2["id"], api)
        acct = validate_success(api.get_account(account["id"], MGR))
        assert acct["ytd_volume_cents"] == 5_000_000
        assert acct["tier"] == "PREMIER", (
            f"at least 5,000,000 cents earns PREMIER (inclusive): {acct}"
        )


class TestTierRatchet:
    def test_tier_ratchet_never_decreases_on_cancel(self, api):
        """PRD §2.11: "Tier is a ratchet: invoicing may push it upward, but cancellations and returns never pull it back down, and it is never recomputed on draft edits."
        PRD §3.6: "The account's `ytd_volume_cents` is decremented by the order's `invoiced_cents` — but per §2.11 the tier ratchet holds and the account's tier is not recomputed downward."

        Design: Corner/cross_cutting_complexity_layers/tier_ratchet_never_decreases_on_cancel
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-26"},
            product_over={
                "sku": "HEATER-B",
                "product_family": "EQUIPMENT",
                "base_price_cents": 2_000_000,
            },
            lot_over={"qty_on_hand": 1},
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 1)],
        )
        invoice_order(order["id"], api)
        acct = validate_success(api.get_account(account["id"], MGR))
        assert acct["tier"] == "ELITE", f"crossed ELITE exactly at 2,000,000: {acct}"
        assert acct["ytd_volume_cents"] == 2_000_000

        resp = api.cancel_order(order["id"], MGR)
        validate_success(resp, 200)
        acct = validate_success(api.get_account(account["id"], MGR))
        assert acct["ytd_volume_cents"] == 0, (
            f"cancel decrements ytd by invoiced_cents: {acct}"
        )
        assert acct["tier"] == "ELITE", (
            f"ratchet holds — tier never recomputes downward on cancel: {acct}"
        )
