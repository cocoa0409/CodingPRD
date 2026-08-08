"""Depth-3 delinquency cascade, event-cancel refund cascade, and rent-ledger
conservation.

Queue A (Difficulty):
transitive_cascade/delinquency_suspends_bookings_releases_holds,
transitive_cascade/event_cancel_cascades_registration_refunds,
compensating_invariant/rent_ledger_conserved_charge_then_payment.
"""
from test_helpers import (
    fixtures as fx,
    validate_success,
)


def _setup_delinquency_scenario(api):
    base = fx.setup_amenity_booking_base(
        api, clock="2026-05-20T00:00:00Z",
        resident_overrides={"full_name": "Gus", "email": "gus@x.com", "membership_tier": "STANDARD"},
        amenity_overrides={
            "name": "Gym", "amenity_type": "GYM", "capacity": 1,
            "base_rate_cents_per_hour": 4000, "deposit_cents": 10000,
            "buffer_minutes": 0, "open_minute": 0, "close_minute": 1440,
        },
    )
    booking = fx.new_booking(api, base["amenity"]["id"], base["resident"]["id"],
                             "2026-06-10T10:00:00Z", "2026-06-10T12:00:00Z",
                             expected_version=base["amenity"]["version"])
    return base["resident"]["id"], booking["id"]


def test_rent_charge_delinquency_suspends_future_booking(api):
    """PRD §3.3: "every one of that resident's `CONFIRMED` bookings whose
    `start_at` is still in the future (strictly after the current time) is
    transitioned from `CONFIRMED` to `SUSPENDED`."

    A 60000 charge drives the resident to DELINQUENT and cascades the future
    CONFIRMED booking into SUSPENDED.

    Design: Difficulty/transitive_cascade/delinquency_suspends_bookings_releases_holds
    """
    resident_id, booking_id = _setup_delinquency_scenario(api)
    fx.charge_resident(api, resident_id, 60000, "June rent")

    resident = fx.get_resident(api, resident_id)
    assert resident["account_status"] == "DELINQUENT"
    booking = fx.get_booking(api, booking_id)
    assert booking["status"] == "SUSPENDED"


def test_suspension_releases_deposit_hold(api):
    """PRD §3.3: "Each such suspension releases that booking's deposit hold by
    decreasing the resident's `hold_balance_cents` by its `deposit_hold_cents`;
    this is a hold movement only and writes no ledger entry."

    The 10000 deposit hold is released when the booking is cascade-suspended.

    Design: Difficulty/transitive_cascade/delinquency_suspends_bookings_releases_holds
    """
    resident_id, _ = _setup_delinquency_scenario(api)
    fx.charge_resident(api, resident_id, 60000, "June rent")

    resident = fx.get_resident(api, resident_id)
    assert resident["hold_balance_cents"] == 0, "hold released on suspension"


def _setup_registered_event(api):
    base = fx.setup_published_event(api, clock="2026-05-20T00:00:00Z", capacity=5, fee_cents=2000,
                                    event_start="2026-06-15T18:00:00Z", event_end="2026-06-15T20:00:00Z")
    reg = fx.register_resident(api, base["event"]["id"], base["resident"]["id"])
    return base["event"]["id"], reg["id"], base["resident"]["id"]


def test_event_cancel_cancels_reserved_registration(api):
    """PRD §3.4: "Cancelling a `PUBLISHED` event moves it to `CANCELLED` and
    cascades to its registrations: every registration in `RESERVED` or
    `WAITLISTED` is transitioned to `CANCELLED`, and any that carried a positive
    `fee_charged_cents` is refunded by crediting the resident's
    `wallet_credit_cents` and recording a `REFUND` ledger entry for the negative
    of that amount."

    Cancelling the event cancels its RESERVED registration.

    Design: Difficulty/transitive_cascade/event_cancel_cascades_registration_refunds
    """
    event_id, reg_id, _ = _setup_registered_event(api)
    cancelled = validate_success(api.cancel_event(event_id, fx.PM))
    assert cancelled["status"] == "CANCELLED"

    reg = validate_success(api.get_registration(reg_id, fx.PM))
    assert reg["status"] == "CANCELLED"


def test_event_cancel_refunds_fee_to_wallet(api):
    """PRD §3.4: "any that carried a positive `fee_charged_cents` is refunded by
    crediting the resident's `wallet_credit_cents` and recording a `REFUND`
    ledger entry for the negative of that amount."

    The 2000 fee charged at registration is refunded to wallet_credit_cents on
    event cancel.

    Design: Difficulty/transitive_cascade/event_cancel_cascades_registration_refunds
    """
    event_id, _, resident_id = _setup_registered_event(api)
    validate_success(api.cancel_event(event_id, fx.PM))

    resident = fx.get_resident(api, resident_id)
    assert resident["wallet_credit_cents"] == 2000


def _setup_charged_resident(api):
    base = fx.setup_property_unit_resident(api, resident_overrides={"full_name": "Pam", "email": "pam@x.com"})
    resident_id = base["resident"]["id"]
    fx.charge_resident(api, resident_id, 60000, "rent")
    return resident_id


def test_rent_balance_conserved_by_charge_then_payment(api):
    """PRD §2.6: "It follows that a forward charge of some amount paired with a
    later compensating reversal of the same amount leaves `rent_balance_cents`
    unchanged."

    A +60000 charge paired with a -60000 payment returns rent_balance_cents to
    its pre-charge value of 0.

    Design: Difficulty/compensating_invariant/rent_ledger_conserved_charge_then_payment
    """
    resident_id = _setup_charged_resident(api)
    fx.pay_resident(api, resident_id, 60000)

    resident = fx.get_resident(api, resident_id)
    assert resident["rent_balance_cents"] == 0


def test_exact_payment_leaves_no_wallet_and_good_standing(api):
    """PRD §3.3: "The payment amount first reduces the resident's
    `rent_balance_cents` by the lesser of the payment amount and the current
    balance; whatever remains after the balance reaches zero becomes prepaid
    credit added to `wallet_credit_cents`."

    An exact 60000 payment against a 60000 balance leaves wallet_credit_cents at
    0 and restores GOOD_STANDING.

    Design: Difficulty/compensating_invariant/rent_ledger_conserved_charge_then_payment
    """
    resident_id = _setup_charged_resident(api)
    fx.pay_resident(api, resident_id, 60000)

    resident = fx.get_resident(api, resident_id)
    assert resident["wallet_credit_cents"] == 0
    assert resident["account_status"] == "GOOD_STANDING"
