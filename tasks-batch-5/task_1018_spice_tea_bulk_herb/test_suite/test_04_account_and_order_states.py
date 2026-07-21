"""Account ACTIVE<->SUSPENDED cycle and invalid state-transition rejections."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_account, new_order, setup_priced_order,
    TEST_USERS,
)

SALES = TEST_USERS["sales_headers"]


# ---- non_linear_state_machine / wholesale_account_active_suspended_cycle ----

def test_reinstate_returns_account_to_active(api):
    """PRD §3.5: "A `SalesAgent` suspending an account moves it `ACTIVE → SUSPENDED`, after
    which any attempt to confirm a new order against it is blocked with
    `ERR_ACCOUNT_SUSPENDED`; reinstating it moves it `SUSPENDED → ACTIVE` with no further
    effect."

    Design: Difficulty/non_linear_state_machine/wholesale_account_active_suspended_cycle
    """
    account = new_account(api)
    validate_success(api.suspend_account(account["id"], SALES))
    reinstated = validate_success(api.reinstate_account(account["id"], SALES))
    assert reinstated["status"] == "ACTIVE", reinstated["status"]


def test_account_cycles_active_suspended_active(api):
    """PRD §3.5: "An account may cycle between `ACTIVE` and `SUSPENDED`."
    PRD §3.5: "A `SalesAgent` suspending an account moves it `ACTIVE → SUSPENDED`, after
    which any attempt to confirm a new order against it is blocked with
    `ERR_ACCOUNT_SUSPENDED`; reinstating it moves it `SUSPENDED → ACTIVE` with no further
    effect."

    Design: Difficulty/non_linear_state_machine/wholesale_account_active_suspended_cycle
    """
    account = new_account(api)
    suspended = validate_success(api.suspend_account(account["id"], SALES))
    assert suspended["status"] == "SUSPENDED", suspended["status"]
    reinstated = validate_success(api.reinstate_account(account["id"], SALES))
    assert reinstated["status"] == "ACTIVE", reinstated["status"]


# ---- Corner / state_machines ----

def test_ship_draft_order_rejected_invalid_state(api):
    """PRD §3.8: "Shipping is a `SalesAgent` action that advances a packed order
    `PACKED → SHIPPED`; it makes the allocations permanent, leaving each lot's grams
    decremented, and has no other effect."

    Design: Corner/state_machines/corner_ship_from_draft_returns_invalid_state
    """
    account = new_account(api)
    order = validate_success(api.create_order({"wholesale_account_id": account["id"]}, SALES), 201)
    resp = api.ship_order(order["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_price_already_priced_order_rejected_invalid_state(api):
    """PRD §3.6: "Pricing an order advances it `DRAFT → PRICED` and requires at least one
    line, with every line's product still `ACTIVE`."

    Design: Corner/state_machines/corner_price_twice_returns_invalid_state
    """
    ctx = setup_priced_order(api)
    resp = api.price_order(ctx["order"]["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reinstate_active_account_rejected_invalid_state(api):
    """PRD §3.5: "reinstating it moves it `SUSPENDED → ACTIVE` with no further effect.
    Neither transition has preconditions beyond the account being in the opposite state."

    Design: Corner/state_machines/corner_reinstate_active_account_returns_invalid_state
    """
    account = new_account(api)
    resp = api.reinstate_account(account["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
