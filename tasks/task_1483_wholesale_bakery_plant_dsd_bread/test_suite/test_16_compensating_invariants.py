"""Compensating invariants: store credit balance conservation and thrift
pool conservation across void (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_stale_return,
    create_thrift_sale,
    make_qa_headers,
    setup_two_product_delivered_scenario,
    setup_verified_stale_return_scenario,
    validate_error,
    validate_success,
)


class TestStoreCreditBalanceConservation:
    def test_credit_applies_full_amount_to_balance(self, api):
        """PRD §3.8: "Crediting sets `credited_amount_cents` to
        `final_credit_cents`, adds that amount onto the store's
        `credit_balance_cents`, increments the store's `version`, and moves
        the return from `VERIFIED` to `CREDITED`."

        Design: Difficulty/compensating_invariant/store_credit_balance_conservation
        """
        ctx = setup_verified_stale_return_scenario(
            plant_name="Plant Upsilon", stale_lines_qty=3,
        )
        sre = ctx["stale_return"]
        store = ctx["store"]

        credited = validate_success(
            api.credit_stale_return(sre["id"], TEST_USERS["planner_headers"])
        )
        assert credited["status"] == "CREDITED"
        # Batch at 30h -> rate 0.50; qty 3 * 199 * 0.5 -> round_half_up = 299.
        assert credited["credited_amount_cents"] == 299, (
            f"credited_amount_cents must equal final_credit_cents=299, got {credited['credited_amount_cents']}"
        )

        store_after = validate_success(
            api.get_store(store["id"], TEST_USERS["planner_headers"])
        )
        assert store_after["credit_balance_cents"] == 299, (
            f"credit must apply 299 to store balance, got {store_after['credit_balance_cents']}"
        )

    def test_reverse_credit_restores_zero_balance(self, api):
        """PRD §3.8: "Should a credit need unwinding, a `PlantAdmin` reverses
        it: the store's `credit_balance_cents` is reduced by
        `credited_amount_cents`, the store's `version` increments again, and
        the return moves from `CREDITED` to the terminal `REVERSED` state."

        Design: Difficulty/compensating_invariant/store_credit_balance_conservation
        """
        ctx = setup_verified_stale_return_scenario(
            plant_name="Plant Upsilon 2", stale_lines_qty=3,
        )
        sre = ctx["stale_return"]
        store = ctx["store"]

        validate_success(
            api.credit_stale_return(sre["id"], TEST_USERS["planner_headers"])
        )
        reversed_ret = validate_success(
            api.reverse_credit_stale_return(sre["id"], TEST_USERS["admin_headers"])
        )
        assert reversed_ret["status"] == "REVERSED"

        store_after = validate_success(
            api.get_store(store["id"], TEST_USERS["planner_headers"])
        )
        assert store_after["credit_balance_cents"] == 0, (
            f"compensating reverse-credit must restore the balance to 0, "
            f"got {store_after['credit_balance_cents']}"
        )


class TestThriftPoolConservationOnVoid:
    def test_sale_then_second_sale_exceeds_pool(self, api):
        """PRD §3.8: "the requested units must not exceed the pool's
        available stock (else `ERR_THRIFT_STOCK_UNAVAILABLE`)."

        Design: Difficulty/compensating_invariant/thrift_pool_conservation_on_void
        """
        # Pool of 3 units of product A from a verified 3-unit stale line.
        ctx = _verified_thrift_pool_ctx("Plant Phi", qty_a=3, qty_d=2)
        product_a = ctx["product_a"]

        s1 = create_thrift_sale(product_a["id"], units=2, unit_price_cents=100)
        assert s1["status"] == "RECORDED"
        assert s1["total_cents"] == 200

        # Pool A: 3 - 2 = 1 available; a further sale of 2 must be rejected.
        resp = api.create_thrift_sale(
            {"product_id": product_a["id"], "units": 2, "unit_price_cents": 100},
            TEST_USERS["thrift_headers"],
        )
        validate_error(resp, "ERR_THRIFT_STOCK_UNAVAILABLE", expected_status=409)

    def test_void_restores_pool(self, api):
        """PRD §3.8: "A `PlantAdmin` may void a recorded sale, moving it from
        `RECORDED` to the terminal `VOIDED` state and crediting its units
        back into the pool — a sale followed by its own void leaves the pool
        exactly unchanged."

        Design: Difficulty/compensating_invariant/thrift_pool_conservation_on_void
        """
        ctx = _verified_thrift_pool_ctx("Plant Phi 2", qty_a=3, qty_d=2)
        product_a = ctx["product_a"]

        s1 = create_thrift_sale(product_a["id"], units=2, unit_price_cents=100)
        # Void restores the pool to 3.
        voided = validate_success(
            api.void_thrift_sale(s1["id"], TEST_USERS["admin_headers"])
        )
        assert voided["status"] == "VOIDED"

        # After void, a sale of 3 succeeds.
        s3 = create_thrift_sale(product_a["id"], units=3, unit_price_cents=100)
        assert s3["status"] == "RECORDED"
        assert s3["total_cents"] == 300


def _verified_thrift_pool_ctx(plant_name: str, qty_a: int, qty_d: int):
    """Build the two-product scenario with a verified stale return covering
    both products (both lines earn a positive rate) so the thrift pool is
    stocked with `qty_a` of product A and `qty_d` of product D."""
    ctx = setup_two_product_delivered_scenario(plant_name=plant_name)
    store = ctx["store"]
    driver = ctx["driver"]
    stop = ctx["stop"]
    batch_a = ctx["batch"]
    batch_d = ctx["batch_d"]

    sre = create_stale_return(
        store["id"],
        stop["id"],
        [{"batch_id": batch_a["id"], "qty": qty_a},
         {"batch_id": batch_d["id"], "qty": qty_d}],
        driver["id"],
    )
    verified = validate_success(
        api_client.verify_stale_return(
            sre["id"],
            {"verified_lines": [{"batch_id": batch_a["id"], "qty": qty_a},
                                {"batch_id": batch_d["id"], "qty": qty_d}]},
            make_qa_headers("qa-1"),
        )
    )
    ctx["stale_return"] = verified
    return ctx


class TestThriftPriceFloorExactBoundary:
    def test_thrift_price_floor_exact_boundary(self, api):
        """PRD §3.8: "the price must be at least half the product's
        `base_price_cents` rounded up to a whole cent (else
        `ERR_THRIFT_PRICE_BELOW_FLOOR`)."

        Design: Corner/calculations/thrift_price_floor_exact_boundary
        """
        ctx = setup_verified_stale_return_scenario(
            plant_name="Plant P Floor", stale_lines_qty=3,
        )
        product_a = ctx["product_a"]
        # floor = ceil(199 * 0.50) = 100. price 99 must be rejected.
        resp = api.create_thrift_sale(
            {"product_id": product_a["id"], "units": 1, "unit_price_cents": 99},
            TEST_USERS["thrift_headers"],
        )
        validate_error(resp, "ERR_THRIFT_PRICE_BELOW_FLOOR", expected_status=409)

        # price 100 (== floor) is accepted.
        sale = create_thrift_sale(product_a["id"], units=1, unit_price_cents=100)
        assert sale["status"] == "RECORDED"
        assert sale["total_cents"] == 100
