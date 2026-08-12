"""Credit exposure lifecycle and the order revision cycle (PRD §2.10, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_customer_headers,
    make_customer, make_order, confirm_order, get_customer,
    setup_active_grow_formula, setup_confirmed_order,
)

MM = TEST_USERS["mill_manager_headers"]


class TestRevisionCycle:
    def test_order_revision_cycle_requotes_at_current_prices(self, api):
        """PRD §3.5: "Committing the revision moves `REVISING` → `CONFIRMED` with a new, positive `tons`: the order is re-quoted at current prices against the current formula, re-pinning the version, lines, and floors and refreshing `quoted_formula_version`, `quoted_cost_basis_cents`, and `quoted_total_cents`."

        Design: Difficulty/non_linear_state_machine/order_revision_cycle_confirmed_to_revising_to_confirmed
        """
        ctx = setup_confirmed_order(tons=10, credit_limit_cents=1000000)
        order = ctx["order"]
        cust_headers = make_customer_headers(ctx["customer"]["id"])

        revising = validate_success(api.begin_revision(order["id"], cust_headers), 200)
        assert revising["status"] == "REVISING"

        # Re-quoted at current prices for 12t: corn 8.4t*30000 + SBM 3.6t*52000
        # = 439200; margin 52704; delivery 18300 -> 510204.
        committed = validate_success(
            api.commit_revision(order["id"], {"tons": 12}, cust_headers), 200)
        assert committed["status"] == "CONFIRMED"
        assert committed["tons"] == pytest.approx(12, abs=1e-6)
        assert committed["quoted_total_cents"] == 510204

    def test_revision_releases_and_recharges_credit(self, api):
        """PRD §3.5: "Beginning a revision moves `CONFIRMED` → `REVISING` and is permitted only while no batch of the order is `BATCHING`, `MIXED`, or `HOLD`; it releases the quoted total from the customer's exposure and increments both versions."
        PRD §2.10: "Orders in `QUOTED`, `REVISING`, `DELIVERED`, or `CANCELLED` contribute nothing."

        Design: Difficulty/non_linear_state_machine/order_revision_cycle_confirmed_to_revising_to_confirmed
        """
        ctx = setup_confirmed_order(tons=10, credit_limit_cents=1000000)
        order = ctx["order"]
        cust_headers = make_customer_headers(ctx["customer"]["id"])

        charged = get_customer(ctx["customer"]["id"])
        assert charged["credit_used_cents"] == 426420

        validate_success(api.begin_revision(order["id"], cust_headers), 200)
        released = get_customer(ctx["customer"]["id"])
        assert released["credit_used_cents"] == 0, (
            "REVISING orders contribute nothing to exposure")

        validate_success(api.commit_revision(order["id"], {"tons": 12}, cust_headers), 200)
        recharged = get_customer(ctx["customer"]["id"])
        assert recharged["credit_used_cents"] == 510204


class TestCreditConfirmCancelInvariant:
    def test_confirm_charges_credit_exposure(self, api):
        """PRD §2.10: "Exposure moves as orders move: it is charged at confirmation, released when a revision begins, re-charged when the revision commits, reclassed from quoted to final at completion, and released entirely on delivery or cancellation."

        Design: Difficulty/compensating_invariant/credit_confirm_then_cancel_restores_exposure
        """
        env = setup_active_grow_formula()
        customer = make_customer("Acme Farms", 500000)
        before = get_customer(customer["id"])
        assert before["credit_used_cents"] == 0, "QUOTED orders contribute nothing"

        order = make_order(customer, env["formula"]["id"], 10)
        mid = get_customer(customer["id"])
        assert mid["credit_used_cents"] == 0

        order = confirm_order(order, customer["id"])
        after = get_customer(customer["id"])
        assert after["credit_used_cents"] == 426420, (
            "the quoted total joins the customer's exposure at confirmation")

    def test_cancel_releases_credit_exposure(self, api):
        """PRD §2.10: "Exposure moves as orders move: it is charged at confirmation, released when a revision begins, re-charged when the revision commits, reclassed from quoted to final at completion, and released entirely on delivery or cancellation."
        PRD §3.5: "From `CONFIRMED`, cancellation is refused with `ERR_INVALID_STATE` while any batch of the order is `PLANNED`, `BATCHING`, `MIXED`, or `HOLD`, or any delivery trip is `PLANNED`, `LOADING`, or `IN_TRANSIT`; when it proceeds, the quoted exposure is released and the customer's `version` increments alongside the order's."

        Design: Difficulty/compensating_invariant/credit_confirm_then_cancel_restores_exposure
        """
        env = setup_active_grow_formula()
        customer = make_customer("Acme Farms", 500000)
        order = make_order(customer, env["formula"]["id"], 10)
        order = confirm_order(order, customer["id"])
        assert get_customer(customer["id"])["credit_used_cents"] == 426420

        cancelled = validate_success(
            api.cancel_order(order["id"], make_customer_headers(customer["id"])), 200)
        assert cancelled["status"] == "CANCELLED"

        after = get_customer(customer["id"])
        assert after["credit_used_cents"] == 0, (
            "confirm + cancel conserves exposure: back to the pre-confirm value")


class TestCreditLimitGate:
    def test_confirm_at_exact_credit_limit_passes(self, api):
        """PRD §2.10: "The credit gate itself admits equality: an order whose quoted total would bring the exposure exactly to the limit passes."

        Design: Corner/validations/confirm_at_exact_credit_limit_passes
        """
        env = setup_active_grow_formula()
        # Limit exactly equal to the 10t F-GROW quote of 426420 cents.
        customer = make_customer("Exact Eddie", 426420)
        order = make_order(customer, env["formula"]["id"], 10)

        confirmed = validate_success(
            api.confirm_order(order["id"], make_customer_headers(customer["id"])), 200)
        assert confirmed["status"] == "CONFIRMED"

        after = get_customer(customer["id"])
        assert after["credit_used_cents"] == 426420

    def test_confirm_over_credit_limit_rejected(self, api):
        """PRD §3.5: "`credit_used_cents` plus `quoted_total_cents` must not exceed `credit_limit_cents`, with equality passing (`ERR_CREDIT_LIMIT_EXCEEDED`)."

        Design: Corner/errors/confirm_over_credit_limit_rejected
        """
        env = setup_active_grow_formula()
        customer = make_customer("Thin Credit Co", 400000)
        order = make_order(customer, env["formula"]["id"], 10)  # quote 426420 > 400000

        resp = api.confirm_order(order["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

        after = validate_success(api.get_order(order["id"], MM), 200)
        assert after["status"] == "QUOTED", "rejected confirm must leave the order QUOTED"
        assert get_customer(customer["id"])["credit_used_cents"] == 0
