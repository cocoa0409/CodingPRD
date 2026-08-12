"""Subscriptions: activation, cancellation, OCC create, season-end sweep
(PRD §2.7, §3.3, §3.9)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_subscription_payload, create_payment_payload,
    set_clock, create_customer, create_product, create_route, create_window,
    create_order, create_subscription, create_activated_subscription,
    submit_and_pay, schedule_order, create_delivered_order,
    TEST_USERS,
)

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]
RP = TEST_USERS["route_planner_headers"]


class TestSubscriptionCancelFromPending:
    def test_subscription_pending_to_cancelled_no_credit_movement(self, api):
        """PRD §3.3: "Cancelling a `PENDING` subscription simply sets
        `closed_at`; no credit moves, because the prepayment was never
        credited."

        Design: Corner/state_machines/subscription_pending_to_cancelled_no_credit_movement
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = create_customer()
        subscription = create_subscription(customer["id"], tier="HEARTH",
                                           season_year=2026,
                                           commitment_cord_equivalent=2.0,
                                           prepaid_cents=5000, discount_pct=0.05)
        assert subscription["status"] == "PENDING"
        cancelled = validate_success(api.cancel_subscription(
            subscription["id"], {"reason": "changed mind"}, CS), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["closed_at"] is not None
        customer_after = get_success_data(api.get_customer(customer["id"], CS))
        assert customer_after["credit_balance_cents"] == 0


class TestActivationSeasonRule:
    def test_activation_after_season_start_rejected(self, api):
        """PRD §3.3: "Activation is an `OperationsManager` action with a hard
        calendar rule: the logical date must be on or before November 1 of
        `season_year`, because retroactive activation would break commitment
        arithmetic; a late activation is rejected with
        `ERR_SUBSCRIPTION_OUT_OF_SEASON`."

        Design: Corner/validations/activation_after_season_start_rejected
        """
        set_clock("2026-11-15T00:00:00Z")
        customer = create_customer()
        subscription = create_subscription(customer["id"], tier="HEARTH",
                                           season_year=2026,
                                           commitment_cord_equivalent=2.0,
                                           prepaid_cents=0, discount_pct=0.05)
        res = api.activate_subscription(subscription["id"], OM)
        validate_error(res, "ERR_SUBSCRIPTION_OUT_OF_SEASON", expected_status=422)


class TestOccStaleVersionOnSubscriptionCreate:
    def test_occ_stale_version_on_subscription_create(self, api):
        """PRD §2.7: "Creating a winter subscription requires the request to
        carry `expected_customer_version` equal to the customer's current
        `version`. A mismatch means a credit adjustment or account-status
        mutation has invalidated the customer's observed state, and the create
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_subscription_create
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = create_customer()
        stale_version = customer["version"]
        # Intervening mutation: wallet adjustment advances Customer.version.
        get_success_data(api.adjust_wallet(
            customer["id"], {"amount_cents": 100, "reason": "bump version"}, OM))
        res = api.create_subscription(create_subscription_payload(
            customer["id"], stale_version, tier="HEARTH", season_year=2026,
            commitment_cord_equivalent=2.0, prepaid_cents=0, discount_pct=0.05), CS)
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)


class TestSeasonEndSweep:
    """Non-linear seasonal branching: FULFILLED via delivery bubble-up vs
    SHORTFALL via the April 1 sweep."""

    def _setup_two_subscriptions(self, api):
        set_clock("2026-10-01T00:00:00Z")
        cust_met = create_customer(postal_code="40006", full_name="Cu Six",
                                   email="cu6@x.com")
        cust_short = create_customer(postal_code="40007", full_name="Cu Seven",
                                     email="cu7@x.com")
        sub_met = create_activated_subscription(
            cust_met["id"], tier="HEARTH", season_year=2026,
            commitment_cord_equivalent=2.0, prepaid_cents=0, discount_pct=0.05)
        sub_short = create_activated_subscription(
            cust_short["id"], tier="HEARTH", season_year=2026,
            commitment_cord_equivalent=2.0, prepaid_cents=0, discount_pct=0.05)
        product = create_product(sku="P6", product_kind="CORD", species="OAK",
                                 seasoned_grade="KILN_DRIED", base_price_cents=40000,
                                 moisture_ceiling_pct=20.0, available_qty=100)
        route = create_route(route_code="R6", depot_name="East",
                             prefixes=("4",), capacity=100.0)
        # cust_met takes delivery of 2.5 CE inside the season window.
        create_delivered_order(
            cust_met["id"], product["id"], 2.5, route, postal_code="40006",
            service_date="2027-01-15", subscription_id=sub_met["id"])
        return cust_met, cust_short, sub_met, sub_short, product, route

    def test_subscription_fulfilled_by_delivery_before_sweep(self, api):
        """PRD §3.3: "The moment a delivery pushes `delivered_cord_equivalent`
        to at least `commitment_cord_equivalent`, the subscription
        auto-transitions from `ACTIVE` to `FULFILLED` with `closed_at` set to
        that delivery's timestamp."

        Design: Difficulty/non_linear_state_machine/subscription_cyclic_seasonal_with_terminal_branching
        """
        _cm, _cs, sub_met, sub_short, _p, _r = self._setup_two_subscriptions(api)
        sub_met_after = get_success_data(api.get_subscription(sub_met["id"], CS))
        assert sub_met_after["status"] == "FULFILLED"
        assert sub_met_after["closed_at"] is not None
        # The shortfall subscription is untouched before the sweep.
        sub_short_after = get_success_data(api.get_subscription(sub_short["id"], CS))
        assert sub_short_after["status"] == "ACTIVE"

    def test_subscription_cyclic_seasonal_with_terminal_branching(self, api):
        """PRD §3.3: "Whatever remains `ACTIVE` when the logical clock crosses
        April 1 at 00:00:00 of the closing year is swept: a subscription short
        of its commitment transitions to `SHORTFALL` and is penalized per §3.9,
        while one whose commitment was already met — a defensive branch that is
        normally unreachable, retained for manual recovery — transitions to
        `EXPIRED`."
        PRD §3.9: "The shortfall volume is `commitment_cord_equivalent` minus
        `delivered_cord_equivalent`."
        PRD §3.9: "if the customer took no such delivery, the reference falls
        back to the highest `base_price_cents` among `KILN_DRIED` `CORD`
        products in the catalog, uplifted by the kiln-dried multiplier of 1.35.
        The penalty is twenty percent of the shortfall volume times that
        reference price, rounded half-up to integer cents."
        Shortfall here: (2.0 - 0) x (40000 x 1.35) x 0.20 = 21600 cents.

        Design: Difficulty/non_linear_state_machine/subscription_cyclic_seasonal_with_terminal_branching
        """
        _cm, cust_short, sub_met, sub_short, _p, _r = \
            self._setup_two_subscriptions(api)
        set_clock("2027-04-01T00:00:00Z")
        sweep = get_success_data(api.sweep_season_end(2026, OM))
        sub_met_after = get_success_data(api.get_subscription(sub_met["id"], CS))
        assert sub_met_after["status"] == "FULFILLED"
        sub_short_after = get_success_data(api.get_subscription(sub_short["id"], CS))
        assert sub_short_after["status"] == "SHORTFALL"
        assert sub_short_after["closed_at"] is not None
        # A shortfall invoice is posted for the customer with no deliveries.
        invoices = get_success_data(api.list_invoices(
            CS, params={"customer_id": cust_short["id"]}))
        assert len(invoices) >= 1
        penalty_amounts = [inv["amount_cents"] for inv in invoices]
        assert 21600 in penalty_amounts
