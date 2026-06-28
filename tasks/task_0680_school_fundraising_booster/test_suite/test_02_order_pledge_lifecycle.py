"""Parallel order dimensions and the cyclic pledge revision loop.

Covers difficulty queue A rule: non_linear_state_machine.
"""
import pytest
from test_helpers import (
    validate_success,
    setup_active_catalog, setup_active_pledge,
    place_simple_order, create_pledge,
    assert_order, assert_pledge,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]


# ─── non_linear_state_machine / order_parallel_payment_and_fulfillment_independent

class TestOrderParallelDimensions:
    def test_pay_then_confirm_advances_both_axes_independently(self, api, admin_headers):
        """PRD §3.4: "An order carries two **independent** state dimensions. The
        first is `payment_status`, running `PENDING → PAID → REFUNDED`. The
        second is `fulfillment_status`, running `PLACED → CONFIRMED → DELIVERED`,
        with `CANCELLED` reachable from `PLACED` or `CONFIRMED`."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_independent
        """
        camp, seller, product = setup_active_catalog()
        order = place_simple_order(camp["id"], seller["id"], product["id"], 5)
        assert order["payment_status"] == "PENDING"
        assert order["fulfillment_status"] == "PLACED"

        paid = validate_success(api.pay_order(order["id"], admin_headers), 200)
        # PRD §3.4: paying moves payment PENDING->PAID; fulfillment is independent.
        assert paid["payment_status"] == "PAID"
        assert paid["fulfillment_status"] == "PLACED", \
            "fulfillment must stay PLACED after paying (independent dimension)"

        confirmed = validate_success(api.confirm_order(order["id"], admin_headers), 200)
        assert_order(confirmed)
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        assert confirmed["payment_status"] == "PAID", \
            "payment must stay PAID after confirming (independent dimension)"

    def test_pay_does_not_change_fulfillment(self, api, admin_headers):
        """PRD §3.4: "Paying an order moves `payment_status` from `PENDING` to
        `PAID`."

        PRD §3.4: "confirming an order moves `fulfillment_status` from
        `PLACED` to `CONFIRMED`; it is permitted only when the campaign is
        `ACTIVE` and the order is already `PAID`"

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_independent
        """
        camp, seller, product = setup_active_catalog()
        order = place_simple_order(camp["id"], seller["id"], product["id"], 3)
        paid = validate_success(api.pay_order(order["id"], admin_headers), 200)
        assert paid["payment_status"] == "PAID"
        assert paid["fulfillment_status"] == "PLACED"


# ─── non_linear_state_machine / pledge_record_revise_cycle ─────────────────

class TestPledgeRevisionLoop:
    def test_revise_returns_to_promised_and_resets_units(self, api, admin_headers):
        """PRD §3.5: "Revising a pledge moves it from `RECORDED` back to
        `PROMISED` while the campaign is `ACTIVE`, resetting `units_recorded`
        to 0 and recomputing `pledged_amount_cents`; this record-and-revise
        loop may repeat any number of times."

        Design: Difficulty/non_linear_state_machine/pledge_record_revise_cycle
        """
        camp, seller = setup_active_pledge()
        pledge = create_pledge(camp["id"], seller["id"], per_unit_cents=250, flat_cents=0)
        validate_success(api.record_pledge(pledge["id"], {"units_recorded": 30}, admin_headers), 200)

        revised = validate_success(api.revise_pledge(pledge["id"], admin_headers), 200)
        assert_pledge(revised)
        assert revised["status"] == "PROMISED", "revise returns the pledge to PROMISED"
        assert revised["units_recorded"] == 0, "revise resets units_recorded to 0"

    def test_second_record_after_revise_sets_new_units_and_amount(self, api, admin_headers):
        """PRD §3.5: "Recording a pledge moves it from `PROMISED` to `RECORDED`
        ... Recording takes the performed `units_recorded` from the request
        and recomputes `pledged_amount_cents` accordingly."

        PRD §3.5: "The raw amount is the `flat_cents` plus the
        `per_unit_cents` multiplied by `units_recorded`."

        Design: Difficulty/non_linear_state_machine/pledge_record_revise_cycle
        """
        camp, seller = setup_active_pledge()
        pledge = create_pledge(camp["id"], seller["id"], per_unit_cents=250, flat_cents=0)
        validate_success(api.record_pledge(pledge["id"], {"units_recorded": 30}, admin_headers), 200)
        validate_success(api.revise_pledge(pledge["id"], admin_headers), 200)

        re_recorded = validate_success(
            api.record_pledge(pledge["id"], {"units_recorded": 12}, admin_headers), 200)
        assert re_recorded["status"] == "RECORDED", "second record returns to RECORDED"
        assert re_recorded["units_recorded"] == 12, "second record sets units_recorded to 12"
        assert re_recorded["pledged_amount_cents"] == 3000, \
            f"0 + 250*12 = 3000, got {re_recorded['pledged_amount_cents']}"
