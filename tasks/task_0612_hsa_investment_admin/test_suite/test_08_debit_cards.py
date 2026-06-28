"""Debit card lifecycle: the ACTIVE<->SUSPENDED cycle and the CLOSED terminal state."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
)
from test_helpers.fixtures import (
    ADMIN, setup_active_account, issue_card, issue_and_activate_card,
)
from test_helpers.test_users import make_accountholder_headers
from test_helpers.api_client import api_client

ADMIN_HDR = ADMIN


# ── debitcard_cyclic_active_suspended (Difficulty/non_linear_state_machine) ──

def test_card_activate_suspend_activate_cycle(api):
    """PRD §3.6: "Suspending a card is permitted only from `ACTIVE` (else
    `ERR_INVALID_STATE`) and moves it to `SUSPENDED`; the card can be reactivated later,
    so `ACTIVE` and `SUSPENDED` cycle freely."

    activate -> suspend -> activate returns the card to ACTIVE.

    Design: Difficulty/non_linear_state_machine/debitcard_cyclic_active_suspended
    """
    account, holder = setup_active_account()
    hdr = make_accountholder_headers(holder["id"])
    card = issue_and_activate_card(account["id"], holder["id"], "4242")
    assert card["status"] == "ACTIVE"
    suspended = validate_success(api.suspend_card(account["id"], card["id"], hdr), 200)
    assert suspended["status"] == "SUSPENDED"
    reactivated = validate_success(api.activate_card(account["id"], card["id"], hdr), 200)
    assert reactivated["status"] == "ACTIVE"


def test_card_version_increments_each_hop(api):
    """PRD §2.4: "`version`, an integer that starts at creation and increments by one on
    each mutation."

    Each suspend/activate hop is a mutation that increments the card's version.

    Design: Difficulty/non_linear_state_machine/debitcard_cyclic_active_suspended
    """
    account, holder = setup_active_account()
    hdr = make_accountholder_headers(holder["id"])
    card = issue_and_activate_card(account["id"], holder["id"], "4242")
    v_active = card["version"]
    suspended = validate_success(api.suspend_card(account["id"], card["id"], hdr), 200)
    assert suspended["version"] > v_active
    reactivated = validate_success(api.activate_card(account["id"], card["id"], hdr), 200)
    assert reactivated["version"] > suspended["version"]
    assert reactivated["status"] == "ACTIVE"


# ── card_closed_terminal_lockdown_rejects_activate (Corner/state_machines) ───

def test_activate_closed_card_rejected(api):
    """PRD §3.6: "Closing a card moves it to `CLOSED` from either `ACTIVE` or `SUSPENDED`
    and is terminal."
    PRD §3.6: "an activation attempt from a state other than `ISSUED` or `SUSPENDED`, or
    against a non-active account from `ISSUED`, is rejected with `ERR_INVALID_STATE`."

    A CLOSED card cannot be activated.

    Design: Corner/state_machines/card_closed_terminal_lockdown_rejects_activate
    """
    account, holder = setup_active_account()
    hdr = make_accountholder_headers(holder["id"])
    # PRD §3.6: a card is closed only from ACTIVE or SUSPENDED. Reach CLOSED via
    # the legal path issue -> activate -> close, then attempt to re-activate.
    card = issue_and_activate_card(account["id"], holder["id"], "7777")
    validate_success(api.close_card(account["id"], card["id"], hdr), 200)
    res = api.activate_card(account["id"], card["id"], hdr)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    cards = validate_success(api.list_cards(account["id"], ADMIN_HDR), 200)
    target = next(c for c in cards if c["id"] == card["id"])
    assert target["status"] == "CLOSED"
