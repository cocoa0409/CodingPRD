"""Catalog, branch, account, and inventory record basics (PRD §2.3, §2.7, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_account,
    create_account_payload,
    create_branch_payload,
    create_order_payload,
    create_product_payload,
    create_stock_record_payload,
    get_stock_row,
    make_account,
    make_branch,
    make_product,
    make_stock,
    setup_branch_product_account,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCatalogCreation:
    def test_account_create_missing_tier_returns_400(self, api, sales_headers):
        """PRD §3.3: "An `InsideSales` representative opens a contractor account
        with the `company_name`, a `pricing_tier` of exactly one of `STANDARD`,
        `SILVER`, `GOLD`, or `PLATINUM`, payment `terms` of exactly one of `COD`,
        `NET_15`, or `NET_30`, and a `credit_limit_cents` of at least 0."
        PRD §2.7: "Request body shape — required fields are present, enum members are valid, quantities are at least 1, `cut_length_ft` is present exactly when the line's product is cut-to-order and absent otherwise, a program's `period_end` is after its `period_start`, and a window's `window_end` is after its `window_start`; otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/account_create_missing_tier_returns_400
        """
        payload = create_account_payload()
        del payload["pricing_tier"]
        res = api.create_account(payload, sales_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_product_invalid_category_rejected(self, api, manager_headers):
        """PRD §3.1: "a `category` of exactly one of `PIPE`, `VALVE`, `FITTING`,
        or `FIXTURE`".
        PRD §2.7: "Request body shape — required fields are present, enum members are valid, quantities are at least 1, `cut_length_ft` is present exactly when the line's product is cut-to-order and absent otherwise, a program's `period_end` is after its `period_start`, and a window's `window_end` is after its `window_start`; otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/product_invalid_category_rejected
        """
        res = api.create_product(
            create_product_payload(sku="H1", category="HOSE", list_price_cents=100,
                                   cost_cents=50, cubes_per_unit=1),
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_account_computed_fields_input_ignored(self, api, sales_headers):
        """PRD §3.3: "The account's standing fields — `outstanding_balance_cents`,
        `forward_exposure_cents`, and `available_credit_cents` — are computed
        continuously per the dual-exposure model of §2.9, and the account `status`
        cycles among `ACTIVE`, `CREDIT_HOLD`, and `SUSPENDED` without any terminal
        state." A client-supplied value must not override the computation: a brand
        new account has no orders, payments, or credits, so the computed balance
        is 0.

        Design: Corner/entities/account_computed_fields_input_ignored
        """
        payload = create_account_payload(
            company_name="Sneaky Co", credit_limit_cents=100000,
        )
        payload["outstanding_balance_cents"] = 999999
        res = api.create_account(payload, sales_headers)
        account = validate_success(res, 201)
        assert_account(account)
        assert account["outstanding_balance_cents"] == 0, (
            f"computed balance must be 0 for a new account, got {account['outstanding_balance_cents']}"
        )

    def test_branch_duplicate_code_rejected(self, api, manager_headers):
        """PRD §3.1: "A `BranchManager` creates a branch with a display `name` and
        a short `code`; the code must be unique across all branches, and a
        duplicate is rejected with `ERR_BRANCH_CODE_EXISTS`."

        Design: Corner/entities/branch_duplicate_code_rejected
        """
        make_branch(code="M1")
        res = api.create_branch(create_branch_payload(name="Main Clone", code="M1"), manager_headers)
        validate_error(res, ApiErrorId.ERR_BRANCH_CODE_EXISTS)

    def test_product_duplicate_sku_rejected(self, api, manager_headers):
        """PRD §3.1: "Products are created one at a time with a unique `sku`
        (a duplicate is rejected with `ERR_SKU_EXISTS`)".

        Design: Corner/endpoints/product_duplicate_sku_rejected
        """
        make_product(sku="P1")
        res = api.create_product(
            create_product_payload(sku="P1", description="Duplicate", category="VALVE",
                                   list_price_cents=100, cost_cents=50, cubes_per_unit=1),
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_SKU_EXISTS)


class TestExistenceAndReferences:
    def test_order_get_nonexistent_returns_404(self, api, sales_headers):
        """PRD §2.7: "Path-template identifiers — path ids are resolved left to right, and the first id that does not resolve produces that resource's not-found error: `ERR_BRANCH_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, or `ERR_SHEET_NOT_FOUND`."

        Design: Corner/entities/order_get_nonexistent_returns_404
        """
        res = api.get_order(NON_EXISTENT_UUID, sales_headers)
        err = validate_error(res, ApiErrorId.ERR_ORDER_NOT_FOUND)
        assert err.get("message"), "error envelope must carry a human-readable message"

    def test_order_create_unknown_account_returns_404(self, api, counterrep_headers, manager_headers):
        """PRD §2.7: "Body-referenced identifiers — foreign keys carried in the payload (the `product_id` on a line add, the `slot_id` on a booking, the `order_id` on a return, the `account_id` and `branch_id` on creates, the `substitute_product_id` on a substitute proposal) resolve to existing resources; otherwise the corresponding not-found error, such as `ERR_PRODUCT_NOT_FOUND`, is returned."

        Design: Corner/entities/order_create_unknown_account_returns_404
        """
        branch = make_branch()
        res = api.create_order(
            create_order_payload(NON_EXISTENT_UUID, branch["id"]), counterrep_headers
        )
        validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)

    def test_receipt_unknown_product_rejected(self, api, warehouse_headers, manager_headers):
        """PRD §2.7: "Body-referenced identifiers — foreign keys carried in the payload (the `product_id` on a line add, the `slot_id` on a booking, the `order_id` on a return, the `account_id` and `branch_id` on creates, the `substitute_product_id` on a substitute proposal) resolve to existing resources; otherwise the corresponding not-found error, such as `ERR_PRODUCT_NOT_FOUND`, is returned."
        PRD §3.1: "A `WarehouseLead` posts a stock receipt against a branch as a
        batch of `lines`, each naming a `product_id`, a `qty` of at least 1, and
        a `unit_cost_cents` of at least 0".

        Design: Corner/validations/receipt_unknown_product_rejected
        """
        branch = make_branch()
        res = api.create_stock_receipt(
            branch["id"],
            {"lines": [{"product_id": NON_EXISTENT_UUID, "qty": 5, "unit_cost_cents": 100}]},
            warehouse_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRODUCT_NOT_FOUND)


class TestInventoryRecords:
    def test_stock_record_duplicate_rejected(self, api, warehouse_headers):
        """PRD §3.1: "Before stock can be tracked for a product at a branch, a
        `WarehouseLead` creates the inventory record for the pair by supplying the
        `product_id` and an `initial_on_hand`; the record starts with `on_hand`
        equal to `initial_on_hand` and `reserved` at 0. A second record for the
        same branch-and-product pair is rejected with `ERR_STOCK_RECORD_EXISTS`."

        Design: Corner/entities/stock_record_duplicate_rejected
        """
        branch, product, _ = setup_branch_product_account()
        first = validate_success(
            api.create_stock_record(
                branch["id"], create_stock_record_payload(product["id"], initial_on_hand=5),
                warehouse_headers,
            ),
            201,
        )
        assert first["on_hand"] == 5 and first["reserved"] == 0

        res = api.create_stock_record(
            branch["id"], create_stock_record_payload(product["id"], initial_on_hand=3),
            warehouse_headers,
        )
        validate_error(res, ApiErrorId.ERR_STOCK_RECORD_EXISTS)

        row = get_stock_row(branch["id"], product["id"])
        assert row["on_hand"] == 5, f"on_hand must stay 5 after the rejected duplicate, got {row['on_hand']}"


class TestPagination:
    def test_branch_list_pagination_envelope(self, api, manager_headers, counterrep_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10 when omitted, and accepts values from a
        minimum of 1 to a maximum of 100. The `offset` parameter specifies how
        many items to skip and defaults to 0. Unless otherwise specified, every
        list endpoint returns resources sorted by `created_at` in ascending order.
        The `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/branch_list_pagination_envelope
        """
        for i in (1, 2, 3):
            make_branch(code=f"B{i}", name=f"B{i}")

        res1 = api.list_branches(counterrep_headers, params={"limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(res1)
        assert res1.json()["response_type"] == "array"
        assert len(data1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True

        res2 = api.list_branches(counterrep_headers, params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(res2)
        assert len(data2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False


class TestCutLengthValidation:
    def test_cut_length_validation_rejected_both_ways(self, api, counterrep_headers):
        """PRD §3.6: "Lines are added to a `DRAFT` order one at a time, by a `CounterRep` or a `BranchManager`, with a `product_id`, a `qty`, and — exactly when the product is cut-to-order — a `cut_length_ft` of at least 1 (present on a non-cut product, or missing on a cut product, is `ERR_INVALID_REQUEST`)."

        Design: Corner/entities/cut_length_validation_rejected_both_ways
        """
        branch = make_branch()
        cut = make_product(sku="PC", is_cut_to_order=True, list_price_cents=200, cost_cents=100,
                           cubes_per_unit=1)
        plain = make_product(sku="P1")
        account = make_account()
        make_stock(branch["id"], cut["id"], 20)
        make_stock(branch["id"], plain["id"], 20)
        order = validate_success(
            api.create_order(create_order_payload(account["id"], branch["id"]), counterrep_headers), 201
        )

        res1 = api.add_order_line(order["id"], {"product_id": cut["id"], "qty": 2}, counterrep_headers)
        validate_error(res1, ApiErrorId.ERR_INVALID_REQUEST)

        res2 = api.add_order_line(
            order["id"], {"product_id": plain["id"], "qty": 1, "cut_length_ft": 3}, counterrep_headers
        )
        validate_error(res2, ApiErrorId.ERR_INVALID_REQUEST)
