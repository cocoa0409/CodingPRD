"""Wallet conservation invariant and immediate-consistency of charges.

Translates difficulty queue instance:
  compensating_invariant / booking_cancel_restores_wallet_conservation
and corner queue instances for booking-charge immediate visibility and the
already-cancelled invalid-state guard.
"""
from test_helpers import (
    validate_success, validate_error, assert_wallet_conservation,
    make_member_operator_headers, TEST_USERS,
    register_funded_member, create_station, current_member_version,
    create_booking,
)


# ── Difficulty: compensating_invariant / booking_cancel_restores_wallet_conservation ──

def test_cancel_booking_restores_wallet_balance_and_charged(api):
    """PRD 3.2: "the cancellation refunds the member by crediting
    wallet_balance_cents by fee_cents and reducing lifetime_charged_cents by the
    same amount, the compensating move that restores the wallet invariant." A
    booking fee of 2400 charged then refunded returns balance to 100000 and
    lifetime_charged to 0.

    Design: Difficulty/compensating_invariant/booking_cancel_restores_wallet_conservation
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="Prep16", station_class="PREP_TABLE")
    booking = create_booking(member["id"], prep["id"],
                             "2026-07-09T12:00:00.000Z", "2026-07-09T14:00:00.000Z", v)
    validate_success(api.cancel_booking(member["id"], booking["id"], mo), 200)

    after = validate_success(api.get_member(member["id"], mo), 200)
    assert after["wallet_balance_cents"] == 100000, f"expected 100000, got {after['wallet_balance_cents']}"
    assert after["lifetime_charged_cents"] == 0, f"expected 0, got {after['lifetime_charged_cents']}"
    assert_wallet_conservation(after)


def test_booking_charge_debits_wallet_and_preserves_invariant(api):
    """PRD 2.7: "wallet_balance_cents always equals lifetime_loaded_cents minus
    lifetime_charged_cents." and PRD 3.2: "confirmation then debits
    wallet_balance_cents by fee_cents and increases lifetime_charged_cents by the
    same amount." After a single 2400 booking the balance is 97600 and
    lifetime_charged is 2400.

    Design: Difficulty/compensating_invariant/booking_cancel_restores_wallet_conservation
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="Prep16b", station_class="PREP_TABLE")
    create_booking(member["id"], prep["id"],
                   "2026-07-09T12:00:00.000Z", "2026-07-09T14:00:00.000Z", v)
    after = validate_success(api.get_member(member["id"], mo), 200)
    assert after["wallet_balance_cents"] == 97600
    assert after["lifetime_charged_cents"] == 2400
    assert after["lifetime_loaded_cents"] == 100000
    assert_wallet_conservation(after)


# ── Corner: consistency_model / booking_charge_visible_in_same_response ──

def test_booking_charge_immediately_visible_on_get(api):
    """PRD 3.2: "confirmation then debits wallet_balance_cents by fee_cents and
    increases lifetime_charged_cents by the same amount." After top-up 100000
    then a 2400 booking, the next GET shows wallet_balance_cents == 97600,
    reflecting the immediate debit.

    Design: Corner/consistency_model/booking_charge_visible_in_same_response
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="PrepCm", station_class="PREP_TABLE")
    create_booking(member["id"], prep["id"],
                   "2026-07-22T12:00:00.000Z", "2026-07-22T14:00:00.000Z", v)
    refetched = validate_success(api.get_member(member["id"], mo), 200)
    assert refetched["wallet_balance_cents"] == 97600


# ── Corner: state_machines / booking_cancel_already_cancelled_returns_invalid_state ──

def test_cancel_already_cancelled_booking_rejected(api):
    """PRD 3.2: "Cancelling a booking is permitted only while it is CONFIRMED
    (otherwise ERR_INVALID_STATE)". A second cancel of an already-CANCELLED
    booking is rejected.

    Design: Corner/state_machines/booking_cancel_already_cancelled_returns_invalid_state
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="PrepC", station_class="PREP_TABLE")
    booking = create_booking(member["id"], prep["id"],
                             "2026-07-12T12:00:00.000Z", "2026-07-12T13:00:00.000Z", v)
    validate_success(api.cancel_booking(member["id"], booking["id"], mo), 200)
    res = api.cancel_booking(member["id"], booking["id"], mo)
    validate_error(res, "ERR_INVALID_STATE")
