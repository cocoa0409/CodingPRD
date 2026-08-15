"""Rebooking-credit waterfall, redemption states, and the run-ops sweeps."""
from test_helpers import (
    ApiErrorId,
    apply_credit,
    assert_credit_invariant,
    cancel_booking,
    confirm_booking,
    create_booking,
    create_flight,
    get_booking,
    get_credit,
    get_flight,
    is_valid_uuid,
    list_credits_for_booking,
    passenger_entry,
    set_clock,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import create_route

AGENT = TEST_USERS["booking_agent_headers"]
DISP = TEST_USERS["dispatcher_headers"]
OPS = TEST_USERS["ops_admin_headers"]


def _setup_two_credits(api):
    """Two CONFIRMED bookings (25000 each) on F1 cancelled 30 minutes before
    its 14:00 departure -> two credits of 18750 each (credit-only tier).
    Returns (env, f3, f4, c1, c2) where f3/f4 are future flights on routes
    R1 (25000) and R2 (10000)."""
    env = setup_ops_env()
    r2 = create_route(route_code="R2", base_seat_price_cents=10000)
    f1 = create_flight(env, "2026-08-03T14:00:00Z")
    f3 = create_flight(env, "2026-08-04T14:00:00Z")
    f4 = create_flight(env, "2026-08-04T15:00:00Z", route=r2)

    b1 = create_booking(f1["id"], [passenger_entry("P0", 150)],
                        contact_name="A", contact_email="a@x.com")
    b2 = create_booking(f1["id"], [passenger_entry("P1", 150)],
                        contact_name="B", contact_email="b@x.com")
    confirm_booking(b1["id"], 25000)
    confirm_booking(b2["id"], 25000)

    set_clock("2026-08-03T13:30:00Z")  # 30 min before departure
    cancel_booking(b1["id"])
    cancel_booking(b2["id"])
    c1 = list_credits_for_booking(b1["id"])[0]
    c2 = list_credits_for_booking(b2["id"])[0]
    return env, f3, f4, c1, c2


def test_credit_partial_and_full_redemption(api):
    """PRD §3.8: "Redemption applies a credit to a HELD booking: the credit
    must be ISSUED or PARTIALLY_REDEEMED with `remaining_cents` above zero,
    otherwise `ERR_CREDIT_NOT_REDEEMABLE`."
    PRD §3.8: "The balance due is `quoted_total_cents` minus
    `credits_applied_cents` — `paid_cents` is always 0 while HELD — and the
    waterfall consumes the smaller of the credit's `remaining_cents` and that
    balance, adding it to both the credit's `redeemed_cents` and the
    booking's `credits_applied_cents`."
    PRD §3.8: "A credit drained to zero becomes REDEEMED; one partially
    consumed becomes PARTIALLY_REDEEMED, passing ISSUED → PARTIALLY_REDEEMED
    on the way."
    PRD §3.5: "Confirming collects the card: `card_amount_cents` must equal
    `quoted_total_cents` minus `credits_applied_cents` to the cent, otherwise
    `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402)"

    Design: Corner/state_machines/credit_partial_and_full_redemption
    """
    env, f3, f4, c1, c2 = _setup_two_credits(api)
    b3 = create_booking(f3["id"], [passenger_entry("P2", 150)],
                        contact_name="C", contact_email="c@x.com")
    b4 = create_booking(f4["id"], [passenger_entry("P3", 150)],
                        contact_name="D", contact_email="d@x.com")

    # Full consumption: min(remaining 18750, balance 25000) == 18750.
    applied = apply_credit(b3["id"], c1["id"])
    assert applied["credits_applied_cents"] == 18750
    c1_after = get_credit(c1["id"])
    assert c1_after["status"] == "REDEEMED"
    assert c1_after["redeemed_cents"] == 18750
    assert c1_after["remaining_cents"] == 0
    assert_credit_invariant(c1_after)

    # A drained credit cannot be applied again.
    resp = api.apply_credit(b4["id"], {"credit_id": c1["id"]}, AGENT)
    validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_REDEEMABLE)

    # Partial consumption: min(remaining 18750, balance 10000) == 10000.
    applied4 = apply_credit(b4["id"], c2["id"])
    assert applied4["credits_applied_cents"] == 10000
    c2_after = get_credit(c2["id"])
    assert c2_after["status"] == "PARTIALLY_REDEEMED"
    assert c2_after["redeemed_cents"] == 10000
    assert c2_after["remaining_cents"] == 8750
    assert_credit_invariant(c2_after)

    # Balances due after credit: 25000-18750 == 6250 and 10000-10000 == 0.
    confirmed3 = confirm_booking(b3["id"], 6250)
    assert confirmed3["status"] == "CONFIRMED"
    confirmed4 = confirm_booking(b4["id"], 0)
    assert confirmed4["status"] == "CONFIRMED"
    assert confirmed4["paid_cents"] == 0


def test_run_ops_sweeps_expired_holds_and_credits(api):
    """PRD §3.4: "In one invocation it expires every HELD booking whose
    `expires_at` is at or before now (§3.8), expires every rebooking credit
    whose `expires_at` has likewise arrived, and closes every OPEN `DutyDay`
    whose `duty_date` is before the current UTC date, moving it OPEN →
    CLOSED."
    PRD §3.8: "`issued_at` stamps the logical clock at minting, and
    `expires_at` is exactly 365 days later; a credit whose `expires_at` is at
    or before now is EXPIRED, swept by the batch tick from either ISSUED or
    PARTIALLY_REDEEMED."
    PRD §3.8: "Redemption applies a credit to a HELD booking: the credit must
    be ISSUED or PARTIALLY_REDEEMED with `remaining_cents` above zero,
    otherwise `ERR_CREDIT_NOT_REDEEMABLE`."

    Design: Corner/state_machines/run_ops_sweeps_expired_holds_and_credits
    """
    env = setup_ops_env(clock="2026-08-03T11:55:00Z")
    f1 = create_flight(env, "2026-08-03T14:00:00Z")
    f2 = create_flight(env, "2027-08-10T14:00:00Z")
    b1 = create_booking(f1["id"], [passenger_entry("P0", 150)],
                        contact_name="A", contact_email="a@x.com")
    b2 = create_booking(f1["id"], [passenger_entry("P1", 150)],
                        contact_name="B", contact_email="b@x.com")
    confirm_booking(b1["id"], 25000)

    # 30 minutes before departure -> credit-only tier:
    # round_half_up(25000 * 0.75) == 18750 minted, issued 13:30.
    set_clock("2026-08-03T13:30:00Z")
    cancelled = cancel_booking(b1["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["credited_cents"] == 18750
    c1 = list_credits_for_booking(b1["id"])[0]
    assert c1["amount_cents"] == 18750

    # B2's hold expired at 12:25; C1 expires 2027-08-03T13:30. One tick at
    # 2027-08-04 sweeps both.
    set_clock("2027-08-04T00:00:00Z")
    run_result = validate_success(api.run_ops(env["base"]["id"], OPS))
    assert run_result["ops_run_index"] == 1

    assert get_booking(b2["id"])["status"] == "EXPIRED"
    assert get_credit(c1["id"])["status"] == "EXPIRED"
    # Cancelled + expired bookings release their seats.
    assert get_flight(f1["id"])["seats_booked"] == 0

    b3 = create_booking(f2["id"], [passenger_entry("P9", 150)],
                        contact_name="D", contact_email="d@x.com")
    resp = api.apply_credit(b3["id"], {"credit_id": c1["id"]}, AGENT)
    validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_REDEEMABLE)
