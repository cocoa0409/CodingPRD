"""Dual-variant calculations: settled-vs-authorized balance, and RECOGNIZE-vs-ESCHEAT breakage.

Queue A (Difficulty) rule dual_variant_calc.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    assert_gift_card, assert_program,
    setup_card_with_hold, setup_two_jurisdiction_cards_for_breakage,
    place_hold, setup_program_and_active_card,
    TEST_USERS,
)

_STORE = TEST_USERS["store_associate_headers"]
_ADMIN = TEST_USERS["program_admin_headers"]


def test_balance_variants_diverge_by_held_amount(api):
    """PRD §2.5: "The available_balance_cents is the settled_balance_cents minus the
    pending_hold_cents."
    PRD §2.5: "Whenever a hold is outstanding the two views diverge by exactly the held
    amount; with no active holds they coincide."

    Design: Difficulty/dual_variant_calc/balance_authorized_vs_settled_diverge_with_hold
    """
    program, card, hold = setup_card_with_hold(settled_cents=5000, hold_cents=2000)
    fetched = validate_success(api.get_card(card["id"], _STORE), 200)
    assert_gift_card(fetched)
    assert fetched["settled_balance_cents"] == 5000, "settled ignores holds"
    assert fetched["pending_hold_cents"] == 2000
    assert fetched["available_balance_cents"] == 3000, \
        "available = settled - pending_hold = 5000 - 2000"


def test_settled_balance_ignores_holds_entirely(api):
    """PRD §2.5: "The settled_balance_cents is the sum of amount_cents over every
    LedgerEntry on the card whose status is POSTED; entries whose status is REVERSED are
    excluded from this sum."
    PRD §2.5: "The pending_hold_cents is the sum of amount_cents over every
    AuthorizationHold on the card whose status is ACTIVE."

    Design: Difficulty/dual_variant_calc/balance_authorized_vs_settled_diverge_with_hold
    """
    program, card = setup_program_and_active_card(settled_cents=5000)
    # Two ACTIVE holds accumulate in pending_hold; settled is untouched by holds.
    place_hold(card["id"], 1000)
    place_hold(card["id"], 500)
    fetched = validate_success(api.get_card(card["id"], _STORE), 200)
    assert fetched["settled_balance_cents"] == 5000, "settled unchanged by holds"
    assert fetched["pending_hold_cents"] == 1500
    assert fetched["available_balance_cents"] == 3500


def test_recognize_and_escheat_book_different_numbers_same_residual(api):
    """PRD §3.8: "Under RECOGNIZE, the full residual settled_balance_cents is booked as
    breakage revenue: a BREAKAGE debit equal to the negative of the residual is posted, and
    the program's breakage_recognized_cents rises by that magnitude."
    PRD §3.8: "Under ESCHEAT, only a fraction is owed to the state: the escheated amount is
    the residual settled_balance_cents multiplied by the rule's escheat_rate, rounded half up
    to whole cents; an ESCHEAT debit equal to the negative of that amount is posted, the
    program's escheat_liability_cents rises by that magnitude."

    Design: Difficulty/dual_variant_calc/breakage_recognize_vs_escheat_diverge_same_balance
    """
    program, card_fl, card_ca = setup_two_jurisdiction_cards_for_breakage(
        activate_at_iso="2025-01-01T00:00:00Z",
        assess_at_iso="2026-02-01T00:00:00Z",
        settled_cents=4000, escheat_rate=0.60)
    fl_after = get_success_data(api.assess_dormancy(card_fl["id"], _ADMIN))
    ca_after = get_success_data(api.assess_dormancy(card_ca["id"], _ADMIN))
    assert fl_after["lifecycle_status"] == "EXPIRED"
    assert ca_after["lifecycle_status"] == "EXPIRED"
    prog = validate_success(api.get_program(program["id"], _ADMIN), 200)
    assert_program(prog)
    # RECOGNIZE books the FULL residual; ESCHEAT books rate * residual = 0.60 * 4000 = 2400.
    assert prog["breakage_recognized_cents"] == 4000
    assert prog["escheat_liability_cents"] == 2400


def test_escheat_books_only_rate_fraction_not_full_residual(api):
    """PRD §3.8: "the escheated amount is the residual settled_balance_cents multiplied by
    the rule's escheat_rate, rounded half up to whole cents; an ESCHEAT debit equal to the
    negative of that amount is posted, the program's escheat_liability_cents rises by that
    magnitude, and the remaining residual is forfeited rather than booked as revenue."

    Design: Difficulty/dual_variant_calc/breakage_recognize_vs_escheat_diverge_same_balance
    """
    program, card_fl, card_ca = setup_two_jurisdiction_cards_for_breakage(
        activate_at_iso="2025-01-01T00:00:00Z",
        assess_at_iso="2026-02-01T00:00:00Z",
        settled_cents=4000, escheat_rate=0.60)
    get_success_data(api.assess_dormancy(card_ca["id"], _ADMIN))
    prog = validate_success(api.get_program(program["id"], _ADMIN), 200)
    # ESCHEAT card alone: escheat liability = 2400; the residual remainder is forfeited,
    # NOT booked as breakage revenue.
    assert prog["escheat_liability_cents"] == 2400
    assert prog["breakage_recognized_cents"] == 0, \
        "ESCHEAT must not book breakage revenue"
