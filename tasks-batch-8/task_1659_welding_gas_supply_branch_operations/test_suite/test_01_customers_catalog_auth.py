"""Customer accounts, catalog registration, authentication, and pagination."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_customer,
    assert_version_incremented,
    make_customer,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerDefaults:
    def test_create_customer_applies_defaults(self, api, counter_rep_headers):
        """PRD §3.1: "Terms are either `CASH` or `NET30` and default to `CASH`
        when omitted; the credit limit defaults to 0 and only has meaning for
        `NET30` accounts; the price book link defaults to null, which means
        the account buys at retail pricing." and "New accounts start in
        `ACTIVE` status with all computed balances at zero."

        Design: Corner/entities/customer_creation_applies_defaults
        """
        resp = api.create_customer(
            {"account_no": "ACC-EN1", "name": "Defaults Co"},
            counter_rep_headers)
        data = validate_success(resp, 201)
        assert_customer(data)
        assert data["terms"] == "CASH"
        assert data["credit_limit_cents"] == 0
        assert data["status"] == "ACTIVE"
        assert data["posted_exposure_cents"] == 0
        assert data["outstanding_balance_cents"] == 0
        assert data["projected_exposure_cents"] == 0
        assert data["accrued_rental_cents"] == 0
        assert data["credit_balance_cents"] == 0

    def test_customer_get_roundtrip_and_not_found(self, api,
                                                  counter_rep_headers):
        """PRD §3.1: "Reading an account returns those computed figures —
        `outstanding_balance_cents`, `posted_exposure_cents`,
        `accrued_rental_cents`, `projected_exposure_cents`, and
        `credit_balance_cents` as defined in §2.9 — evaluated against the
        current logical clock." PRD §2.8: "Every identifier in the path
        exists, and every body-referenced identifier — `customer_id`,
        `product_id`, `route_id`, `price_book_id`, cylinder or machine asset
        identifiers, `class_id` — exists. Violations are `ERR_NOT_FOUND`."

        Design: Corner/entities/customer_get_roundtrip_and_not_found
        """
        created = validate_success(
            api.create_customer({"account_no": "ACC-EN2", "name": "Roundtrip Co"},
                                counter_rep_headers), 201)
        got = validate_success(api.get_customer(created["id"],
                                                counter_rep_headers))
        assert got["name"] == "Roundtrip Co"
        assert got["account_no"] == "ACC-EN2"
        missing = api.get_customer(NON_EXISTENT_UUID, counter_rep_headers)
        validate_error(missing, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_duplicate_account_no_rejected(self, api, counter_rep_headers):
        """PRD §3.1: "A `CounterRep` or `BranchManager` opens a customer
        account by supplying a unique branch `account_no` (a duplicate is
        rejected with `ERR_DUPLICATE_ACCOUNT`), a display `name`, and
        optionally the account `terms`, its `credit_limit_cents`, and a
        `price_book_id`."

        Design: Corner/entities/duplicate_account_no_rejected
        """
        validate_success(api.create_customer(
            {"account_no": "ACC-EN3", "name": "First"}, counter_rep_headers), 201)
        resp = api.create_customer({"account_no": "ACC-EN3", "name": "Second"},
                                   counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCOUNT)


class TestCatalogRegistration:
    def test_duplicate_product_sku_rejected(self, api, branch_manager_headers):
        """PRD §3.2: "A `BranchManager` registers each sellable product with a
        unique `sku` (duplicates fail with `ERR_DUPLICATE_SKU`), a display
        `name`, a `category` of `HARDGOOD`, `GAS`, or `SPECIALTY_GAS`, and a
        `retail_price_cents` list price of zero or more."

        Design: Corner/entities/duplicate_product_sku_rejected
        """
        validate_success(api.create_product(
            {"sku": "HG-DUP", "name": "One", "category": "HARDGOOD",
             "retail_price_cents": 100}, branch_manager_headers), 201)
        resp = api.create_product(
            {"sku": "HG-DUP", "name": "Two", "category": "HARDGOOD",
             "retail_price_cents": 200}, branch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU)

    def test_duplicate_cylinder_serial_rejected(self, api,
                                                branch_manager_headers):
        """PRD §3.2: "Registering one — again a `BranchManager` operation —
        records its stamped `serial_no` (unique across both cylinders and
        machines, enforced as `ERR_DUPLICATE_SERIAL`), its `gas_grade`, and
        its `size` of `SMALL`, `MEDIUM`, or `LARGE`; a newly registered
        cylinder arrives `FULL`."

        Design: Corner/entities/duplicate_cylinder_serial_rejected
        """
        validate_success(api.create_cylinder_asset(
            {"serial_no": "CYL-DUP", "gas_grade": "ARGON", "size": "SMALL"},
            branch_manager_headers), 201)
        resp = api.create_cylinder_asset(
            {"serial_no": "CYL-DUP", "gas_grade": "OXYGEN", "size": "LARGE"},
            branch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL)

    def test_needs_reorder_at_and_above_threshold(self, api,
                                                  branch_manager_headers):
        """PRD §3.2: "A product whose `stock_on_hand` has fallen to at or
        below its `reorder_point` reports `needs_reorder` as true." Also
        "`stock_on_hand`, which starts at 0, increases by the received `qty`
        (a positive integer) when a `BranchManager` receives stock into branch
        inventory".

        Design: Corner/entities/product_needs_reorder_threshold
        """
        product = validate_success(api.create_product(
            {"sku": "HG-EN5", "name": "Lens", "category": "HARDGOOD",
             "retail_price_cents": 500, "reorder_point": 5},
            branch_manager_headers), 201)
        at_point = validate_success(api.receive_stock(
            product["id"], {"qty": 5}, branch_manager_headers))
        assert at_point["needs_reorder"] is True, "stock 5 <= reorder_point 5"
        above = validate_success(api.receive_stock(
            product["id"], {"qty": 1}, branch_manager_headers))
        assert above["stock_on_hand"] == 6
        assert above["needs_reorder"] is False, "stock 6 > reorder_point 5"


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing, or
        whose value does not name one of these five roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/request_missing_auth_header_unauthenticated
        """
        resp = api.list_customers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_price_book_create_forbidden_for_counter_rep(
            self, api, counter_rep_headers):
        """PRD §2.1: "A request whose role is recognized but is not listed for
        the endpoint — or that fails a per-action role condition, such as the
        fulfillment-type split on order fulfillment or the per-target role
        split on repair-ticket and enrollment advancement described in §3 — is
        rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /price-books under BranchManager only.

        Design: Corner/validations/price_book_create_forbidden_for_counter_rep
        """
        customer = make_customer(account_no="ACC-VA1", name="Auth Co",
                                 terms="CASH")
        resp = api.create_price_book(
            {"name": "Sneaky", "scope": "CONTRACT", "customer_id": customer["id"],
             "effective_from": "2026-01-01T00:00:00Z",
             "effective_to": "2027-01-01T00:00:00Z",
             "default_discount_pct": 0.10}, counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_price_book_inverted_window_rejected(self, api,
                                                 branch_manager_headers):
        """PRD §3.1: "an effective window from `effective_from` (inclusive) to
        `effective_to` (exclusive, and strictly later than `effective_from` —
        otherwise `ERR_VALIDATION`)".

        Design: Corner/validations/price_book_inverted_window_rejected
        """
        resp = api.create_price_book(
            {"name": "Backwards", "scope": "RETAIL",
             "effective_from": "2026-06-01T00:00:00Z",
             "effective_to": "2026-01-01T00:00:00Z",
             "default_discount_pct": 0.05}, branch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestImmediateConsistency:
    def test_patch_customer_immediately_visible(self, api,
                                                counter_rep_headers):
        """PRD §1: "Consistency is immediate: every mutation and all of its
        cascading side effects commit atomically within the request that
        triggered them." PRD §3.1: "the mutable account fields — `name`,
        `terms`, `credit_limit_cents`, and `price_book_id` — can be updated by
        a `CounterRep` or `BranchManager` through the account-update
        operation, each update incrementing the customer's `version`."

        Design: Corner/consistency_model/mutation_immediately_visible_on_read
        """
        created = validate_success(api.create_customer(
            {"account_no": "ACC-CM1", "name": "Before Co"},
            counter_rep_headers), 201)
        patched = validate_success(api.update_customer(
            created["id"], {"name": "After Co"}, counter_rep_headers))
        assert patched["name"] == "After Co"
        assert_version_incremented(patched["version"], created["version"])
        got = validate_success(api.get_customer(created["id"],
                                                counter_rep_headers))
        assert got["name"] == "After Co", "GET must reflect the mutation at once"


class TestPagination:
    def test_customer_list_pagination_limit_offset(self, api,
                                                   counter_rep_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; when omitted it defaults to 10, and it may not be
        less than 1 or greater than 100. The `offset` parameter specifies how
        many items to skip and defaults to 0." and "Paginated list responses
        carry four pagination fields in the `meta` object of the response
        envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/customer_list_pagination_limit_offset
        """
        for i in range(1, 4):
            validate_success(api.create_customer(
                {"account_no": f"ACC-EP{i}", "name": f"P{i}"},
                counter_rep_headers), 201)
        page1, meta1 = validate_paginated(api.list_customers(
            counter_rep_headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_customers(
            counter_rep_headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
