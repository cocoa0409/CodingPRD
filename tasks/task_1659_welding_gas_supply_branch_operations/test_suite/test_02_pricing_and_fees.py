"""Order pricing: draft computed fields, contract price resolution, rounding,
fees, price-book windows."""
from test_helpers import (
    ApiErrorId,
    confirm_order,
    get_order,
    make_active_contract_book,
    make_customer,
    make_order,
    make_product,
    make_route,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDraftOrderShape:
    def test_draft_order_computed_fields(self, api, counter_rep_headers):
        """PRD §3.3: "A new order starts with `fulfillment_status` `DRAFT` and
        `payment_status` `UNPAID`, and its `subtotal_cents` remains 0 while it
        is a draft. Two derived figures appear immediately: `units`, the sum
        of quantities across all lines, and `available_date`, which for orders
        containing specialty-gas lines is the order's creation date plus the
        largest `lead_time_days` among those specialty lines, and which is
        null for orders without specialty lines."

        Design: Corner/entities/order_draft_computed_fields_zero
        """
        customer = make_customer(account_no="ACC-EN4", name="Draft Co",
                                 terms="CASH")
        product = make_product(sku="HG-EN4", name="Soapstone",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=5)
        resp = api.create_order(
            {"customer_id": customer["id"], "order_type": "RETAIL",
             "fulfillment": "WILL_CALL",
             "lines": [{"product_id": product["id"], "qty": 2}]},
            counter_rep_headers)
        data = validate_success(resp, 201)
        assert data["subtotal_cents"] == 0, "pricing happens at confirm"
        assert data["units"] == 2
        assert data["available_date"] is None, "no specialty lines"
        assert data["invoice_id"] is None

    def test_order_initial_state_draft_unpaid(self, api, counter_rep_headers):
        """PRD §3.3: "A new order starts with `fulfillment_status` `DRAFT` and
        `payment_status` `UNPAID`, and its `subtotal_cents` remains 0 while it
        is a draft."

        Design: Corner/state_machines/order_initial_state_is_draft_unpaid
        """
        customer = make_customer(account_no="ACC-SM1", name="Init Co",
                                 terms="CASH")
        product = make_product(sku="HG-SM1", name="Chipping Hammer",
                               category="HARDGOOD", retail_price_cents=2500,
                               stock=1)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}])
        assert order["fulfillment_status"] == "DRAFT"
        assert order["payment_status"] == "UNPAID"

    def test_invalid_order_type_rejected(self, api, counter_rep_headers):
        """PRD §3.3: "An order begins when a `CounterRep` or `BranchManager`
        creates it with a `customer_id`, an `order_type` of `RETAIL`,
        `EXCHANGE`, or `SPECIAL_MIX`, a `fulfillment` mode of `WILL_CALL` or
        `ROUTE`, and a `lines` array in which each line references a
        `product_id` and a positive integer `qty`." PRD §2.8: "Required fields
        are present, types and enum members are valid ... Shape failures are
        `ERR_VALIDATION`".

        Design: Corner/validations/invalid_enum_order_type_rejected
        """
        customer = make_customer(account_no="ACC-VA2", name="Enum Co",
                                 terms="CASH")
        product = make_product(sku="HG-VA2", name="Thing", category="HARDGOOD",
                               retail_price_cents=100, stock=1)
        resp = api.create_order(
            {"customer_id": customer["id"], "order_type": "WHOLESALE",
             "fulfillment": "WILL_CALL",
             "lines": [{"product_id": product["id"], "qty": 1}]},
            counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestContractTieredPricing:
    def _setup_contract_customer(self, account_suffix, retail_price_cents,
                                 volume_tiers, stock):
        customer = make_customer(account_no=f"ACC-CT{account_suffix}",
                                 name="Contract Co", terms="CASH")
        make_active_contract_book(
            customer["id"], name=f"CT{account_suffix} Book",
            default_discount_pct=0.10, volume_tiers=volume_tiers)
        product = make_product(sku=f"HG-CT{account_suffix}",
                               name="Electrode 10lb", category="HARDGOOD",
                               retail_price_cents=retail_price_cents,
                               stock=stock)
        return customer, product

    def test_contract_pricing_no_tier_and_first_tier(self, api):
        """PRD §3.3: "Otherwise the discounted base is the product's retail
        price reduced by the book's `default_discount_pct` fraction; the
        applicable volume tier is the `volume_tiers` entry with the greatest
        `min_qty` that does not exceed the line quantity (if no tier
        qualifies, no extra discount applies); and the line's
        `unit_price_cents` is that base further reduced by the tier's
        `extra_discount_pct` fraction, rounded half-up to a whole cent — the
        single rounding event of §2.6, with no intermediate rounding of the
        base. Each line's `line_total_cents` is the rounded unit price
        multiplied by its quantity."

        Design: Difficulty/combinatorial_formula/contract_tiered_unit_price_resolution
        """
        customer, product = self._setup_contract_customer(
            "1", 10000,
            [{"min_qty": 10, "extra_discount_pct": 0.05},
             {"min_qty": 50, "extra_discount_pct": 0.10}], 100)
        # qty 5: below every tier -> base 10000 * 0.90 = 9000 per unit
        order1 = make_order(customer["id"],
                            [{"product_id": product["id"], "qty": 5}])
        confirmed1 = confirm_order(order1["id"])
        assert confirmed1["lines"][0]["unit_price_cents"] == 9000
        assert confirmed1["total_cents"] == 45000
        # qty 12: tier min_qty 10 qualifies -> 9000 * 0.95 = 8550 per unit
        order2 = make_order(customer["id"],
                            [{"product_id": product["id"], "qty": 12}])
        confirmed2 = confirm_order(order2["id"])
        assert confirmed2["lines"][0]["unit_price_cents"] == 8550
        assert confirmed2["total_cents"] == 102600

    def test_contract_pricing_top_volume_tier(self, api):
        """PRD §3.3: "the applicable volume tier is the `volume_tiers` entry
        with the greatest `min_qty` that does not exceed the line quantity (if
        no tier qualifies, no extra discount applies); and the line's
        `unit_price_cents` is that base further reduced by the tier's
        `extra_discount_pct` fraction, rounded half-up to a whole cent". At
        qty 60 the min_qty 50 tier wins: 10000 x 0.90 x 0.90 = 8100 per unit.

        Design: Difficulty/combinatorial_formula/contract_tiered_unit_price_resolution
        """
        customer, product = self._setup_contract_customer(
            "1b", 10000,
            [{"min_qty": 10, "extra_discount_pct": 0.05},
             {"min_qty": 50, "extra_discount_pct": 0.10}], 100)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 60}])
        confirmed = confirm_order(order["id"])
        assert confirmed["lines"][0]["unit_price_cents"] == 8100
        assert confirmed["lines"][0]["line_total_cents"] == 486000
        assert confirmed["total_cents"] == 486000


class TestRoundingPinnedOrder:
    def _setup(self):
        customer = make_customer(account_no="ACC-CT2", name="Rounding Co",
                                 terms="CASH")
        make_active_contract_book(
            customer["id"], name="CT2 Book", default_discount_pct=0.10,
            volume_tiers=[{"min_qty": 1, "extra_discount_pct": 0.05}])
        product = make_product(sku="HG-CT2", name="Nozzle Tip",
                               category="HARDGOOD", retail_price_cents=1095,
                               stock=10)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 3}])
        return confirm_order(order["id"])

    def test_unit_price_rounds_half_up_once_at_end(self, api):
        """PRD §2.6: "Exactly one rounding event exists in the entire pricing
        pipeline. When a contract unit price is computed for an order line,
        the discounted figure is rounded half-up to a whole cent, and this
        rounding happens exactly once, at the very end of the unit-price
        calculation; the intermediate discounted base is never rounded."
        1095 x 0.90 x 0.95 = 936.225 -> 936 (a base-first double rounding
        would yield 937).

        Design: Difficulty/combinatorial_formula/line_rounding_order_pinned_single_round_at_end
        """
        confirmed = self._setup()
        assert confirmed["lines"][0]["unit_price_cents"] == 936

    def test_line_total_is_integer_multiply_of_rounded_unit(self, api):
        """PRD §2.6: "Line totals are then plain integer multiplications of
        the already-rounded unit price by the line quantity, with no further
        rounding, and an order's subtotal is the sum of those rounded line
        totals — summing raw unrounded per-line products is forbidden because
        it yields different cents." 3 x 936 = 2808 (sum-then-round of
        2808.675 would give 2809).

        Design: Difficulty/combinatorial_formula/line_rounding_order_pinned_single_round_at_end
        """
        confirmed = self._setup()
        assert confirmed["lines"][0]["line_total_cents"] == 2808
        assert confirmed["subtotal_cents"] == 2808
        assert confirmed["total_cents"] == 2808


class TestOrderFees:
    def test_delivery_fee_threshold_boundary(self, api, counter_rep_headers):
        """PRD §3.3: "`delivery_fee_cents` is a flat 2500 cents ($25.00) when
        the order ships by route and its subtotal is strictly below the
        free-delivery threshold of 20000 cents ($200.00) — a subtotal exactly
        equal to the threshold waives the fee — and 0 otherwise." and
        "`total_cents` is the subtotal plus the two fees."

        Design: Corner/calculations/delivery_fee_threshold_exact_vs_one_cent_under
        """
        customer = make_customer(account_no="ACC-CA1", name="Fee Co",
                                 terms="CASH")
        p20 = make_product(sku="HG-CA1A", name="Table", category="HARDGOOD",
                           retail_price_cents=10000, stock=5)
        p19 = make_product(sku="HG-CA1B", name="Odd Tool", category="HARDGOOD",
                           retail_price_cents=19999, stock=5)
        route = make_route(route_date="2026-08-05", truck_capacity_units=10)
        # subtotal exactly at the threshold -> fee waived
        o1 = make_order(customer["id"], [{"product_id": p20["id"], "qty": 2}],
                        fulfillment="ROUTE", route_id=route["id"])
        confirmed1 = confirm_order(o1["id"])
        assert confirmed1["subtotal_cents"] == 20000
        assert confirmed1["delivery_fee_cents"] == 0
        assert confirmed1["total_cents"] == 20000
        # one cent under -> fee applies
        o2 = make_order(customer["id"], [{"product_id": p19["id"], "qty": 1}],
                        fulfillment="ROUTE", route_id=route["id"])
        confirmed2 = confirm_order(o2["id"])
        assert confirmed2["delivery_fee_cents"] == 2500
        assert confirmed2["total_cents"] == 22499

    def test_hazmat_fee_flat_per_order(self, api):
        """PRD §3.3: "`hazmat_fee_cents` is a flat 1500 cents ($15.00) per
        order when any line's product is hazmat-flagged, regardless of how
        many hazmat lines exist, and 0 otherwise." and "`total_cents` is the
        subtotal plus the two fees."

        Design: Corner/calculations/hazmat_fee_flat_once_per_order
        """
        customer = make_customer(account_no="ACC-CA2", name="Haz Co",
                                 terms="CASH")
        pa = make_product(sku="HG-CA2A", name="Flux (haz)", category="HARDGOOD",
                          retail_price_cents=1000, hazmat=True, stock=5)
        pb = make_product(sku="HG-CA2B", name="Cleaner (haz)",
                          category="HARDGOOD", retail_price_cents=2000,
                          hazmat=True, stock=5)
        order = make_order(customer["id"],
                           [{"product_id": pa["id"], "qty": 1},
                            {"product_id": pb["id"], "qty": 1}])
        confirmed = confirm_order(order["id"])
        assert confirmed["hazmat_fee_cents"] == 1500, \
            "flat per order — two hazmat lines do not double it"
        assert confirmed["subtotal_cents"] == 3000
        assert confirmed["total_cents"] == 4500


class TestPriceBookWindows:
    def test_expired_price_book_falls_back_to_retail(self, api,
                                                     branch_manager_headers):
        """PRD §3.1: "Thereafter the book participates in pricing until the
        logical clock reaches its `effective_to`, at which point the system
        flips it to `EXPIRED` (a terminal state) and it stops participating in
        contract price resolution." PRD §3.3: "if the customer has no linked
        price book, or the linked book is not `ACTIVE`, or the clock date
        falls outside the book's window (which runs from `effective_from`
        inclusive to `effective_to` exclusive), the line's `unit_price_cents`
        snapshot is simply the product's `retail_price_cents`."

        Design: Corner/calculations/expired_price_book_falls_back_to_retail
        """
        set_clock("2026-07-15T00:00:00Z")
        customer = make_customer(account_no="ACC-CA7", name="Lapse Co",
                                 terms="CASH")
        make_active_contract_book(
            customer["id"], name="Short Book",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z", default_discount_pct=0.50)
        product = make_product(sku="HG-CA7", name="Sleeves",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=5)
        set_clock("2026-08-10T00:00:00Z")
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}])
        confirmed = confirm_order(order["id"])
        assert confirmed["lines"][0]["unit_price_cents"] == 10000, \
            "expired book -> full retail"
        assert confirmed["total_cents"] == 10000
        books, _meta = validate_paginated(api.list_price_books(
            branch_manager_headers, params={"customer_id": customer["id"]}))
        assert books[0]["status"] == "EXPIRED", \
            "clock sweep past effective_to expires the book"

    def test_price_book_overlap_rejected_but_adjacency_allowed(
            self, api, branch_manager_headers):
        """PRD §3.1: "Activation moves a book from `DRAFT` to `ACTIVE` and is
        guarded by a window-exclusion rule: no other `ACTIVE` book with the
        same `scope` and the same `customer_id` may have a window overlapping
        the candidate's window. Windows are half-open — `effective_to` is
        exclusive — so a book whose window begins exactly when another's ends
        is allowed; a genuine overlap is rejected with
        `ERR_PRICE_BOOK_OVERLAP`."

        Design: Corner/validations/price_book_overlap_rejected_but_adjacency_allowed
        """
        customer = make_customer(account_no="ACC-VA14", name="Books Co",
                                 terms="CASH")

        def _book(name, frm, to, pct):
            resp = api.create_price_book(
                {"name": name, "scope": "CONTRACT",
                 "customer_id": customer["id"], "effective_from": frm,
                 "effective_to": to, "default_discount_pct": pct},
                branch_manager_headers)
            return validate_success(resp, 201)

        book_a = _book("A", "2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z",
                       0.10)
        validate_success(api.activate_price_book(book_a["id"],
                                                 branch_manager_headers))
        book_b = _book("B", "2026-05-01T00:00:00Z", "2026-09-01T00:00:00Z",
                       0.20)
        book_c = _book("C", "2026-06-01T00:00:00Z", "2026-12-01T00:00:00Z",
                       0.15)
        overlap = api.activate_price_book(book_b["id"], branch_manager_headers)
        validate_error(overlap, ApiErrorId.ERR_PRICE_BOOK_OVERLAP)
        adjacent = api.activate_price_book(book_c["id"], branch_manager_headers)
        assert validate_success(adjacent)["status"] == "ACTIVE", \
            "C.effective_from == A.effective_to is half-open adjacency"
