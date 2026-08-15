"""Shortage allocation: PRO_RATA tiered grants, EQUAL_SHARE exhaustion,
provisional vs final invoice variants, OCC stale-version rejection, policy
lifecycle, and the pool-conservation invariant under cancel."""
from test_helpers import (
    ApiErrorId,
    FulfillmentStatus,
    LineStatus,
    allocate_order,
    create_product,
    declare_shortage,
    get_order,
    get_policy,
    get_single_line,
    open_allocation_policy,
    set_clock,
    setup_confirmed_order,
    setup_customer_with_license,
    setup_shortage_order,
    setup_shortage_product,
    validate_error,
    validate_success,
)


class TestProvisionalVsFinalInvoice:
    """The provisional variant prices requested quantities at confirm; the
    final variant re-prices allocated quantities after the allocation run."""

    def _setup_shortage_340b_order(self):
        """One 340B line qty 10 (WAC 10000 / contract 7000) under a PRO_RATA
        pool of 6 with no other competitor."""
        set_clock()
        product, policy = setup_shortage_product(
            wac_cents=10000, pool_units=6, policy_mode="PRO_RATA",
            min_guarantee_units=0, is_340b_contracted=True,
            contract_340b_price_cents=7000,
        )
        customer, order = setup_shortage_order(
            product["id"], 10, customer_name="C1 Pharmacy", is_340b_order=True
        )
        return customer, product, policy, order

    def test_provisional_invoice_prices_requested_quantities_at_confirm(
        self, api, order_manager_headers
    ):
        """PRD §3.4: "The `unit_price_cents` is the product's
        `contract_340b_price_cents` when the order `is_340b_order` and the
        product `is_340b_contracted`, and the product's
        `wholesale_acquisition_cost_cents` otherwise."
        PRD §3.4: "Because nothing has been allocated yet, the provisional
        `extended_price_cents` for each line is the unit price times the
        requested quantity, and the provisional `invoice_total_cents` is the
        sum of those extended prices".

        Provisional variant: 10 requested x 7000 contract price = 70000.

        Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_invoice
        """
        _c, _p, _pol, order = self._setup_shortage_340b_order()
        assert order["invoice_total_cents"] == 70000, (
            f"provisional invoice must be 10 x 7000 = 70000, "
            f"got {order['invoice_total_cents']}"
        )
        assert order["invoice_balance_cents"] == 70000
        line = get_single_line(order["id"])
        assert line["unit_price_cents"] == 7000
        assert line["extended_price_cents"] == 70000

    def test_final_invoice_after_allocation_uses_allocated_quantities(
        self, api, order_manager_headers
    ):
        """PRD §3.5: "Under a `PRO_RATA` policy, the distributable remainder is
        the policy's `pool_units` less the per-customer floor multiplied by the
        competing order count; the line's grant is then `min_guarantee_units`
        plus the whole-unit floor of the remainder multiplied by the line's
        `quantity_requested` and divided by the total competing demand".
        PRD §3.5: "After the run, the invoice is finalized: each line's
        `extended_price_cents` is recomputed as the unit price times the
        allocated quantity, so the final total under shortage is strictly
        smaller than the provisional total priced on requested quantities."

        Final variant: grant = 0 + floor(6 x 10 / 10) = 6; final invoice
        6 x 7000 = 42000, strictly below the 70000 provisional.

        Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_invoice
        """
        _c, _p, _pol, order = self._setup_shortage_340b_order()
        provisional = order["invoice_total_cents"]

        final = allocate_order(order["id"], expected_version=order["version"])
        assert final["invoice_total_cents"] == 42000, (
            f"final invoice must be 6 x 7000 = 42000, got {final['invoice_total_cents']}"
        )
        assert final["invoice_total_cents"] != provisional
        assert final["invoice_total_cents"] < provisional
        line = get_single_line(order["id"])
        assert line["quantity_allocated"] == 6
        assert line["extended_price_cents"] == 42000


class TestProRataTieredFormula:
    """Min-guarantee floor + floor-division share + three-way cap interact:
    pool 100, min_guarantee 2, competing demands 30/70."""

    def _setup_two_competing_orders(self):
        set_clock()
        product, policy = setup_shortage_product(
            wac_cents=1000, pool_units=100, policy_mode="PRO_RATA",
            min_guarantee_units=2,
        )
        cust_a, order_a = setup_shortage_order(product["id"], 30, customer_name="PA")
        cust_b, order_b = setup_shortage_order(product["id"], 70, customer_name="PB")
        return product, policy, order_a, order_b

    def test_first_order_grant_hits_min_guarantee_plus_share_capped_at_request(
        self, api, order_manager_headers
    ):
        """PRD §3.5: "the line's grant is then `min_guarantee_units` plus the
        whole-unit floor of the remainder multiplied by the line's
        `quantity_requested` and divided by the total competing demand, and a
        grant never falls below its zero-unit floor."
        PRD §3.5: "when every line is fully allocated the order advances on its
        own from `CONFIRMED` to `ALLOCATED`."

        Order A: distributable = 100 - 2x2 = 96; grant = 2 + floor(96x30/100)
        = 30, capped at the request of 30 -> fully allocated.

        Design: Difficulty/combinatorial_formula/pro_rata_allocation_tiered_formula
        """
        _p, _pol, order_a, _b = self._setup_two_competing_orders()
        result = allocate_order(order_a["id"], expected_version=order_a["version"])

        line = get_single_line(order_a["id"])
        assert line["quantity_allocated"] == 30, (
            f"grant 2 + floor(96*30/100) = 30 capped at requested 30; "
            f"got {line['quantity_allocated']}"
        )
        assert line["line_status"] == LineStatus.ALLOCATED.value
        assert result["fulfillment_status"] == FulfillmentStatus.ALLOCATED.value

    def test_second_order_grant_and_stranded_remainder(
        self, api, order_manager_headers
    ):
        """PRD §3.5: "the granted `quantity_allocated` is the smallest of three
        values: the grant, the line's requested quantity, and the policy's
        `remaining_units`."
        PRD §3.5: "The line then becomes `ALLOCATED` when the grant covers the
        full request, `PARTIALLY_ALLOCATED` when some but not all of the request
        is granted, and `UNFULFILLABLE` when nothing is granted".

        Order B: grant = 2 + floor(96x70/100) = 69 < 70 requested ->
        PARTIALLY_ALLOCATED; the pool strands 1 unit (100 - 30 - 69).

        Design: Difficulty/combinatorial_formula/pro_rata_allocation_tiered_formula
        """
        _p, policy, order_a, order_b = self._setup_two_competing_orders()
        allocate_order(order_a["id"], expected_version=order_a["version"])
        allocate_order(order_b["id"], expected_version=order_b["version"])

        line_b = get_single_line(order_b["id"])
        assert line_b["quantity_allocated"] == 69, (
            f"grant 2 + floor(96*70/100) = 69; got {line_b['quantity_allocated']}"
        )
        assert line_b["line_status"] == LineStatus.PARTIALLY_ALLOCATED.value

        pol = get_policy(policy["id"])
        assert pol["remaining_units"] == 1, (
            f"pool 100 - 30 - 69 must strand 1 unit, got {pol['remaining_units']}"
        )
        assert pol["policy_status"] == "OPEN"


class TestEqualShareExhaustion:
    def test_equal_share_split_and_exhaustion_at_zero(self, api, order_manager_headers):
        """PRD §3.5: "Under an `EQUAL_SHARE` policy, the grant is `pool_units`
        divided by the competing order count, rounded down to a whole unit."
        PRD §3.5: "a policy whose `remaining_units` reaches zero flips to
        `EXHAUSTED`."
        PRD §3.2: "When an allocation run drives `remaining_units` to zero, the
        policy flips from `OPEN` to `EXHAUSTED` on its own."

        Pool 10 with two competing orders of 8 each: floor(10/2) = 5 apiece;
        the second run drives remaining_units to exactly 0 and the policy
        auto-flips to EXHAUSTED.

        Design: Corner/cross_cutting_layers/equal_share_allocation_exhaustion
        """
        set_clock()
        product, policy = setup_shortage_product(
            wac_cents=100, pool_units=10, policy_mode="EQUAL_SHARE",
            min_guarantee_units=0,
        )
        _ca, order_a = setup_shortage_order(product["id"], 8, customer_name="EqA")
        _cb, order_b = setup_shortage_order(product["id"], 8, customer_name="EqB")

        allocate_order(order_a["id"], expected_version=order_a["version"])
        allocate_order(order_b["id"], expected_version=order_b["version"])

        line_a = get_single_line(order_a["id"])
        line_b = get_single_line(order_b["id"])
        assert line_a["quantity_allocated"] == 5, f"floor(10/2) == 5, got {line_a['quantity_allocated']}"
        assert line_b["quantity_allocated"] == 5
        assert line_a["line_status"] == LineStatus.PARTIALLY_ALLOCATED.value
        assert line_b["line_status"] == LineStatus.PARTIALLY_ALLOCATED.value

        pol = get_policy(policy["id"])
        assert pol["remaining_units"] == 0
        assert pol["policy_status"] == "EXHAUSTED"


class TestAllocateOcc:
    def test_allocate_with_stale_expected_version_rejected(self, api, order_manager_headers):
        """PRD §2.7: "That request must carry `expected_order_version`, a
        non-optional input field holding the order `version` the caller last
        observed. If the supplied value does not equal the order's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)
        and nothing is mutated".
        PRD §2.4: "wherever a transition's definition increments a resource's
        `version`, it does so by exactly one".

        The first allocate succeeds; replaying the same captured version is
        stale because the run incremented the order's version by one.

        Design: Corner/endpoints/allocate_occ_stale_version_conflict
        """
        set_clock()
        customer, _lic = setup_customer_with_license(name="OccRx")
        product = create_product(wholesale_acquisition_cost_cents=100)
        order = setup_confirmed_order(customer["id"], product["id"], 2)
        confirmed_version = order["version"]

        first = api.allocate_order(
            order["id"], {"expected_order_version": confirmed_version}, order_manager_headers
        )
        validate_success(first)

        replay = api.allocate_order(
            order["id"], {"expected_order_version": confirmed_version}, order_manager_headers
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        refreshed = get_order(order["id"])
        assert refreshed["version"] == confirmed_version + 1, (
            f"only the successful run bumped the version: expected "
            f"{confirmed_version + 1}, got {refreshed['version']}"
        )


class TestPolicyLifecycle:
    def test_policy_close_from_closed_rejected(self, api, order_manager_headers):
        """PRD §3.2: "An `OrderManager` may also close a policy outright from
        either `OPEN` or `EXHAUSTED`, moving it to the terminal `CLOSED` state
        and incrementing `version`; closing from any other state is rejected
        with `ERR_POLICY_NOT_CLOSABLE`."

        Design: Corner/errors/policy_close_from_closed_rejected
        """
        product = create_product()
        declare_shortage(product["id"])
        policy = open_allocation_policy(product["id"], 10, policy_mode="EQUAL_SHARE")

        first = api.close_allocation_policy(policy["id"], order_manager_headers)
        assert validate_success(first)["policy_status"] == "CLOSED"

        resp = api.close_allocation_policy(policy["id"], order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_CLOSABLE)


class TestAllocationPoolInvariant:
    """Pool conservation: pool_units == remaining_units + units held by
    non-cancelled orders, conserved across allocate/cancel pairs."""

    def _setup_drained_pool(self):
        """Pool of 6; a sole competing order for 10 drains it to 0."""
        set_clock()
        product, policy = setup_shortage_product(
            wac_cents=1000, pool_units=6, policy_mode="PRO_RATA", min_guarantee_units=0
        )
        customer, order = setup_shortage_order(product["id"], 10, customer_name="PoolRx")
        allocated = allocate_order(order["id"], expected_version=order["version"])
        return product, policy, customer, allocated

    def test_allocation_draining_pool_flips_policy_exhausted(
        self, api, order_manager_headers
    ):
        """PRD §3.5: "the granted `quantity_allocated` is the smallest of three
        values: the grant, the line's requested quantity, and the policy's
        `remaining_units`. Before the policy's `remaining_units` is decremented,
        any units the line already held from a previous allocation run are added
        back".
        PRD §3.2: "When an allocation run drives `remaining_units` to zero, the
        policy flips from `OPEN` to `EXHAUSTED` on its own."

        Design: Difficulty/compensating_invariant/allocation_pool_cancel_release_invariant
        """
        _p, policy, _c, order = self._setup_drained_pool()
        line = get_single_line(order["id"])
        assert line["quantity_allocated"] == 6
        assert line["line_status"] == LineStatus.PARTIALLY_ALLOCATED.value

        pol = get_policy(policy["id"])
        assert pol["remaining_units"] == 0
        assert pol["policy_status"] == "EXHAUSTED"

    def test_cancel_releases_units_and_reopens_policy(self, api, order_manager_headers):
        """PRD §3.5: "any units the order held are released back to the
        allocation policy that granted them — whether that policy is `OPEN` or
        `EXHAUSTED`, with an `EXHAUSTED` policy flipping back to `OPEN` once its
        `remaining_units` rises above zero."
        PRD §3.2: "The policy's `remaining_units` initializes to `pool_units`
        and may never go negative".

        Cancelling the CONFIRMED allocated order restores remaining_units to
        the full pool of 6 and flips the policy back to OPEN.

        Design: Difficulty/compensating_invariant/allocation_pool_cancel_release_invariant
        """
        _p, policy, _c, order = self._setup_drained_pool()
        assert get_policy(policy["id"])["policy_status"] == "EXHAUSTED"

        validate_success(api.cancel_order(order["id"], order_manager_headers))
        pol = get_policy(policy["id"])
        assert pol["remaining_units"] == 6, (
            f"released units must restore the full pool; got {pol['remaining_units']}"
        )
        assert pol["policy_status"] == "OPEN"
