"""Reverse-reachability reads and the 404 family (PRD §2.7, §3.1, §3.4, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_awarded_quote,
    create_order_payload,
    create_order_line_payload,
    make_branch,
    make_product,
    make_stock,
    setup_branch_product_account,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["counterrep_headers"]
SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


class TestNotFoundFamily:
    def test_path_not_found_family_returns_404(self, api):
        """PRD §2.7: "Path-template identifiers — path ids are resolved left to
        right, and the first id that does not resolve produces that resource's
        not-found error: `ERR_BRANCH_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_ORDER_LINE_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`,
        `ERR_RETURN_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, or
        `ERR_SHEET_NOT_FOUND`."

        Every resource family 404s on an unknown id with its own domain error
        id; on the propose-substitute endpoint the path's line id resolves
        before the body's product id.

        Design: Corner/endpoints/path_not_found_family_returns_404
        """
        cases = [
            (api.get_branch(NON_EXISTENT_UUID, MANAGER), ApiErrorId.ERR_BRANCH_NOT_FOUND),
            (api.get_quote(NON_EXISTENT_UUID, SALES), ApiErrorId.ERR_QUOTE_NOT_FOUND),
            (api.get_kit(NON_EXISTENT_UUID, WAREHOUSE), ApiErrorId.ERR_KIT_NOT_FOUND),
            (api.get_slot(NON_EXISTENT_UUID, REP), ApiErrorId.ERR_SLOT_NOT_FOUND),
            (api.get_return(NON_EXISTENT_UUID, REP), ApiErrorId.ERR_RETURN_NOT_FOUND),
            (api.get_program(NON_EXISTENT_UUID, MANAGER), ApiErrorId.ERR_PROGRAM_NOT_FOUND),
            (api.get_sheet(NON_EXISTENT_UUID, SALES), ApiErrorId.ERR_SHEET_NOT_FOUND),
        ]
        for res, expected in cases:
            validate_error(res, expected)

        res = api.propose_substitute(
            NON_EXISTENT_UUID, {"substitute_product_id": NON_EXISTENT_UUID}, SALES
        )
        validate_error(res, ApiErrorId.ERR_ORDER_LINE_NOT_FOUND)


class TestReverseReachability:
    def test_fk_reverse_reachability_gets(self, api, sales_headers, counterrep_headers):
        """PRD §3.1: "the catalog exposes reverse-reachability reads: the stock
        rows of a single product across branches, and the order lines that
        reference a product either as the ordered `product_id` or as a pending
        `proposed_substitute_product_id`."
        PRD §3.4: "The orders produced from a quote remain discoverable through
        the quote's reverse-reachability read."
        PRD §4 lists "List lines of an order" at GET /pvf/orders/{id}/lines.

        The counter order's lines, the product's stock rows, and the converted
        PROJECT order are each discoverable through their reverse reads.

        Design: Corner/endpoints/fk_reverse_reachability_gets
        """
        branch, product, account = setup_branch_product_account(
            stock=5, account_overrides={"credit_limit_cents": 100000000}
        )
        order = validate_success(
            api.create_order(create_order_payload(account["id"], branch["id"]), counterrep_headers),
            201,
        )
        line = validate_success(
            api.add_order_line(order["id"], create_order_line_payload(product["id"], 1),
                               counterrep_headers),
            201,
        )
        quote = create_awarded_quote(
            account["id"], branch["id"],
            [{"product_id": product["id"], "qty": 2, "unit_price_cents": 9000}],
            valid_until="2026-12-31T00:00:00Z",
        )
        project_order = validate_success(api.convert_quote(quote["id"], sales_headers), 201)
        assert project_order["source"] == "PROJECT"

        lines = validate_success(api.get_order_lines(order["id"], sales_headers))
        line_rows = lines if isinstance(lines, list) else lines.get("data", [])
        assert [r["id"] for r in line_rows] == [line["id"]]

        stock_rows = validate_success(api.get_product_inventory(product["id"], sales_headers))
        stock_rows = stock_rows if isinstance(stock_rows, list) else stock_rows.get("data", [])
        assert len(stock_rows) == 1
        assert stock_rows[0]["branch_id"] == branch["id"]
        assert stock_rows[0]["on_hand"] == 5

        quote_orders = validate_success(api.get_quote_orders(quote["id"], sales_headers))
        order_rows = quote_orders if isinstance(quote_orders, list) else quote_orders.get("data", [])
        assert len(order_rows) == 1
        assert order_rows[0]["id"] == project_order["id"]
        assert order_rows[0]["source"] == "PROJECT"
