"""Non-linear state machines (parallel risk/lifecycle, revision loop) and transitive cascades.

Queue A (Difficulty) rules non_linear_state_machine and transitive_cascade.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_program_and_active_card, place_hold, flag_card,
    setup_pending_refund_on_owned_card, make_customer_headers,
    setup_open_replacement, setup_confirmed_bulk_order,
    assert_gift_card, assert_program,
    TEST_USERS,
)

_STORE = TEST_USERS["store_associate_headers"]
_FRAUD = TEST_USERS["fraud_analyst_headers"]
_ADMIN = TEST_USERS["program_admin_headers"]


def test_freeze_advances_risk_dimension_while_lifecycle_stays_active(api):
    """PRD §2.8: "A GiftCard carries two orthogonal status fields that evolve independently."
    PRD §3.7: "Freezing moves a FLAGGED card FLAGGED to FROZEN_RISK ... as a cascade, every
    AuthorizationHold on the card whose status is ACTIVE is released to RELEASED and
    pending_hold_cents recomputes to zero."

    Design: Difficulty/non_linear_state_machine/giftcard_parallel_lifecycle_and_risk_dimensions
    """
    program, card = setup_program_and_active_card(settled_cents=5000)
    place_hold(card["id"], 1000)
    flag_card(card["id"])
    frozen = validate_success(api.freeze_card(card["id"], _FRAUD), 200)
    assert_gift_card(frozen)
    assert frozen["risk_status"] == "FROZEN_RISK"
    assert frozen["lifecycle_status"] == "ACTIVE", \
        "lifecycle stays ACTIVE; risk is an independent dimension"
    assert frozen["pending_hold_cents"] == 0, "freeze released the ACTIVE hold"
    assert frozen["settled_balance_cents"] == 5000, "settled untouched by freeze"


def test_flag_advances_risk_without_touching_lifecycle(api):
    """PRD §3.7: "Flagging a card moves its risk_status CLEAR to FLAGGED and is permitted
    only when the card's lifecycle_status is ACTIVE or EXHAUSTED."
    PRD §2.8: "Because risk is a separate dimension, there is deliberately no 'frozen'
    lifecycle state — a frozen card retains whatever lifecycle status it held."

    Design: Difficulty/non_linear_state_machine/giftcard_parallel_lifecycle_and_risk_dimensions
    """
    program, card = setup_program_and_active_card(settled_cents=5000)
    flagged = validate_success(api.flag_card(card["id"], _FRAUD), 200)
    assert flagged["risk_status"] == "FLAGGED"
    assert flagged["lifecycle_status"] == "ACTIVE"
    assert flagged["settled_balance_cents"] == 5000


def test_refund_revision_loop_overwrites_amount_back_to_pending(api):
    """PRD §3.6: "from NEEDS_REVISION the owning Customer resubmits a revised positive
    requested_refund_cents, which updates the stored amount and loops the request back to
    PENDING."

    Design: Difficulty/non_linear_state_machine/refund_request_revision_loop_cycle
    """
    program, customer, card, refund = setup_pending_refund_on_owned_card(
        settled_cents=5000, refund_cents=1000)
    # ProgramAdmin sends back for revision, customer resubmits a lower amount.
    validate_success(api.request_refund_revision(refund["id"], _ADMIN), 200)
    resubmitted = validate_success(
        api.resubmit_refund(refund["id"], {"requested_refund_cents": 750},
                            make_customer_headers(customer["id"])), 200)
    assert resubmitted["status"] == "PENDING"
    assert resubmitted["requested_refund_cents"] == 750


def test_refund_request_revision_moves_to_needs_revision(api):
    """PRD §3.6: "They may send it back for revision (PENDING to NEEDS_REVISION) with no side
    effects."

    Design: Difficulty/non_linear_state_machine/refund_request_revision_loop_cycle
    """
    program, customer, card, refund = setup_pending_refund_on_owned_card(
        settled_cents=5000, refund_cents=1000)
    revised = validate_success(api.request_refund_revision(refund["id"], _ADMIN), 200)
    assert revised["status"] == "NEEDS_REVISION"
    assert revised["requested_refund_cents"] == 1000, "amount unchanged on revision request"


def test_replacement_approve_cascades_void_transfer_and_credit(api):
    """PRD §3.7: "It posts a TRANSFER_OUT debit on the old card equal to the negative of that
    snapshot (zeroing the old card) and a TRANSFER_IN credit of the same magnitude on the new
    card ... The old card transitions ACTIVE to VOIDED, its replaced_by_card_id is set to the
    new card's id, and the old card's version increments."

    Design: Difficulty/transitive_cascade/replacement_approve_three_hop_cascade
    """
    program, old_card, replacement = setup_open_replacement(settled_cents=3000, reason="FRAUD")
    approved = validate_success(
        api.approve_replacement(replacement["id"],
                                {"expected_old_card_version": old_card["version"]}, _FRAUD), 200)
    assert approved["status"] == "APPROVED"
    assert approved["transferred_amount_cents"] == 3000
    new_card_id = approved["new_card_id"]
    old_after = validate_success(api.get_card(old_card["id"], _FRAUD), 200)
    assert old_after["lifecycle_status"] == "VOIDED"
    assert old_after["settled_balance_cents"] == 0, "TRANSFER_OUT zeroed the old card"
    assert old_after["replaced_by_card_id"] == new_card_id
    new_after = validate_success(api.get_card(new_card_id, _FRAUD), 200)
    assert new_after["settled_balance_cents"] == 3000, "TRANSFER_IN credited the new card"


def test_bulk_activate_mints_cards_and_recomputes_liability(api):
    """PRD §3.9: "Activation mints card_count gift cards as a cascade, each driven INACTIVE to
    ACTIVE with a LOAD credit of face_value_cents ... the program's outstanding_liability_cents
    is then re-derived to reflect all the newly loaded value."

    Design: Difficulty/transitive_cascade/bulk_activate_two_hop_cascade_liability
    """
    program, buyer, confirmed = setup_confirmed_bulk_order(
        card_count=4, face_value_cents=2500, b2b_discount_pct=0.035)
    activated = validate_success(api.activate_bulk_order(confirmed["id"], _ADMIN), 200)
    assert activated["status"] == "ACTIVATED"
    prog = validate_success(api.get_program(program["id"], _ADMIN), 200)
    assert_program(prog)
    # 4 cards * 2500 face value each = 10000 outstanding liability.
    assert prog["outstanding_liability_cents"] == 10000
