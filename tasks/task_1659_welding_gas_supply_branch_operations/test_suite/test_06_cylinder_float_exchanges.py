"""Cylinder float conservation, exchange fulfillment, and gas-line guards."""
from test_helpers import (
    ApiErrorId,
    confirm_order,
    float_grade,
    fulfill_order,
    get_cylinder,
    get_float_summary,
    make_customer,
    make_cylinder,
    make_order,
    make_product,
    pay_order,
    stage_order,
    validate_error,
    validate_success,
)


def _exchange_scenario():
    """Four FULL ARGON cylinders; customer holds a1, a2 after a RETAIL gas
    sale; a second EXCHANGE order for 2 is confirmed, paid, and staged."""
    customer = make_customer(account_no="ACC-CI1", name="Swap Co",
                             terms="CASH")
    a1 = make_cylinder(serial_no="CYL-CI1", gas_grade="ARGON", size="MEDIUM")
    a2 = make_cylinder(serial_no="CYL-CI2", gas_grade="ARGON", size="MEDIUM")
    a3 = make_cylinder(serial_no="CYL-CI3", gas_grade="ARGON", size="MEDIUM")
    a4 = make_cylinder(serial_no="CYL-CI4", gas_grade="ARGON", size="MEDIUM")
    gas = make_product(sku="G-ARG-CI", name="Argon Refill", category="GAS",
                       gas_grade="ARGON", retail_price_cents=3000)
    sale = make_order(customer["id"], [{"product_id": gas["id"], "qty": 2}])
    confirm_order(sale["id"])
    pay_order(sale["id"], 6000)
    stage_order(sale["id"])
    fulfill_order(sale["id"], issued_asset_ids=[a1["id"], a2["id"]])
    summary_pre = get_float_summary()
    exchange = make_order(customer["id"], [{"product_id": gas["id"], "qty": 2}],
                          order_type="EXCHANGE")
    confirm_order(exchange["id"])
    pay_order(exchange["id"], 6000)
    stage_order(exchange["id"])
    return customer, (a1, a2, a3, a4), summary_pre, exchange


class TestExchangeFloatConservation:
    def test_balanced_exchange_conserves_per_grade_totals(self, api):
        """PRD §2.10: "A balanced exchange fulfillment — a customer returning
        k cylinders of a grade and being issued k full cylinders of the same
        grade — leaves the grade's out count and total unchanged while its
        full count drops by k and its empty count rises by k." and "That total
        changes only through registration, which adds one, and retirement,
        which removes one; every other transition merely moves a cylinder
        between buckets."

        Design: Difficulty/compensating_invariant/exchange_float_conservation_per_grade
        """
        customer, (a1, a2, a3, a4), summary_pre, exchange = \
            _exchange_scenario()
        argon_pre = float_grade(summary_pre, "ARGON")
        assert summary_pre["total_assets"] == 4
        assert (argon_pre["full"], argon_pre["empty"], argon_pre["out"],
                argon_pre["total"]) == (2, 0, 2, 4)
        fulfilled = fulfill_order(exchange["id"],
                                  issued_asset_ids=[a3["id"], a4["id"]],
                                  returned_asset_ids=[a1["id"], a2["id"]])
        assert fulfilled["fulfillment_status"] == "FULFILLED"
        summary_post = get_float_summary()
        argon_post = float_grade(summary_post, "ARGON")
        assert summary_post["total_assets"] == 4, \
            "register/retire are the only total-changing operations"
        assert (argon_post["full"], argon_post["empty"], argon_post["out"],
                argon_post["total"]) == (0, 2, 2, 4), \
            "out and total unchanged; full -2, empty +2"

    def test_exchange_flips_asset_states_and_holders(self, api):
        """PRD §3.4: "Fulfilling flips the assets: each issued cylinder moves
        `FULL` → `OUT` with its `holder_customer_id` set to the ordering
        customer, and each returned cylinder moves `OUT` → `EMPTY` with its
        holder link cleared, conserving the float per §2.10."

        Design: Difficulty/compensating_invariant/exchange_float_conservation_per_grade
        """
        customer, (a1, a2, a3, a4), _summary_pre, exchange = \
            _exchange_scenario()
        fulfill_order(exchange["id"], issued_asset_ids=[a3["id"], a4["id"]],
                      returned_asset_ids=[a1["id"], a2["id"]])
        returned = get_cylinder(a1["id"])
        assert returned["status"] == "EMPTY"
        assert returned["holder_customer_id"] is None, "back at the branch"
        issued = get_cylinder(a3["id"])
        assert issued["status"] == "OUT"
        assert issued["holder_customer_id"] == customer["id"], \
            "issued into the customer's custody"


class TestGasLineGuards:
    def test_cylinder_unavailable_at_confirm(self, api, counter_rep_headers):
        """PRD §3.3: "gas lines are stocked as cylinders rather than shelf
        units, so for each `GAS` or `SPECIALTY_GAS` line the branch must hold
        at least as many `FULL` cylinders of the line's grade as the line
        quantity, or the confirm fails with `ERR_CYLINDER_UNAVAILABLE`."

        Design: Corner/validations/cylinder_unavailable_at_confirm
        """
        customer = make_customer(account_no="ACC-VA9", name="Short Co",
                                 terms="CASH")
        make_cylinder(serial_no="CYL-VA9", gas_grade="ARGON", size="LARGE")
        product = make_product(sku="G-ARG-VA9", name="Argon Refill",
                               category="GAS", gas_grade="ARGON",
                               retail_price_cents=3000)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 2}])
        resp = api.confirm_order(order["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_UNAVAILABLE)

    def test_stock_insufficient_at_confirm(self, api, counter_rep_headers):
        """PRD §3.3: "Every `HARDGOOD` line must be covered by the product's
        `stock_on_hand` (a shortfall is `ERR_STOCK_INSUFFICIENT`)".

        Design: Corner/validations/stock_insufficient_at_confirm
        """
        customer = make_customer(account_no="ACC-VA10", name="Stock Co",
                                 terms="CASH")
        product = make_product(sku="HG-VA10", name="Clamp",
                               category="HARDGOOD", retail_price_cents=800,
                               stock=2)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 3}])
        resp = api.confirm_order(order["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_STOCK_INSUFFICIENT)

    def test_exchange_return_grade_mismatch_rejected(self, api,
                                                     counter_rep_headers):
        """PRD §3.4: "An `EXCHANGE` order additionally requires
        `returned_asset_ids`, one per line quantity, where every returned
        cylinder must currently be `OUT`, must be held by the order's customer
        — its `holder_customer_id` equal to the order's `customer_id` — and
        must match the issued grades, with violations again reported as
        `ERR_CYLINDER_GRADE_MISMATCH`."

        Design: Corner/validations/exchange_return_grade_mismatch_rejected
        """
        customer = make_customer(account_no="ACC-VA7", name="Swap Co",
                                 terms="CASH")
        argon = make_cylinder(serial_no="CYL-VA7-AR", gas_grade="ARGON",
                              size="MEDIUM")
        oxygen = make_cylinder(serial_no="CYL-VA7-OX", gas_grade="OXYGEN",
                               size="MEDIUM")
        g_arg = make_product(sku="G-ARG-VA7", name="Argon Refill",
                             category="GAS", gas_grade="ARGON",
                             retail_price_cents=3000)
        g_oxy = make_product(sku="G-OXY-VA7", name="Oxygen Refill",
                             category="GAS", gas_grade="OXYGEN",
                             retail_price_cents=3000)
        # Customer takes the ARGON cylinder out via a retail sale.
        sale = make_order(customer["id"],
                          [{"product_id": g_arg["id"], "qty": 1}])
        confirm_order(sale["id"])
        pay_order(sale["id"], 3000)
        stage_order(sale["id"])
        fulfill_order(sale["id"], issued_asset_ids=[argon["id"]])
        assert get_cylinder(argon["id"])["holder_customer_id"] == customer["id"]
        # Exchange sells OXYGEN but the customer hands back the ARGON unit.
        exchange = make_order(customer["id"],
                              [{"product_id": g_oxy["id"], "qty": 1}],
                              order_type="EXCHANGE")
        confirm_order(exchange["id"])
        pay_order(exchange["id"], 3000)
        stage_order(exchange["id"])
        resp = api.fulfill_order(
            exchange["id"],
            {"issued_asset_ids": [oxygen["id"]],
             "returned_asset_ids": [argon["id"]]}, counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_GRADE_MISMATCH)

    def test_retire_out_cylinder_rejected(self, api, branch_manager_headers):
        """PRD §2.10: "A cylinder that has been condemned — moved to
        `RETIRED`, which is permitted only from `FULL` or `EMPTY`, never while
        the cylinder is `OUT` at a customer site — is permanently out of
        circulation". PRD §2.8: "The target entity's own state permits the
        requested transition ... Violations are `ERR_INVALID_STATE`."

        Design: Corner/state_machines/retire_out_cylinder_rejected
        """
        customer = make_customer(account_no="ACC-SM11", name="Out Co",
                                 terms="CASH")
        asset = make_cylinder(serial_no="CYL-SM11", gas_grade="OXYGEN",
                              size="SMALL")
        product = make_product(sku="G-OXY-SM11", name="Oxygen Refill",
                               category="GAS", gas_grade="OXYGEN",
                               retail_price_cents=2500)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}])
        confirm_order(order["id"])
        pay_order(order["id"], 2500)
        stage_order(order["id"])
        fulfill_order(order["id"], issued_asset_ids=[asset["id"]])
        assert get_cylinder(asset["id"])["status"] == "OUT"
        resp = api.retire_cylinder_asset(asset["id"], branch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
