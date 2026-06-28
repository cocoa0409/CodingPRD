"""Breadth tests over state-machine transitions: invalid transitions, precondition
enforcement, initial states, terminal lockdown, and side-effect cascades across
layaway, agreement, consignment, trade-in, and special-order lifecycles.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    make_customer_headers,
    create_customer,
    setup_open_layaway, setup_customer_and_active_agreement, setup_rto_with_n_paid_months,
    setup_listed_consignment, setup_offered_trade_in, setup_arrived_special_order,
    read_agreement, advance_cycles,
    ApiErrorId,
    buyout_payload,
    TEST_USERS,
)
import test_helpers.factories as f

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ===========================================================================
# Corner / state_machines
# ===========================================================================
def test_cancel_already_cancelled_layaway_returns_invalid_state(api):
    """PRD §3.5: "any transition attempted from a state that does not permit it is
    rejected with ERR_INVALID_STATE." (CANCELLED is terminal — see "COMPLETED and
    CANCELLED are terminal.")

    Design: Corner/state_machines/cancel_already_cancelled_layaway_returns_invalid_state
    """
    customer, plan, unit = setup_open_layaway(deposit_cents=5000)
    validate_success(api.cancel_layaway(plan["id"], SA), 200)
    resp = api.cancel_layaway(plan["id"], SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_layaway(plan["id"], SA), 200)
    assert after["status"] == "CANCELLED"


def test_complete_unpaid_layaway_returns_layaway_not_paid(api):
    """PRD §3.5: "Completing a layaway is permitted only when the plan is fully paid
    — remaining_cents must equal 0 — otherwise the completion is rejected with
    ERR_LAYAWAY_NOT_PAID."

    Design: Corner/state_machines/complete_unpaid_layaway_returns_layaway_not_paid
    """
    customer, plan, unit = setup_open_layaway(list_price_cents=60000, deposit_cents=10000)
    resp = api.complete_layaway(plan["id"], SA)
    validate_error(resp, ApiErrorId.ERR_LAYAWAY_NOT_PAID.value)
    after = validate_success(api.get_layaway(plan["id"], SA), 200)
    assert after["status"] == "OPEN"
    unit_after = validate_success(api.get_unit(unit["id"], SA), 200)
    assert unit_after["status"] == "ON_LAYAWAY"


def test_buyout_on_plain_rental_returns_plan_not_rent_to_own(api):
    """PRD §3.4: "Buyout is restricted to agreements whose `plan` is `RENT_TO_OWN`;
    attempting it on a plain `RENTAL` agreement is rejected with
    `ERR_PLAN_NOT_RENT_TO_OWN`."

    Design: Corner/state_machines/buyout_on_plain_rental_returns_plan_not_rent_to_own
    """
    customer, agreement, unit = setup_customer_and_active_agreement(plan="RENTAL")
    av = read_agreement(agreement["id"])["version"]
    resp = api.buyout_agreement(agreement["id"], buyout_payload(65000, av),
                                make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_RENT_TO_OWN.value)
    after = read_agreement(agreement["id"])
    assert after["status"] == "ACTIVE"


def test_return_with_outstanding_late_fees_blocked(api):
    """PRD §3.4: "but only if there is no outstanding late-fee balance — if
    `late_fee_balance_cents` is greater than 0 the return is blocked with
    `ERR_OUTSTANDING_LATE_FEES`."

    Design: Corner/state_machines/return_with_outstanding_late_fees_blocked
    """
    customer, agreement, unit = setup_customer_and_active_agreement(plan="RENT_TO_OWN")
    # one unpaid advance posts a 1500 late fee (still ACTIVE after a single miss)
    advance_cycles(agreement["id"], [1])
    resp = api.return_agreement(agreement["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_LATE_FEES.value)
    after = read_agreement(agreement["id"])
    assert after["status"] == "ACTIVE"


def test_initial_states_on_create(api):
    """PRD §3.7: "The trade-in begins `OFFERED` at `version` 1 with the computed
    `offer_cents`"

    Design: Corner/state_machines/initial_states_on_create
    """
    customer, trade_in = setup_offered_trade_in(condition="USED", appraised_value_cents=10000)
    assert trade_in["status"] == "OFFERED"
    assert trade_in["version"] == 1


def test_terminal_state_lockdown_bought_out_cannot_return(api):
    """PRD §3.3: "`BOUGHT_OUT`, `RETURNED`, and `REPOSSESSED` are the three terminal
    outcomes of an agreement."
    PRD §3.4: "A `Customer` or `SalesAssociate` returns the unit on an `ACTIVE`
    agreement"

    Design: Corner/state_machines/terminal_state_lockdown_bought_out_cannot_return
    """
    customer, agreement, unit = setup_rto_with_n_paid_months(
        num_months=3, list_price_cents=120000, monthly_rent_cents=10000, equity_rate_pct=0.50,
    )
    cust_headers = make_customer_headers(customer["id"])
    av = read_agreement(agreement["id"], customer["id"])["version"]
    bought = validate_success(api.buyout_agreement(agreement["id"], buyout_payload(110000, av), cust_headers), 200)
    assert bought["status"] == "BOUGHT_OUT"
    resp = api.return_agreement(agreement["id"], cust_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = read_agreement(agreement["id"], customer["id"])
    assert after["status"] == "BOUGHT_OUT"


def test_consignment_withdraw_retires_unit_cascade(api):
    """PRD §3.7: "Withdrawing a listed consignment instead transitions it
    `LISTED → WITHDRAWN` and cascades the linked unit `CONSIGNED → RETIRED`"

    Design: Corner/state_machines/consignment_withdraw_retires_unit_cascade
    """
    consignor, listing = setup_listed_consignment(ask_price_cents=80000)
    units, _ = validate_paginated(
        api.list_units(SA, params={"consignment_listing_id": listing["id"]})
    )
    assert len(units) == 1
    unit_id = units[0]["id"]
    withdrawn = validate_success(api.withdraw_consignment(listing["id"], SA), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    unit_after = validate_success(api.get_unit(unit_id, SA), 200)
    assert unit_after["status"] == "RETIRED"


def test_trade_in_accept_mints_unit_and_credits(api):
    """PRD §3.7: "Acceptance transitions the trade-in `OFFERED → ACCEPTED`, mints a
    new `InventoryUnit` in the `AVAILABLE` state whose `source_kind` is `TRADE_IN`
    and whose `acquisition_cost_cents` equals the offer, records that unit's id in the
    trade-in's `resulting_unit_id`, and adds the offer to the customer's
    `store_credit_cents`"
    PRD §3.7: "the fraction is 0.60 for `NEW`, 0.50 for `USED`, and 0.70 for `VINTAGE`"

    Design: Corner/state_machines/trade_in_accept_mints_unit_and_credits
    """
    customer, trade_in = setup_offered_trade_in(condition="VINTAGE", appraised_value_cents=200000)
    # offer = floor(200000 * 0.70) = 140000
    assert trade_in["offer_cents"] == 140000
    accepted = validate_success(api.accept_trade_in(trade_in["id"], SM), 200)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["offer_cents"] == 140000
    assert accepted["resulting_unit_id"] is not None
    minted = validate_success(api.get_unit(accepted["resulting_unit_id"], SM), 200)
    assert minted["status"] == "AVAILABLE"
    cust = validate_success(api.get_customer(customer["id"], SM), 200)
    assert cust["store_credit_cents"] == 140000


def test_special_order_full_lifecycle_to_fulfilled(api):
    """PRD §3.8: "Fulfilling the arrived order hands the unit to the customer: the
    order moves `ARRIVED → FULFILLED` and the unit cascades `RESERVED → SOLD`."

    Design: Corner/state_machines/special_order_full_lifecycle_to_fulfilled
    """
    customer, order = setup_arrived_special_order(quoted_price_cents=200000, deposit_amount=50000)
    assert order["status"] == "ARRIVED"
    fulfilled = validate_success(api.fulfill_special_order(order["id"], SA), 200)
    assert fulfilled["status"] == "FULFILLED"
    unit_after = validate_success(api.get_unit(order["fulfilled_unit_id"], SA), 200)
    assert unit_after["status"] == "SOLD"
