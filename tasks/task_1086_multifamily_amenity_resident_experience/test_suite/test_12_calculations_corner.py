"""Calculation corners: late-cancel penalty when late, payment wallet overflow,
emergency trip fee.

Queue B (Corner): calculations/*.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    make_vendor_headers,
    validate_success,
)


def test_late_cancel_penalty_applied_within_window(api):
    """PRD §3.2: "If it is less than 24 hours, the penalty is the
    `deposit_hold_cents` multiplied by a forfeit fraction of fifty percent,
    rounded half up."

    Cancelling 8h before start forfeits round(10000 * 0.5) = 5000 to
    rent_balance and releases the hold.

    Design: Corner/calculations/late_cancel_penalty_applied_when_late
    """
    base = fx.setup_amenity_booking_base(
        api, clock="2026-06-01T12:00:00Z",
        resident_overrides={"full_name": "Xan", "email": "xan@x.com", "membership_tier": "STANDARD"},
        amenity_overrides={"name": "Club", "amenity_type": "CLUBROOM", "capacity": 1,
                           "base_rate_cents_per_hour": 1000, "deposit_cents": 10000,
                           "buffer_minutes": 0, "open_minute": 0, "close_minute": 1440},
    )
    resident_id = base["resident"]["id"]
    booking = fx.new_booking(api, base["amenity"]["id"], resident_id,
                             "2026-06-01T20:00:00Z", "2026-06-01T22:00:00Z",
                             expected_version=base["amenity"]["version"])
    cancelled = validate_success(api.cancel_booking(booking["id"], make_resident_headers(resident_id)))
    assert cancelled["status"] == "CANCELLED"

    resident = fx.get_resident(api, resident_id)
    assert resident["rent_balance_cents"] == 5000
    assert resident["hold_balance_cents"] == 0


def test_payment_overflow_credits_wallet(api):
    """PRD §3.3: "The payment amount first reduces the resident's
    `rent_balance_cents` by the lesser of the payment amount and the current
    balance; whatever remains after the balance reaches zero becomes prepaid
    credit added to `wallet_credit_cents`."

    A 50000 payment against a 30000 balance clears rent to 0 and credits 20000
    to wallet_credit_cents.

    Design: Corner/calculations/payment_overflow_to_wallet
    """
    base = fx.setup_property_unit_resident(api, resident_overrides={"full_name": "Yos", "email": "yos@x.com"})
    resident_id = base["resident"]["id"]
    fx.charge_resident(api, resident_id, 30000, "partial")
    fx.pay_resident(api, resident_id, 50000, method="CARD")

    resident = fx.get_resident(api, resident_id)
    assert resident["rent_balance_cents"] == 0
    assert resident["wallet_credit_cents"] == 20000


def test_emergency_request_adds_trip_fee(api):
    """PRD §3.5: "A trip fee is added when the request's `priority` is
    `EMERGENCY`: 7500 cents, and zero otherwise."

    An EMERGENCY request completed with 1h labor at 8000/h and no parts invoices
    8000 + 7500 = 15500.

    Design: Corner/calculations/service_emergency_trip_fee_added
    """
    ctx = fx.setup_started_request(
        api, trade="PLUMBING", priority="EMERGENCY", estimated_hours=1,
        vendor_overrides={"name": "PlumbCo", "trades": ["PLUMBING"], "hourly_rate_cents": 8000},
    )
    completed = validate_success(api.complete_service_request(
        ctx["sr"]["id"], {"labor_hours": 1}, make_vendor_headers(ctx["vendor"]["id"])))
    assert completed["final_invoice_cents"] == 15500
