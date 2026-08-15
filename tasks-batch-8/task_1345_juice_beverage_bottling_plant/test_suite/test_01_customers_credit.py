"""Customer onboarding, credit lifecycle, payments, and the credit sweep."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, quote_run, setup_completed_run, place_order,
    allocate_order, ship_allocated_order, set_clock,
)

PM = TEST_USERS["plant_manager_headers"]
FIN = TEST_USERS["finance_clerk_headers"]
PLAN = TEST_USERS["production_planner_headers"]


class TestCustomerCreateDefaults:
    def test_customer_create_born_pending_credit(self, api):
        """PRD §3.1: "The account is born in `PENDING_CREDIT` with
        `outstanding_balance_cents` at zero, and exactly one pallet account is
        created alongside it with every counter at zero (§3.10)."

        Design: Corner/entities/customer_create_defaults_and_pallet_account
        """
        resp = api.create_customer(factories.create_customer_payload(), PM)
        customer = validate_success(resp, 201)
        assert customer["status"] == "PENDING_CREDIT"
        assert customer["outstanding_balance_cents"] == 0

    def test_customer_create_auto_creates_single_zeroed_pallet_account(self, api):
        """PRD §3.1: "The account is born in `PENDING_CREDIT` with
        `outstanding_balance_cents` at zero, and exactly one pallet account is
        created alongside it with every counter at zero (§3.10)."

        Design: Corner/entities/customer_create_defaults_and_pallet_account
        """
        customer = create_customer(approve=False)
        accounts = get_success_data(api.get_customer_pallet_account(customer["id"], PM))
        assert isinstance(accounts, list) and len(accounts) == 1, (
            f"expected exactly one pallet account, got {accounts}")
        account = accounts[0]
        assert account["customer_id"] == customer["id"]
        assert account["pallets_out_total"] == 0
        assert account["pallets_returned_total"] == 0
        assert account["pallets_converted_total"] == 0
        assert account["pallets_outstanding"] == 0
        assert account["escrow_balance_cents"] == 0


class TestCustomerClose:
    def test_close_blocked_by_open_run(self, api):
        """PRD §3.1: "Closure from `ACTIVE` or `SUSPENDED` to `CLOSED` — again a
        `FinanceClerk` action — is refused with `ERR_CUSTOMER_STATE_INVALID` while
        any of the customer's production runs sits in `QUOTED`, `CONFIRMED`,
        `SCHEDULED`, `IN_PRODUCTION`, `BLOCKED_SUPPLY`, or `BLOCKED_LABEL`"

        Design: Corner/state_machines/customer_close_blocked_by_open_run_and_pending_state
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        run = quote_run(customer["id"], formula["id"], planned_units=1000)
        resp = api.close_customer(customer["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_STATE_INVALID)
        # once the run is terminal the same close succeeds
        get_success_data(api.cancel_run(run["id"], PLAN))
        closed = get_success_data(api.close_customer(customer["id"], FIN))
        assert closed["status"] == "CLOSED"

    def test_close_from_pending_credit_rejected(self, api):
        """PRD §3.1: "Closure from `ACTIVE` or `SUSPENDED` to `CLOSED` — again a
        `FinanceClerk` action — is refused with `ERR_CUSTOMER_STATE_INVALID`"

        Design: Corner/state_machines/customer_close_blocked_by_open_run_and_pending_state
        """
        customer = create_customer(approve=False)
        resp = api.close_customer(customer["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_STATE_INVALID)


class TestReactivationHysteresis:
    def test_reactivate_at_full_limit_rejected(self, api):
        """PRD §3.1: "The account must sit in `SUSPENDED`, and its
        `outstanding_balance_cents` must have fallen to no more than the floor of
        four-fifths of `credit_limit_cents`; otherwise the attempt is refused with
        `ERR_REACTIVATION_THRESHOLD_NOT_MET`."

        Design: Corner/state_machines/customer_reactivate_hysteresis_threshold
        """
        ctx = setup_completed_run(credit_limit_cents=149_400)
        customer_id = ctx["customer"]["id"]
        get_success_data(api.suspend_customer(customer_id, FIN))
        # outstanding is exactly the credit limit (149400): not enough headroom
        resp = api.reactivate_customer(customer_id, FIN)
        validate_error(resp, ApiErrorId.ERR_REACTIVATION_THRESHOLD_NOT_MET)

    def test_reactivate_at_eighty_percent_floor_succeeds(self, api):
        """PRD §3.1: "Paying the balance down to exactly the credit limit is not
        enough — the gate demands real headroom below it."

        Design: Corner/state_machines/customer_reactivate_hysteresis_threshold
        """
        ctx = setup_completed_run(credit_limit_cents=149_400)
        customer_id = ctx["customer"]["id"]
        get_success_data(api.suspend_customer(customer_id, FIN))
        # floor(149400 * 0.8) == 119520; pay the balance down to exactly that
        paid = get_success_data(api.post_payment(
            customer_id, {"amount_cents": 29_880}, FIN))
        assert paid["outstanding_balance_cents"] == 119_520
        reactivated = get_success_data(api.reactivate_customer(customer_id, FIN))
        assert reactivated["status"] == "ACTIVE"


class TestPaymentBounds:
    def _customer_with_outstanding(self):
        """Full pipeline through COMPLETED: outstanding == provisional 149400."""
        ctx = setup_completed_run()
        return ctx["customer"]["id"], ctx["run"]["id"]

    def test_payment_of_zero_rejected(self, api):
        """PRD §3.1: "the amount must be strictly greater than zero and no greater
        than the current `outstanding_balance_cents`, else the posting is refused
        with `ERR_PAYMENT_INVALID_AMOUNT`"

        Design: Corner/validations/payment_amount_bounds
        """
        customer_id, _ = self._customer_with_outstanding()
        resp = api.post_payment(customer_id, {"amount_cents": 0}, FIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_INVALID_AMOUNT)

    def test_payment_above_outstanding_rejected(self, api):
        """PRD §3.1: "the amount must be strictly greater than zero and no greater
        than the current `outstanding_balance_cents`, else the posting is refused
        with `ERR_PAYMENT_INVALID_AMOUNT`"

        Design: Corner/validations/payment_amount_bounds
        """
        customer_id, _ = self._customer_with_outstanding()
        resp = api.post_payment(customer_id, {"amount_cents": 149_401}, FIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_INVALID_AMOUNT)

    def test_payment_of_exact_balance_zeroes_it(self, api):
        """PRD §3.1: "a successful posting reduces the balance by exactly that
        amount."

        Design: Corner/validations/payment_amount_bounds
        """
        customer_id, _ = self._customer_with_outstanding()
        paid = get_success_data(api.post_payment(
            customer_id, {"amount_cents": 149_400}, FIN))
        assert paid["outstanding_balance_cents"] == 0
        # with nothing left outstanding, even one cent is too much
        resp = api.post_payment(customer_id, {"amount_cents": 1}, FIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_INVALID_AMOUNT)


class TestConfirmCustomerGate:
    def test_confirm_rejected_when_customer_suspended(self, api):
        """PRD §3.1: "A suspended customer is locked out of new commercial
        commitment: confirming a production run, placing a shipment order, and
        allocating a shipment order all require the customer to be `ACTIVE`, and
        each is refused with `ERR_CUSTOMER_NOT_ACTIVE` while the hold stands."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_customer_active
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        run = quote_run(customer["id"], formula["id"], planned_units=600)
        get_success_data(api.suspend_customer(customer["id"], FIN))
        resp = api.confirm_run(run["id"], PLAN)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)

    def test_confirm_after_reactivate_succeeds(self, api):
        """PRD §3.1: "A suspended customer is locked out of new commercial
        commitment: confirming a production run, placing a shipment order, and
        allocating a shipment order all require the customer to be `ACTIVE`, and
        each is refused with `ERR_CUSTOMER_NOT_ACTIVE` while the hold stands."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_customer_active
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        run = quote_run(customer["id"], formula["id"], planned_units=600)
        get_success_data(api.suspend_customer(customer["id"], FIN))
        resp = api.confirm_run(run["id"], PLAN)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)
        assert get_success_data(api.get_production_run(run["id"], PM))["production_status"] == "QUOTED"
        # hold released (zero outstanding is below the four-fifths floor)
        get_success_data(api.reactivate_customer(customer["id"], FIN))
        confirmed = get_success_data(api.confirm_run(run["id"], PLAN))
        assert confirmed["production_status"] == "CONFIRMED"


class TestConfirmValidationPriority:
    def test_state_error_beats_minimum_run_error(self, api):
        """PRD §2.6: "Every request is validated against a fixed pipeline of check
        categories, evaluated in the order below; when several checks would fail,
        the earliest category's error is the one returned." (state admissibility,
        category 5, precedes structural constraints such as the minimum run size,
        category 8.)

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_business_constraint
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        # planned 499 violates the 500-unit minimum AND the customer is SUSPENDED
        run = quote_run(customer["id"], formula["id"], planned_units=499)
        get_success_data(api.suspend_customer(customer["id"], FIN))
        resp = api.confirm_run(run["id"], PLAN)
        error = validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)
        assert resp.status_code == 409
        assert error["error_id"] != ApiErrorId.ERR_MINIMUM_RUN_NOT_MET

    def test_failed_confirm_leaves_run_quoted(self, api):
        """PRD §2.6: "Every request is validated against a fixed pipeline of check
        categories, evaluated in the order below; when several checks would fail,
        the earliest category's error is the one returned."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_business_constraint
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        run = quote_run(customer["id"], formula["id"], planned_units=499)
        get_success_data(api.suspend_customer(customer["id"], FIN))
        validate_error(api.confirm_run(run["id"], PLAN), ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE)
        run_after = get_success_data(api.get_production_run(run["id"], PM))
        assert run_after["production_status"] == "QUOTED"


class TestCreditSweepBoundary:
    def test_outstanding_equal_to_limit_does_not_suspend(self, api):
        """PRD §3.10: "The credit sweep suspends every `ACTIVE` customer whose
        `outstanding_balance_cents` is strictly greater than `credit_limit_cents`
        — a balance exactly equal to the limit does not suspend."

        Design: Difficulty/boundary_precision_check/credit_sweep_strictly_greater_boundary
        """
        # provisional invoice is 996 * 150 == 149400; set the limit to exactly that
        ctx = setup_completed_run(credit_limit_cents=149_400)
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], PM))
        assert customer["outstanding_balance_cents"] == 149_400
        ops = get_success_data(api.post_ops_run(PM))
        assert ops["customers_suspended_count"] == 0
        customer = get_success_data(api.get_customer(ctx["customer"]["id"], PM))
        assert customer["status"] == "ACTIVE"

    def test_outstanding_one_cent_over_limit_via_escrow_suspends(self, api):
        """PRD §3.10: "The credit sweep suspends every `ACTIVE` customer whose
        `outstanding_balance_cents` is strictly greater than `credit_limit_cents`"
        and §3.10: "raises `escrow_balance_cents` by the count times the
        customer's `pallet_deposit_cents`, and charges the same amount into the
        customer's `outstanding_balance_cents`."

        Design: Difficulty/boundary_precision_check/credit_sweep_strictly_greater_boundary
        """
        ctx = setup_completed_run(credit_limit_cents=149_400)
        customer_id = ctx["customer"]["id"]
        # ship 500 units (1 pallet * 1500 deposit) -> outstanding 150900 > 149400
        order = place_order(customer_id, ctx["formula"]["id"], units_requested=500)
        shipped = ship_allocated_order(order["id"])
        assert shipped["status"] == "SHIPPED"
        customer = get_success_data(api.get_customer(customer_id, PM))
        assert customer["outstanding_balance_cents"] == 150_900
        ops = get_success_data(api.post_ops_run(PM))
        assert ops["customers_suspended_count"] == 1
        customer = get_success_data(api.get_customer(customer_id, PM))
        assert customer["status"] == "SUSPENDED"
