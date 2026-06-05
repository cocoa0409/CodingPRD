"""State-machine corner cases: invalid transitions, terminal lockdown, suspend cascade."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_account, create_vehicle, create_transponder, create_plaza, credit_account,
    bind_transponder, record_transponder_read, record_plate_read, price,
    setup_priced_unsettled_plate_read,
    api_client, TEST_USERS, make_account_holder_headers,
)

OP = TEST_USERS["toll_operator_headers"]


def test_price_already_priced_returns_invalid_state(api):
    """PRD §3.2: "Any state transition requested against an account that is not in the
    required source state is rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "Pricing a `PENDING` transaction is a `TollOperator` action."

    Design: Corner/state_machines/price_already_priced_returns_invalid_state
    """
    account = create_account(holder_name="Ip")
    credit_account(account["id"], 5000)
    vehicle = create_vehicle(account["id"], plate_number="IP1")
    transponder = create_transponder(account["id"], "TP-IP")
    bind_transponder(account["id"], transponder["id"], vehicle["id"], vehicle["version"])
    plaza = create_plaza(base_rate_cents=400)
    txn = record_transponder_read(plaza["id"], transponder["id"], "2026-03-01T03:00:00Z",
                                  is_peak=False)
    price(txn["id"])
    res = api.price_toll_transaction(txn["id"], OP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    acct = validate_success(api.get_account(account["id"], OP), 200)
    # No second debit: 5000 - 400 = 4600
    assert acct["balance_cents"] == 4600, f"expected 4600, got {acct['balance_cents']}"


def test_contest_already_contested_invalid_state(api):
    """PRD §3.8: "The `AccountHolder` may contest an `ASSESSED` violation, supplying a
    free-text `dispute_reason`; this stores the reason and moves the violation from
    `ASSESSED` to `CONTESTED`."

    Design: Corner/state_machines/contest_already_contested_invalid_state
    """
    account, vehicle, plaza, txn = setup_priced_unsettled_plate_read(plate_number="CC1")
    viol = validate_success(api.create_violation({"toll_transaction_id": txn["id"]}, OP), 201)
    holder = make_account_holder_headers(account["id"])
    api.contest_violation(viol["id"], {"dispute_reason": "first"}, holder)
    res = api.contest_violation(viol["id"], {"dispute_reason": "second"}, holder)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_closed_account_terminal_lockdown(api):
    """PRD §3.2: "An operator may close an account only from `SUSPENDED` ... Closing
    moves the account to the terminal `CLOSED` state. Any state transition requested
    against an account that is not in the required source state is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/closed_account_terminal_lockdown
    """
    account = create_account(holder_name="Cl")
    api.suspend_account(account["id"], OP)
    api.close_account(account["id"], OP)
    res = api.reinstate_account(account["id"], OP)
    validate_error(res, "ERR_INVALID_STATE")


def test_suspend_account_deactivates_bound_transponders(api):
    """PRD §3.2: "Suspension carries a cascade: every `BOUND` transponder of the account
    is moved to `DEACTIVATED`, and each of those transponders' `ACTIVE` bindings is moved
    to `ENDED` with `effective_to` set to the moment of suspension."

    Design: Corner/state_machines/suspend_account_deactivates_bound_transponders
    """
    account = create_account(holder_name="Sd")
    vehicle = create_vehicle(account["id"], plate_number="SD1")
    transponder = create_transponder(account["id"], "TP-SD")
    binding = bind_transponder(account["id"], transponder["id"], vehicle["id"],
                               vehicle["version"])
    suspended = validate_success(api.suspend_account(account["id"], OP), 200)
    assert suspended["status"] == "SUSPENDED"
    tp_after = validate_success(api.get_transponder(transponder["id"], OP), 200)
    assert tp_after["status"] == "DEACTIVATED"
    bind_after = validate_success(api.get_transponder_binding(binding["id"], OP), 200)
    assert bind_after["status"] == "ENDED"
