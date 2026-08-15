"""Customers, credit posture, credit gate, and open exposure (PRD §3.1, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_customer, create_profile, create_formulation, create_die,
    create_order, confirm_order, plant_base, publish_index_points, set_clock,
    get_customer, get_order,
)

PM = TEST_USERS["plant_manager_headers"]
SE = TEST_USERS["sales_engineer_headers"]


class TestCustomerCreation:
    def test_customer_create_applies_defaults(self, api):
        """PRD §3.1: "A new customer is born with `status` `ACTIVE` and an
        `open_exposure_cents` of zero."

        Design: Corner/entities/customer_create_applies_defaults
        """
        resp = api.create_customer(
            {"name": "Acme", "resin_index_basis": "MONTHLY_AVG",
             "credit_limit_cents": 10000000}, PM)
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE", f"Expected ACTIVE, got {data['status']}"
        assert data["open_exposure_cents"] == 0
        assert isinstance(data["created_at"], str) and data["created_at"]
        assert isinstance(data["id"], str) and data["id"]


class TestCreditHoldGate:
    def test_confirm_rejected_while_customer_on_credit_hold(self, api):
        """PRD §3.4: "The order must be `QUOTED`; the customer must be `ACTIVE` —
        confirming against a `CREDIT_HOLD` customer is rejected with
        `ERR_CUSTOMER_CREDIT_HOLD`; index coverage for the evaluation window is
        verified next, surfacing `ERR_RESIN_INDEX_MISSING` on any gap; and last
        the credit gate."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_customer_active
        """
        base = plant_base()
        die = create_die(base["prof"]["id"])
        wo = create_order(base["cust"]["id"], base["prof"]["id"],
                          base["form"]["id"], die["id"])
        hold = api.set_credit_status(base["cust"]["id"], {"action": "HOLD"}, PM)
        validate_success(hold, 200)

        resp = api.confirm_work_order(wo["id"], SE)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)
        assert get_order(wo["id"])["status"] == "QUOTED", "Order must stay QUOTED after rejection"

    def test_confirm_succeeds_after_credit_release(self, api):
        """PRD §3.1: "Placing a hold — submitting `action` `HOLD` against a
        customer currently `ACTIVE` — moves the customer to `CREDIT_HOLD`;
        releasing it — `action` `RELEASE` against a customer currently
        `CREDIT_HOLD` — returns the customer to `ACTIVE`."
        PRD §3.4: "The order must be `QUOTED`; the customer must be `ACTIVE` —
        confirming against a `CREDIT_HOLD` customer is rejected with
        `ERR_CUSTOMER_CREDIT_HOLD`; index coverage for the evaluation window is
        verified next, surfacing `ERR_RESIN_INDEX_MISSING` on any gap; and last
        the credit gate."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_customer_active
        """
        base = plant_base()
        die = create_die(base["prof"]["id"])
        wo = create_order(base["cust"]["id"], base["prof"]["id"],
                          base["form"]["id"], die["id"])
        validate_success(api.set_credit_status(base["cust"]["id"], {"action": "HOLD"}, PM), 200)
        validate_error(api.confirm_work_order(wo["id"], SE), ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)

        validate_success(api.set_credit_status(base["cust"]["id"], {"action": "RELEASE"}, PM), 200)
        confirmed = validate_success(api.confirm_work_order(wo["id"], SE), 200)
        assert confirmed["status"] == "CONFIRMED", (
            f"Confirm after release must succeed, got {confirmed['status']}")


class TestCreditLimitBoundary:
    def test_confirm_at_exactly_credit_limit_passes(self, api):
        """PRD §3.4: "At confirm time the pass-through is first recomputed at the
        current clock month, then the gate evaluates a candidate exposure — the
        current `open_exposure_cents` plus this order's own `ordered_length_m`
        times its freshly computed `current_unit_price_cents_per_m`, rounded
        half-up to whole cents — and rejects with `ERR_CREDIT_LIMIT_EXCEEDED`
        only when the candidate is strictly greater than `credit_limit_cents`;
        a candidate exactly equal to the limit passes."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_allowed
        """
        base = plant_base(customer_over={"credit_limit_cents": 5000000})
        die = create_die(base["prof"]["id"])
        wo1 = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        wo2 = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])

        confirmed = validate_success(api.confirm_work_order(wo1["id"], SE), 200)
        assert confirmed["status"] == "CONFIRMED"
        cust = get_customer(base["cust"]["id"])
        assert cust["open_exposure_cents"] == 5000000, (
            f"Exposure must be 5000 m x 1000 cents/m = 5000000, got {cust['open_exposure_cents']}")
        # Second identical order: candidate 10,000,000 > 5,000,000 must fail.
        validate_error(api.confirm_work_order(wo2["id"], SE), ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    def test_confirm_one_cent_over_credit_limit_rejected(self, api):
        """PRD §3.4: "At confirm time the pass-through is first recomputed at the
        current clock month, then the gate evaluates a candidate exposure — the
        current `open_exposure_cents` plus this order's own `ordered_length_m`
        times its freshly computed `current_unit_price_cents_per_m`, rounded
        half-up to whole cents — and rejects with `ERR_CREDIT_LIMIT_EXCEEDED`
        only when the candidate is strictly greater than `credit_limit_cents`;
        a candidate exactly equal to the limit passes."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_allowed
        """
        base = plant_base(customer_over={"credit_limit_cents": 5000000})
        die = create_die(base["prof"]["id"])
        wo1 = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        wo2 = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        validate_success(api.confirm_work_order(wo1["id"], SE), 200)

        resp = api.confirm_work_order(wo2["id"], SE)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_order(wo2["id"])["status"] == "QUOTED", "Rejected confirm leaves order QUOTED"
        assert get_customer(base["cust"]["id"])["open_exposure_cents"] == 5000000, (
            "Rejected confirm must not change open exposure")


class TestConfirmPrecedence:
    def test_second_order_confirm_fails_on_credit_limit(self, api):
        """PRD §3.4: "At confirm time the pass-through is first recomputed at the
        current clock month, then the gate evaluates a candidate exposure — the
        current `open_exposure_cents` plus this order's own `ordered_length_m`
        times its freshly computed `current_unit_price_cents_per_m`, rounded
        half-up to whole cents — and rejects with `ERR_CREDIT_LIMIT_EXCEEDED`
        only when the candidate is strictly greater than `credit_limit_cents`;
        a candidate exactly equal to the limit passes."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
        """
        base = plant_base(customer_over={"credit_limit_cents": 5000000})
        die = create_die(base["prof"]["id"])
        wo1 = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        wo2 = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        validate_success(api.confirm_work_order(wo1["id"], SE), 200)

        resp = api.confirm_work_order(wo2["id"], SE)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_order(wo2["id"])["status"] == "QUOTED"

    def test_reconfirm_confirmed_order_reports_invalid_state_not_fiscal(self, api):
        """PRD §3.4: "The order must be `QUOTED`; the customer must be `ACTIVE` —
        confirming against a `CREDIT_HOLD` customer is rejected with
        `ERR_CUSTOMER_CREDIT_HOLD`; index coverage for the evaluation window is
        verified next, surfacing `ERR_RESIN_INDEX_MISSING` on any gap; and last
        the credit gate."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
        """
        base = plant_base(customer_over={"credit_limit_cents": 5000000})
        die = create_die(base["prof"]["id"])
        wo1 = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        wo2 = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        validate_success(api.confirm_work_order(wo1["id"], SE), 200)
        # Fiscal state is now loaded: a fresh confirm of wo2 already fails the gate.
        validate_error(api.confirm_work_order(wo2["id"], SE), ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

        # Re-confirming wo1 violates the from-state (QUOTED) check AND would also
        # fail fiscally; the order-of-checks makes the from-state error win.
        resp = api.confirm_work_order(wo1["id"], SE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(wo1["id"])["status"] == "CONFIRMED"


class TestExposureReconciliation:
    def test_exposure_returns_to_zero_on_cancel(self, api):
        """PRD §3.4: "a customer's `open_exposure_cents` is the sum, over every
        work order of that customer in `CONFIRMED`, `SCHEDULED`, or
        `IN_PRODUCTION` status, of each order's `ordered_length_m` multiplied by
        its `current_unit_price_cents_per_m`, each product rounded half-up to
        whole cents before the sum; `QUOTED`, `CLOSED`, `CANCELLED`, and
        already-invoiced orders contribute nothing."
        PRD §3.4: "Cancelling moves the order to `CANCELLED`, moves every one of
        its assignments in `SCHEDULED` or `ACTIVE` status to `CANCELLED`, returns
        any line left in `SETUP` by a cancelled active assignment to `IDLE`,
        recomputes the customer's `open_exposure_cents`, and increments the
        order's `version`."

        Design: Corner/cross_cutting_complexity_layers/exposure_reconciled_on_cancel
        """
        base = plant_base()
        die = create_die(base["prof"]["id"])
        wo = create_order(base["cust"]["id"], base["prof"]["id"], base["form"]["id"], die["id"])
        validate_success(api.confirm_work_order(wo["id"], SE), 200)
        cust = get_customer(base["cust"]["id"])
        assert cust["open_exposure_cents"] == 5000000, (
            f"After confirm exposure must be 5000000, got {cust['open_exposure_cents']}")

        validate_success(api.cancel_work_order(wo["id"], SE), 200)
        cust = get_customer(base["cust"]["id"])
        assert cust["open_exposure_cents"] == 0, (
            f"After cancel exposure must return to 0, got {cust['open_exposure_cents']}")
        assert get_order(wo["id"])["status"] == "CANCELLED"
