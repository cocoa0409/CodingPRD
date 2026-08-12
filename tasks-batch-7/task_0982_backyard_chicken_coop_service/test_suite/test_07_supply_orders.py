"""Supply orders: fiscal credit gate, state-vs-fiscal priority, fulfillment
visit linkage."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_household, create_coop, create_visit, create_product,
    assign_visit, create_order, place_order, make_customer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestCreditLimitGate:
    def _order_over_limit(self, api, total_per_line=15000, lines=2):
        household = create_household(name="H CL", address="51 Hen Ln")
        create_product(sku="COOP-KIT", name="Coop Kit", category="EGG_SUPPLIES",
                       unit_price_cents=total_per_line)
        order = create_order(household, [("COOP-KIT", 1)] * lines)
        return household, order

    def test_place_over_credit_limit_rejected(self, api):
        """PRD §3.8: "The fiscal gate runs last: the order's `total_cents` must
        not exceed the household's `wallet_credit_cents` plus a 20000-cent
        credit limit, or placement is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 402)."

        Design: Corner/errors/order_place_over_credit_limit_rejected
        """
        household, order = self._order_over_limit(api)
        res = api.place_order(order["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        after = validate_success(api.get_supply_order(order["id"], DISPATCHER), 200)
        assert after["status"] == "DRAFT"


class TestStateBeatsFiscal:
    def _suspended_household_with_over_limit_order(self, api):
        household = create_household(name="H Prio1", address="8 Hen Ln")
        create_product(sku="COOP-KIT", name="Coop Kit", category="EGG_SUPPLIES",
                       unit_price_cents=15000)
        order = create_order(household, [("COOP-KIT", 1), ("COOP-KIT", 1)])
        validate_success(api.suspend_household(household["id"], BILLING), 200)
        return household, order

    def test_suspended_household_surfaces_state_error_not_fiscal(self, api):
        """PRD §3.8: "Placement freezes the order. Placing requires the `DRAFT`
        state, an `ACTIVE` household (else `ERR_ACCOUNT_SUSPENDED`), at least
        one line (else `ERR_ORDER_EMPTY`), and — when a fulfillment visit is
        linked — that the visit belongs to the same household and is currently
        `SCHEDULED` (else `ERR_FULFILLMENT_VISIT_INVALID`)."
        PRD §2.8: "The practical consequence: a request that fails both a state
        check and a money check surfaces the state error, because fiscal checks
        are evaluated only after every other category has passed."

        Design: Difficulty/priority_pair_validation_conflict/order_place_state_beats_fiscal
        """
        household, order = self._suspended_household_with_over_limit_order(api)
        res = api.place_order(order["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        after = validate_success(api.get_supply_order(order["id"], DISPATCHER), 200)
        assert after["status"] == "DRAFT"

    def test_fiscal_gate_fires_once_state_gate_passes(self, api):
        """PRD §3.8: "The fiscal gate runs last: the order's `total_cents` must
        not exceed the household's `wallet_credit_cents` plus a 20000-cent
        credit limit, or placement is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 402)."
        PRD §3.1: "A `BillingAdmin` may reinstate a `SUSPENDED` household back
        to `ACTIVE`; attempting it on a household that is not `SUSPENDED`
        yields `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/order_place_state_beats_fiscal
        """
        household, order = self._suspended_household_with_over_limit_order(api)
        validate_success(api.reinstate_household(household["id"], BILLING), 200)
        res = api.place_order(order["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestFulfillmentLinkage:
    def test_place_with_unscheduled_fulfillment_visit_rejected(self, api):
        """PRD §3.8: "Placement freezes the order. Placing requires the `DRAFT`
        state, an `ACTIVE` household (else `ERR_ACCOUNT_SUSPENDED`), at least
        one line (else `ERR_ORDER_EMPTY`), and — when a fulfillment visit is
        linked — that the visit belongs to the same household and is currently
        `SCHEDULED` (else `ERR_FULFILLMENT_VISIT_INVALID`)."

        Design: Corner/validations/order_fulfillment_visit_not_scheduled_rejected
        """
        household = create_household(name="H FV", address="46 Hen Ln")
        coop = create_coop(household, 4)
        visit = create_visit(household, coop, "SETUP_INSTALL",
                             "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")
        assert visit["status"] == "REQUESTED"
        create_product(sku="FEED-C", name="Grower Feed", unit_price_cents=700)
        order = create_order(household, [("FEED-C", 1)], fulfillment_visit_id=visit["id"])

        res = api.place_order(order["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_FULFILLMENT_VISIT_INVALID)
        after = validate_success(api.get_supply_order(order["id"], DISPATCHER), 200)
        assert after["status"] == "DRAFT"
