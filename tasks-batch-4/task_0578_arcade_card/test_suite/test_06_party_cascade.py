"""Confirm/cancel cascades: wristband + card provisioning, bonus grant/clawback,
liability conservation, and terminal/invalid-state guards."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import (
    setup_confirmed_booking, setup_completed_booking, revert_booking,
    get_card, get_card_ledger,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
CASHIER = TEST_USERS["cashier_headers"]


# --- Difficulty: confirm_cascade_wristband_card_ledger ---
def test_confirm_provisions_wristbands_linked_to_cards(api):
    """PRD §3.5: "For each of the `guest_count` guests, the system creates a `Wristband` in
    `ISSUED` status linked to this booking. Each new wristband in turn provisions a fresh
    `GameCard` in `ACTIVE` status and links the wristband's `card_id` to it."

    Design: Difficulty/transitive_cascade/confirm_cascade_wristband_card_ledger
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    wristbands = ctx["wristbands"]
    assert len(wristbands) == 2
    assert all(w["card_id"] is not None for w in wristbands)
    assert all(w["status"] == "ISSUED" for w in wristbands)


def test_confirm_grants_bonus_chips_and_appends_ledger_entry(api):
    """PRD §3.5: "Each provisioned card is then granted the package's `included_chip_cents` as
    promotional chips: a `BONUS_GRANT` ledger entry is appended with a bonus delta equal to
    `included_chip_cents`, and the card's `bonus_chip_balance_cents` grows by that amount."

    Design: Difficulty/transitive_cascade/confirm_cascade_wristband_card_ledger
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    card0 = ctx["card_ids"][0]
    assert get_card(api, card0)["bonus_chip_balance_cents"] == 1_000
    ledger = get_card_ledger(api, card0)
    grants = [e for e in ledger if e["entry_type"] == "BONUS_GRANT"]
    assert any(e["bonus_delta_cents"] == 1_000 for e in grants)


# --- Difficulty: cancel_cascade_void_clawback_ledger ---
def test_cancel_voids_wristband_and_claws_back_bonus(api):
    """PRD §3.6: "Cancelling a `CONFIRMED` or `CHECKED_IN` booking runs the same compensation
    as a revert: the room window reservation is released, every wristband of the booking is set
    to `VOID`, and each voided wristband's linked card has its promotional grant clawed back
    through a `BONUS_CLAWBACK` ledger entry with a bonus delta equal to the negative of
    `included_chip_cents`, decreasing that card's `bonus_chip_balance_cents`."

    Design: Difficulty/transitive_cascade/cancel_cascade_void_clawback_ledger
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    bid = ctx["booking"]["id"]
    w0 = ctx["wristbands"][0]
    card0 = w0["card_id"]
    validate_success(api.cancel_party_booking(bid, COORDINATOR))
    w0_now = validate_success(api.get_wristband(w0["id"], CASHIER))
    assert w0_now["status"] == "VOID"
    assert get_card(api, card0)["bonus_chip_balance_cents"] == 0


def test_cancel_appends_bonus_clawback_ledger_entry(api):
    """PRD §3.6: "each voided wristband's linked card has its promotional grant clawed back
    through a `BONUS_CLAWBACK` ledger entry with a bonus delta equal to the negative of
    `included_chip_cents`".

    Design: Difficulty/transitive_cascade/cancel_cascade_void_clawback_ledger
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    bid = ctx["booking"]["id"]
    card0 = ctx["card_ids"][0]
    validate_success(api.cancel_party_booking(bid, COORDINATOR))
    ledger = get_card_ledger(api, card0)
    clawbacks = [e for e in ledger if e["entry_type"] == "BONUS_CLAWBACK"]
    assert any(e["bonus_delta_cents"] == -1_000 for e in clawbacks)


# --- Difficulty: chip_bonus_liability_conserved_confirm_revert ---
def test_confirm_loads_bonus_liability_on_each_card(api):
    """PRD §3.5: "Each provisioned card is then granted the package's `included_chip_cents` as
    promotional chips: a `BONUS_GRANT` ledger entry is appended with a bonus delta equal to
    `included_chip_cents`, and the card's `bonus_chip_balance_cents` grows by that amount."

    Design: Difficulty/compensating_invariant/chip_bonus_liability_conserved_confirm_revert
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    total = sum(get_card(api, c)["bonus_chip_balance_cents"] for c in ctx["card_ids"])
    assert total == 2_000  # 2 cards * 1000 granted


def test_revert_returns_total_bonus_liability_to_zero(api):
    """PRD §3.5: "each of those voided wristbands' linked cards has the granted promotional
    chips clawed back — a `BONUS_CLAWBACK` ledger entry with a bonus delta equal to the
    negative of `included_chip_cents` is appended and the card's `bonus_chip_balance_cents`
    decreases by that amount".

    Design: Difficulty/compensating_invariant/chip_bonus_liability_conserved_confirm_revert
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    bid = ctx["booking"]["id"]
    revert_booking(api, bid)
    balances = [get_card(api, c)["bonus_chip_balance_cents"] for c in ctx["card_ids"]]
    assert balances == [0, 0]
    assert sum(balances) == 0


# --- Corner: cancel_completed_booking_invalid_state ---
def test_cancel_completed_booking_rejected(api):
    """PRD §3.6: "A cancel attempted from any other state is `ERR_INVALID_BOOKING_STATE`
    (409). Booking terminal states are `COMPLETED` and `CANCELLED`."

    Design: Corner/state_machines/cancel_completed_booking_invalid_state
    """
    ctx = setup_completed_booking(api, guest_count=2)
    bid = ctx["booking"]["id"]
    resp = api.cancel_party_booking(bid, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE, 409)
    booking = validate_success(api.get_party_booking(bid, COORDINATOR))
    assert booking["status"] == "COMPLETED"


# --- Corner: return_issued_wristband_invalid_wristband_state ---
def test_return_issued_wristband_rejected(api):
    """PRD §3.6: "returning a wristband that is not `ACTIVE` is rejected with
    `ERR_INVALID_WRISTBAND_STATE` (409)."

    Design: Corner/state_machines/return_issued_wristband_invalid_wristband_state
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=0)
    w0 = ctx["wristbands"][0]  # ISSUED (booking not checked in)
    resp = api.return_wristband(w0["id"], CASHIER)
    validate_error(resp, ApiErrorId.ERR_INVALID_WRISTBAND_STATE, 409)
