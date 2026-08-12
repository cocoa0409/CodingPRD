"""Optimistic concurrency control on customer and formula versions (PRD §2.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_customer_headers,
    create_order_payload,
    make_ingredient, add_price_tick, make_formula, optimize_formula,
    make_customer, make_order, get_customer,
    setup_active_grow_formula,
)

MM = TEST_USERS["mill_manager_headers"]
NUT = TEST_USERS["nutritionist_headers"]


class TestOrderCreateStaleCustomerVersion:
    def test_occ_order_create_stale_customer_version(self, api):
        """PRD §2.6: "Creating a customer order requires the request to carry `expected_customer_version`, holding the `version` of the customer as the client last observed it. If the customer's current `version` has advanced past that value — because another writer has created an order or otherwise mutated the customer's credit posture — the create is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412): the client must not write from a view of the customer it has not re-observed."
        PRD §2.6: "Re-reading the customer and retrying with the fresh version succeeds, because creating several orders for one customer is a legitimate flow."

        Design: Corner/cross_cutting_complexity_layers/occ_order_create_stale_customer_version
        """
        env = setup_active_grow_formula()
        customer = make_customer("Acme Farms", 5000000)
        cust_headers = make_customer_headers(customer["id"])
        stale_version = customer["version"]

        # First create succeeds and mutates the customer's credit posture.
        order1 = validate_success(api.create_order(
            create_order_payload(env["formula"]["id"], 10, stale_version),
            cust_headers), 201)
        assert order1["status"] == "QUOTED"
        mid = get_customer(customer["id"])
        assert mid["version"] == stale_version + 1, (
            "creating an order increments the customer's version by one (PRD §3.5)")

        # Replaying the stale view is rejected.
        resp = api.create_order(
            create_order_payload(env["formula"]["id"], 5, stale_version),
            cust_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_CUSTOMER_VERSION)

        # Re-read and retry with the fresh version succeeds.
        fresh = get_customer(customer["id"])
        order2 = validate_success(api.create_order(
            create_order_payload(env["formula"]["id"], 5, fresh["version"]),
            cust_headers), 201)
        assert order2["status"] == "QUOTED"


class TestOptimizeStaleFormulaVersion:
    def test_occ_optimize_stale_formula_version(self, api):
        """PRD §2.6: "Re-running ration optimization requires `expected_formula_version`, matched against the formula's current `version`; a mismatch is rejected with `ERR_STALE_FORMULA_VERSION` (HTTP 412), since the client's view of the ration's lines and cost basis is stale."
        PRD §2.6: "Sequential re-read of the formula and retry with the fresh version succeeds, because re-optimization is a legitimate, repeatable operation."

        Design: Corner/cross_cutting_complexity_layers/occ_optimize_stale_formula_version
        """
        corn = make_ingredient("CORN")
        sbm = make_ingredient("SBM")
        add_price_tick(corn["id"], 30000)
        add_price_tick(sbm["id"], 52000)
        formula = make_formula("F-GROW")
        v0 = formula["version"]

        # First optimize advances the version by exactly one.
        solved = optimize_formula(formula)
        assert solved["version"] == v0 + 1

        # Replaying the captured, now-stale version is rejected.
        resp = api.optimize_formula(
            formula["id"], {"expected_formula_version": v0}, NUT)
        validate_error(resp, ApiErrorId.ERR_STALE_FORMULA_VERSION)

        # Fresh read + retry succeeds; re-optimization is legitimate.
        fresh = validate_success(api.get_formula(formula["id"], NUT), 200)
        solved2 = validate_success(api.optimize_formula(
            formula["id"], {"expected_formula_version": fresh["version"]}, NUT), 200)
        assert solved2["version"] == v0 + 2
