"""Custom / corporate order lifecycle, mold bookings, and quoting (PRD §3.7).

Covers quote-vs-invoice divergence, the re-quote negotiation cycle, mold
day-capacity aggregation, the mold-active precondition on production start, and
SalesManager-exclusive quoting.
"""
from test_helpers import (
    validate_success, validate_error, make_customer_headers,
    PROD, SALES,
    create_customer, create_product, create_mold, create_custom_order,
    quote_custom_order, accept_custom_order,
    setup_quoted_custom_order, setup_accepted_custom_order,
)


class TestQuoteVsInvoiceDivergence:
    """dual_variant_calc / custom_order_quote_vs_invoice_diverge — provisional
    quote uses units_estimated (100) while final invoice uses units_produced
    (95), so the two amounts diverge."""

    def test_quote_pins_provisional_amount(self):
        """PRD §3.7: "The provisional amount is the estimated unit count
        multiplied by the sum of the product's `base_price_cents` and a per-unit
        mold surcharge of 300 cents, plus a fixed mold setup fee of 25000 cents."

        Design: Difficulty/dual_variant_calc/custom_order_quote_vs_invoice_diverge
        """
        setup = setup_quoted_custom_order(units_estimated=100, base_price=1500, daily_capacity=500)
        # 100 * (1500 + 300) + 25000 = 180000 + 25000 = 205000
        assert setup["custom_order"]["quoted_amount_cents"] == 205000, setup["custom_order"]

    def test_fulfill_pins_final_invoice_diverging_from_quote(self, api):
        """PRD §3.7: "the system pins the final `invoiced_amount_cents` as that
        actual unit count multiplied by the same per-unit base-plus-surcharge
        figure plus the 25000-cent setup fee". PRD §3.7: "The invoiced amount
        equals the earlier quote only when the units produced match the units
        estimated."

        Design: Difficulty/dual_variant_calc/custom_order_quote_vs_invoice_diverge
        """
        setup = setup_accepted_custom_order(
            units_estimated=100, base_price=1500, daily_capacity=500,
            usage_date="2026-07-10T00:00:00Z",
        )
        co_id = setup["custom_order"]["id"]
        validate_success(api.start_production(co_id, PROD))
        co = validate_success(api.fulfill_custom_order(co_id, {"units_produced": 95}, PROD))
        # 95 * (1500 + 300) + 25000 = 171000 + 25000 = 196000
        assert co["invoiced_amount_cents"] == 196000, co
        assert co["quoted_amount_cents"] == 205000, co
        assert co["invoiced_amount_cents"] != co["quoted_amount_cents"], co


class TestRevisionRequoteCycle:
    """non_linear_state_machine / custom_order_revision_requote_cycle — the order
    loops QUOTED -> REVISION_REQUESTED -> QUOTED, re-entering QUOTED with
    quote_round advanced to 2."""

    def test_requote_returns_to_quoted_with_round_two(self, api):
        """PRD §3.7: "a fresh quote may again be issued (`REVISION_REQUESTED ->
        QUOTED`), recomputing `quoted_amount_cents` and again incrementing
        `quote_round`."

        Design: Difficulty/non_linear_state_machine/custom_order_revision_requote_cycle
        """
        setup = setup_quoted_custom_order(units_estimated=50, base_price=1500)
        co_id = setup["custom_order"]["id"]
        cust_headers = make_customer_headers(setup["customer"]["id"])
        validate_success(api.request_revision(co_id, cust_headers, {"note": "smaller size"}))
        co = validate_success(api.quote_custom_order(co_id, SALES))
        assert co["status"] == "QUOTED", co
        assert co["quote_round"] == 2, co

    def test_first_quote_round_one_then_revision_back_edge(self, api):
        """PRD §3.7: "A `SalesManager` issues a quote, advancing the order `DRAFT
        -> QUOTED`; quoting computes the provisional `quoted_amount_cents` and
        increments `quote_round` by 1." PRD §3.7: "A quoted order may be sent back
        by the customer for revision, moving it `QUOTED -> REVISION_REQUESTED`".

        Design: Difficulty/non_linear_state_machine/custom_order_revision_requote_cycle
        """
        setup = setup_quoted_custom_order(units_estimated=50, base_price=1500)
        assert setup["custom_order"]["quote_round"] == 1, setup["custom_order"]
        co_id = setup["custom_order"]["id"]
        cust_headers = make_customer_headers(setup["customer"]["id"])
        co = validate_success(api.request_revision(co_id, cust_headers, {"note": "smaller size"}))
        assert co["status"] == "REVISION_REQUESTED", co


class TestMoldDailyCapacityAggregate:
    """resource_temporal_overlap / mold_daily_capacity_aggregate — two accepts
    for the same mold and usage_date (60+60) exceed daily_capacity_units=100."""

    def _two_quoted_orders_same_mold(self):
        customer = create_customer(account_type="CORPORATE")
        product = create_product(base_price_cents=1500)
        mold = create_mold(daily_capacity_units=100)
        co1 = create_custom_order(customer["id"], product["id"], mold["id"], 60)
        co1 = quote_custom_order(co1["id"])
        accept_custom_order(co1["id"], customer["id"], "2026-07-10T00:00:00Z")
        co2 = create_custom_order(customer["id"], product["id"], mold["id"], 60)
        co2 = quote_custom_order(co2["id"])
        return customer, co2

    def test_second_accept_over_capacity_rejected(self, api):
        """PRD §3.7: "acceptance requires ... that the estimated units plus the
        summed `units` of all `ACTIVE` mold bookings already held for that mold on
        that same `usage_date` do not exceed the mold's `daily_capacity_units`
        (otherwise `ERR_MOLD_CAPACITY_EXCEEDED`)."

        Design: Difficulty/resource_temporal_overlap/mold_daily_capacity_aggregate
        """
        customer, co2 = self._two_quoted_orders_same_mold()
        resp = api.accept_custom_order(
            co2["id"], {"usage_date": "2026-07-10T00:00:00Z"},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, "ERR_MOLD_CAPACITY_EXCEEDED", 409)

    def test_second_order_stays_quoted_after_capacity_rejection(self, api):
        """PRD §3.7: "Accepting advances the order `QUOTED -> ACCEPTED` and books
        the mold". A rejected accept leaves the order in QUOTED (no transition).

        Design: Difficulty/resource_temporal_overlap/mold_daily_capacity_aggregate
        """
        customer, co2 = self._two_quoted_orders_same_mold()
        api.accept_custom_order(
            co2["id"], {"usage_date": "2026-07-10T00:00:00Z"},
            make_customer_headers(customer["id"]),
        )
        fetched = validate_success(api.get_custom_order(co2["id"], make_customer_headers(customer["id"])))
        assert fetched["status"] == "QUOTED", fetched


class TestStartProductionRequiresMoldActive:
    """cross_entity_state_dependency / custom_start_production_requires_mold_active
    — an ACCEPTED custom order cannot start production once its mold is set
    MAINTENANCE."""

    def _accepted_then_mold_maintenance(self, api):
        setup = setup_accepted_custom_order(
            units_estimated=40, base_price=1500, daily_capacity=300,
            usage_date="2026-07-12T00:00:00Z",
        )
        validate_success(api.set_mold_status(setup["mold"]["id"], {"status": "MAINTENANCE"}, PROD))
        return setup

    def test_start_production_with_maintenance_mold_rejected(self, api):
        """PRD §3.7: "Starting production advances it `ACCEPTED -> IN_PRODUCTION`,
        re-checks that the mold's `status` is still `ACTIVE` (again
        `ERR_MOLD_INACTIVE` if not)".

        Design: Difficulty/cross_entity_state_dependency/custom_start_production_requires_mold_active
        """
        setup = self._accepted_then_mold_maintenance(api)
        resp = api.start_production(setup["custom_order"]["id"], PROD)
        validate_error(resp, "ERR_MOLD_INACTIVE", 409)

    def test_custom_order_stays_accepted_after_mold_inactive(self, api):
        """PRD §3.7: "Production of an accepted order is driven by production
        staff. Starting production advances it `ACCEPTED -> IN_PRODUCTION`".
        A rejected start-production leaves the order in ACCEPTED.

        Design: Difficulty/cross_entity_state_dependency/custom_start_production_requires_mold_active
        """
        setup = self._accepted_then_mold_maintenance(api)
        co_id = setup["custom_order"]["id"]
        api.start_production(co_id, PROD)
        fetched = validate_success(api.get_custom_order(co_id, PROD))
        assert fetched["status"] == "ACCEPTED", fetched


def test_customer_cannot_quote_custom_order(api):
    """PRD §2.1: "`SalesManager` owns custom-order quoting, order allocation, and
    manual inventory reservations". A Customer calling quote is denied.

    Design: Corner/rbac/customer_cannot_quote_custom_order
    """
    customer = create_customer(account_type="CORPORATE")
    product = create_product(base_price_cents=1500)
    mold = create_mold(daily_capacity_units=200)
    co = create_custom_order(customer["id"], product["id"], mold["id"], 20)
    resp = api.quote_custom_order(co["id"], make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_UNAUTHORIZED", 403)
