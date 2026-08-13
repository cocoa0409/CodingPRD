"""Customer credit gating on charge loading and its priority against the
capacity check (PRD §2.9, §3.4, §3.5).

Note on derivation: the CREDIT_HOLD auto-transition is not reachable in a
uniquely-derivable way from the PRD (the §3.4 auto-flip presupposes a
balance above the limit, while §3.8 rejects any registration whose fee would
push the balance past the limit). The customer-status gate is therefore
exercised through CLOSED accounts, which §3.5 covers with the same error.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_charge_payload,
    setup_closed_customer,
    setup_customer,
    setup_cycle_complete_charge,
    setup_shop,
    validate_error,
    validate_success,
)

OP = TEST_USERS["plant_operator_headers"]
AR = TEST_USERS["accounts_receivable_headers"]


class TestChargeCreateGatedByCustomerStatus:
    def test_custom_treat_charge_rejected_for_closed_customer(self, api):
        """PRD §3.5: "And a custom-treat charge requires its customer account
        to be `ACTIVE`, failing with `ERR_CUSTOMER_CREDIT_HOLD` (402)
        otherwise."
        PRD §3.4: "Closing an account is permitted only when
        `outstanding_balance_cents` is exactly zero ... `CLOSED` is terminal."

        Design: Difficulty/cross_entity_state_dependency/charge_create_gated_by_customer_status
        """
        shop = setup_shop()
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        customer = setup_closed_customer(customer_name="Closed Co",
                                         credit_limit_cents=100000000)
        assert customer["status"] == "CLOSED"

        resp = api.load_charge(
            plant_id, cyl_id,
            create_charge_payload(customer_id=customer["id"],
                                  ownership_type="CUSTOM_TREAT", volume_mbf=1.0),
            OP)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value)

    def test_custom_treat_charge_accepted_for_active_customer(self, api):
        """PRD §3.5: "And a custom-treat charge requires its customer account
        to be `ACTIVE`, failing with `ERR_CUSTOMER_CREDIT_HOLD` (402)
        otherwise."
        PRD §3.4: "the account starts `ACTIVE` with an
        `outstanding_balance_cents` of zero."

        Design: Difficulty/cross_entity_state_dependency/charge_create_gated_by_customer_status
        """
        shop = setup_shop()
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        customer = setup_customer()
        assert customer["status"] == "ACTIVE"

        resp = api.load_charge(
            plant_id, cyl_id,
            create_charge_payload(customer_id=customer["id"],
                                  ownership_type="CUSTOM_TREAT", volume_mbf=1.0),
            OP)
        charge = validate_success(resp, 201)
        assert charge["status"] == "IN_CYLINDER"
        assert charge["is_custom_treat"] is True
        assert charge["customer_id"] == customer["id"]


class TestCapacityVersusFiscalPriority:
    def test_capacity_error_precedes_customer_credit_error(self, api):
        """PRD §2.9: "The ordered cascade itself then runs as follows: ... 6.
        Cylinder capacity on charge loading — `ERR_CYLINDER_CAPACITY_EXCEEDED`
        (409). ... 17. Customer credit standing — `ERR_CUSTOMER_CREDIT_HOLD`
        (402)."
        PRD §2.9: "The ordering is observable."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_priority_on_charge_create
        """
        shop = setup_shop(max_volume_mbf=25.0)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]

        # 20 mbf already physically present (CYCLE_COMPLETE); cylinder IDLE.
        setup_cycle_complete_charge(shop, volume_mbf=20.0)
        validate_success(api.mark_cleaned(plant_id, cyl_id, OP))

        customer = setup_closed_customer(credit_limit_cents=100000000)

        # 20 + 10 = 30 > 25 (capacity fails) AND the customer is CLOSED
        # (fiscal fails). Capacity is earlier in the cascade.
        resp = api.load_charge(
            plant_id, cyl_id,
            create_charge_payload(customer_id=customer["id"],
                                  ownership_type="CUSTOM_TREAT", volume_mbf=10.0),
            OP)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_CAPACITY_EXCEEDED.value)

    def test_customer_credit_error_surfaces_when_capacity_passes(self, api):
        """PRD §3.5: "And a custom-treat charge requires its customer account
        to be `ACTIVE`, failing with `ERR_CUSTOMER_CREDIT_HOLD` (402)
        otherwise."
        PRD §2.9: "17. Customer credit standing — `ERR_CUSTOMER_CREDIT_HOLD`
        (402)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_priority_on_charge_create
        """
        shop = setup_shop(max_volume_mbf=25.0)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        customer = setup_closed_customer(credit_limit_cents=100000000)

        # Empty cylinder: capacity is fine; only the fiscal gate fails.
        resp = api.load_charge(
            plant_id, cyl_id,
            create_charge_payload(customer_id=customer["id"],
                                  ownership_type="CUSTOM_TREAT", volume_mbf=5.0),
            OP)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value)
