"""Booking deposits, the append-only payment ledger, the derived payment
posture axis, and the tiered cancellation refund policy."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_payment, ApiErrorId,
    create_trip, add_leg, quote_trip, book_trip, cancel_trip, set_clock,
    create_advisory,
    setup_quoted_trip, setup_booked_trip,
    make_sales_agent_headers, make_ops_admin_headers,
)

SALES_AGENT = make_sales_agent_headers()
OPS_ADMIN = make_ops_admin_headers()

# Canonical 480-minute LIGHT_JET quote: legs 2000000, 5% discount 100000,
# 8% surcharge on the discounted 1900000 = 152000 -> quoted 2052000,
# deposit_required 513000, balance 1539000.
QUOTE_480 = 2052000
DEPOSIT_480 = 513000
BALANCE_480 = 1539000


def _booked_480_paid_in_full():
    """Trip dep 2026-08-04T00:00:00Z, single REV 480 leg, quoted 2052000,
    booked 513000 + balance 1539000 (collected 2052000)."""
    return setup_booked_trip(legs=((480, "REVENUE", False),),
                             departure_at="2026-08-04T00:00:00Z",
                             pay_in_full=True)


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / cancellation_refund_three_input_tier
# ---------------------------------------------------------------------------

def test_cancel_customer_30h_before_departure_half_fee(api):
    """PRD §3.4: "For a `CUSTOMER` cancellation, at least 72 hours before
    departure the fee is ten percent of `collected_cents`; at least 24 hours
    but less than 72 hours before, the fee is fifty percent; under 24 hours,
    the fee is the entire collected amount."
    PRD §3.4: "The refund policy tiers on the time remaining before
    departure, measured in hours from the current clock to `departure_at`
    with fractional hours allowed, and it computes against the amount
    actually collected, not the quoted total."

    Design: Difficulty/combinatorial_formula/cancellation_refund_three_input_tier
    """
    trip, _legs = _booked_480_paid_in_full()
    set_clock("2026-08-02T18:00:00Z")  # exactly 30 hours before departure
    resp = api_client.cancel_trip(trip["id"], {"reason": "CUSTOMER"}, SALES_AGENT)
    cancelled = validate_success(resp, expected_status=200)
    assert cancelled["cancellation_fee_cents"] == 1026000, "50% of 2052000 at 30h"
    assert cancelled["refund_cents"] == 1026000
    assert cancelled["status"] == "CANCELLED"


def test_cancel_customer_30h_posture_refunded_partial(api):
    """PRD §3.4: "The `payment_posture` then recomputes on the cancelled
    trip: a positive refund with a zero fee reads `REFUNDED_FULL`, a positive
    refund with a positive fee reads `REFUNDED_PARTIAL`, and a zero refund
    leaves the pre-cancellation posture unchanged."
    PRD §3.4: "When the refund is positive, a `POSTED` payment of type
    `REFUND` is created for it; when the refund is zero, no payment row
    appears."

    Design: Difficulty/combinatorial_formula/cancellation_refund_three_input_tier
    """
    trip, _legs = _booked_480_paid_in_full()
    set_clock("2026-08-02T18:00:00Z")
    cancelled = cancel_trip(trip["id"], "CUSTOMER")
    assert cancelled["payment_posture"] == "REFUNDED_PARTIAL"
    rows, _meta = validate_paginated(api_client.list_payments(trip["id"], OPS_ADMIN))
    refunds = [p for p in rows if p["payment_type"] == "REFUND"]
    assert len(refunds) == 1
    assert_payment(refunds[0])
    assert refunds[0]["amount_cents"] == 1026000
    assert refunds[0]["status"] == "POSTED"


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / cancel_at_exactly_72h_tier1
# ---------------------------------------------------------------------------

def test_cancel_at_exactly_72h_uses_ten_percent_tier(api):
    """PRD §3.4: "Boundary precision matters: exactly 72.0 hours before
    departure falls in the ten-percent tier, and exactly 24.0 hours falls in
    the fifty-percent tier."

    Design: Difficulty/boundary_precision_check/cancel_at_exactly_72h_tier1
    """
    # Default clock 2026-08-01T00:00:00Z is exactly 72.0h before departure.
    trip, _legs = _booked_480_paid_in_full()
    resp = api_client.cancel_trip(trip["id"], {"reason": "CUSTOMER"}, SALES_AGENT)
    cancelled = validate_success(resp, expected_status=200)
    assert cancelled["cancellation_fee_cents"] == 205200, "10% of 2052000 at exactly 72.0h"
    assert cancelled["refund_cents"] == 1846800


def test_cancel_at_72h_refund_recomputes_collected(api):
    """PRD §3.4: "Every posted payment recomputes two derived values on the
    trip: `collected_cents`, the sum of all posted deposit and balance
    amounts minus the sum of posted refunds, and the `payment_posture` — on a
    non-cancelled trip, a net collection of zero reads `UNPAID`, a net
    collection below the quoted total reads `DEPOSIT_PAID`, and a net
    collection at or above the quoted total reads `PAID_IN_FULL`."

    Design: Difficulty/boundary_precision_check/cancel_at_exactly_72h_tier1
    """
    trip, _legs = _booked_480_paid_in_full()
    cancelled = cancel_trip(trip["id"], "CUSTOMER")
    assert cancelled["collected_cents"] == 205200, "2052000 collected - 1846800 refund"
    assert cancelled["payment_posture"] == "REFUNDED_PARTIAL"


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / payment_conservation_on_cancel
# ---------------------------------------------------------------------------

def test_cancel_refund_plus_fee_conserves_collected(api):
    """PRD §3.4: "The `cancellation_fee_cents` is the collected amount times
    the tier percentage, rounded half up, and the `refund_cents` is the
    collected amount minus the fee."
    Invariant: refund + fee == the amount collected before cancellation; the
    post-cancel collected equals the retained fee.

    Design: Difficulty/compensating_invariant/payment_conservation_on_cancel
    """
    trip, _legs = _booked_480_paid_in_full()
    collected_before = trip["collected_cents"]
    assert collected_before == QUOTE_480
    set_clock("2026-08-02T00:00:00Z")  # 48h before departure -> 50% tier
    cancelled = cancel_trip(trip["id"], "CUSTOMER")
    assert cancelled["cancellation_fee_cents"] == 1026000
    assert cancelled["refund_cents"] == 1026000
    assert cancelled["refund_cents"] + cancelled["cancellation_fee_cents"] == collected_before
    assert cancelled["collected_cents"] == collected_before - cancelled["refund_cents"]


def test_cancel_payment_ledger_conservation(api):
    """PRD §3.4: "A successful booking creates a payment row of type
    `DEPOSIT` for the supplied amount in `POSTED` status, recomputes the
    `payment_posture` — `DEPOSIT_PAID` normally, or `PAID_IN_FULL`
    immediately if the deposit happens to cover the entire quote — moves the
    trip to `BOOKED`, and increments its `version`."
    PRD §3.4: "When the refund is positive, a `POSTED` payment of type
    `REFUND` is created for it; when the refund is zero, no payment row
    appears."
    Invariant: the append-only ledger holds DEPOSIT 513000 + BALANCE 1539000
    + REFUND 1026000, all POSTED; net equals the retained fee.

    Design: Difficulty/compensating_invariant/payment_conservation_on_cancel
    """
    trip, _legs = _booked_480_paid_in_full()
    set_clock("2026-08-02T00:00:00Z")
    cancel_trip(trip["id"], "CUSTOMER")
    rows, meta = validate_paginated(api_client.list_payments(trip["id"], OPS_ADMIN))
    assert meta["total_count"] == 3
    by_type = {}
    for p in rows:
        assert_payment(p)
        by_type.setdefault(p["payment_type"], []).append(p["amount_cents"])
    assert by_type["DEPOSIT"] == [513000]
    assert by_type["BALANCE"] == [1539000]
    assert by_type["REFUND"] == [1026000]
    net = 513000 + 1539000 - 1026000
    assert net == 1026000, "no cent appears or vanishes"


# ---------------------------------------------------------------------------
# Queue B: calculations / payment_posture_progression
# ---------------------------------------------------------------------------

def test_payment_posture_progression(api):
    """PRD §3.4: "Every posted payment recomputes two derived values on the
    trip: `collected_cents`, the sum of all posted deposit and balance
    amounts minus the sum of posted refunds, and the `payment_posture` — on a
    non-cancelled trip, a net collection of zero reads `UNPAID`, a net
    collection below the quoted total reads `DEPOSIT_PAID`, and a net
    collection at or above the quoted total reads `PAID_IN_FULL`."

    Design: Corner/calculations/payment_posture_progression
    """
    trip = create_trip(customer_name="Cust PP")
    add_leg(trip["id"], block_minutes=60)
    assert trip["payment_posture"] == "UNPAID"
    quoted = quote_trip(trip["id"])
    assert quoted["quoted_total_cents"] == 270000

    booked = book_trip(trip["id"], 67500)
    assert booked["payment_posture"] == "DEPOSIT_PAID"
    assert booked["collected_cents"] == 67500

    validate_success(api_client.create_payment(
        {"trip_request_id": trip["id"], "payment_type": "BALANCE",
         "amount_cents": 202500}, SALES_AGENT), expected_status=201)
    after = validate_success(api_client.get_trip_request(trip["id"], SALES_AGENT), 200)
    assert after["payment_posture"] == "PAID_IN_FULL"
    assert after["collected_cents"] == 270000


# ---------------------------------------------------------------------------
# Queue B: calculations / overpayment_rejected
# ---------------------------------------------------------------------------

def test_overpayment_by_one_cent_rejected(api):
    """PRD §3.4: "A balance payment may not exceed the trip's outstanding
    balance, defined as `quoted_total_cents` minus `collected_cents`;
    overpayment is rejected with `ERR_OVERPAYMENT`."

    Design: Corner/calculations/overpayment_rejected
    """
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=True,
                                    customer_name="Cust OP")
    assert trip["collected_cents"] == 270000
    resp = api_client.create_payment(
        {"trip_request_id": trip["id"], "payment_type": "BALANCE", "amount_cents": 1},
        SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)


# ---------------------------------------------------------------------------
# Queue B: calculations / deposit_below_required_rejected
# ---------------------------------------------------------------------------

def test_deposit_one_cent_below_required_rejected(api):
    """PRD §3.4: "The deposit must be at least the `deposit_required_cents`,
    or booking is rejected with `ERR_DEPOSIT_INSUFFICIENT`."

    Design: Corner/calculations/deposit_below_required_rejected
    """
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), customer_name="Cust DP")
    assert trip["deposit_required_cents"] == 67500
    resp = api_client.book_trip(trip["id"], {"deposit_cents": 67499}, SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)


# ---------------------------------------------------------------------------
# Queue B: calculations / weather_cancel_zero_fee_full_refund
# ---------------------------------------------------------------------------

def test_weather_cancel_waives_fee_full_refund(api):
    """PRD §3.4: "A `WEATHER` or `OPS` cancellation waives the fee entirely."
    PRD §3.4: "a positive refund with a zero fee reads `REFUNDED_FULL`..."

    Design: Corner/calculations/weather_cancel_zero_fee_full_refund
    """
    trip, _legs = _booked_480_paid_in_full()
    # Advisory on the origin station whose closed window contains departure.
    create_advisory(station_icao="KLAX", severity="SIGMET",
                    starts_at="2026-08-03T00:00:00Z", ends_at="2026-08-05T00:00:00Z")
    set_clock("2026-08-02T00:00:00Z")  # 48h before: 50% tier would apply to CUSTOMER
    cancelled = cancel_trip(trip["id"], "WEATHER")
    assert cancelled["cancellation_fee_cents"] == 0, "WEATHER waives the tiered fee"
    assert cancelled["refund_cents"] == 2052000
    assert cancelled["payment_posture"] == "REFUNDED_FULL"
    assert cancelled["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Queue B: errors / weather_cancel_without_advisory_rejected
# ---------------------------------------------------------------------------

def test_weather_cancel_without_advisory_rejected(api):
    """PRD §3.4: "A `WEATHER` cancellation must be backed by a published
    weather advisory whose `station_icao` matches the trip's `origin_icao` or
    `destination_icao` and whose closed effective window contains the trip's
    `departure_at`; without one, the cancellation is rejected with
    `ERR_NO_ACTIVE_WEATHER_ADVISORY`."

    Design: Corner/errors/weather_cancel_without_advisory_rejected
    """
    trip, _legs = setup_booked_trip(legs=((480, "REVENUE", False),),
                                    departure_at="2026-08-04T00:00:00Z",
                                    pay_in_full=False, customer_name="Cust WN")
    resp = api_client.cancel_trip(trip["id"], {"reason": "WEATHER"}, SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_WEATHER_ADVISORY)
    trip_after = validate_success(api_client.get_trip_request(trip["id"], OPS_ADMIN), 200)
    assert trip_after["status"] == "BOOKED", "rejected cancel leaves the trip untouched"
    rows, _meta = validate_paginated(api_client.list_payments(trip["id"], OPS_ADMIN))
    assert all(p["payment_type"] != "REFUND" for p in rows)


# ---------------------------------------------------------------------------
# Queue B: errors / manual payment channel restrictions
# ---------------------------------------------------------------------------

def test_manual_deposit_via_payments_rejected(api):
    """PRD §3.4: "Deposit rows are created only through booking and refund
    rows only through cancellation; the manual payment capability exists for
    balance collection and accepts only `BALANCE` payments on trips in
    `BOOKED` or `DISPATCHED` status — a manual `DEPOSIT` or `REFUND`, or a
    balance payment on a trip in any other status, is rejected with
    `ERR_PAYMENT_STATE_INVALID`."

    Design: Corner/errors/manual_deposit_via_payments_rejected
    """
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust MD")
    resp = api_client.create_payment(
        {"trip_request_id": trip["id"], "payment_type": "DEPOSIT", "amount_cents": 1000},
        SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_STATE_INVALID)


def test_manual_refund_via_payments_rejected(api):
    """PRD §3.4: "Deposit rows are created only through booking and refund
    rows only through cancellation; the manual payment capability exists for
    balance collection and accepts only `BALANCE` payments on trips in
    `BOOKED` or `DISPATCHED` status — a manual `DEPOSIT` or `REFUND`, or a
    balance payment on a trip in any other status, is rejected with
    `ERR_PAYMENT_STATE_INVALID`."

    Design: Corner/errors/manual_refund_via_payments_rejected
    """
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust MR")
    resp = api_client.create_payment(
        {"trip_request_id": trip["id"], "payment_type": "REFUND", "amount_cents": 1000},
        SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_STATE_INVALID)


def test_balance_payment_on_quoted_trip_rejected(api):
    """PRD §3.4: "Deposit rows are created only through booking and refund
    rows only through cancellation; the manual payment capability exists for
    balance collection and accepts only `BALANCE` payments on trips in
    `BOOKED` or `DISPATCHED` status — a manual `DEPOSIT` or `REFUND`, or a
    balance payment on a trip in any other status, is rejected with
    `ERR_PAYMENT_STATE_INVALID`."

    Design: Corner/errors/balance_payment_on_quoted_trip_rejected
    """
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), customer_name="Cust BQ")
    resp = api_client.create_payment(
        {"trip_request_id": trip["id"], "payment_type": "BALANCE", "amount_cents": 1000},
        SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_STATE_INVALID)


# ---------------------------------------------------------------------------
# Queue B: consistency_model / immediate_consistency_book_response
# ---------------------------------------------------------------------------

def test_book_response_carries_derived_fields_immediately(api):
    """PRD §1: "Consistency is immediate: every state change, cascade, and
    derived amount is applied within the request that triggers it..."
    PRD §3.4: "A successful booking creates a payment row of type `DEPOSIT`
    for the supplied amount in `POSTED` status, recomputes the
    `payment_posture` — `DEPOSIT_PAID` normally, or `PAID_IN_FULL`
    immediately if the deposit happens to cover the entire quote — moves the
    trip to `BOOKED`, and increments its `version`."

    Design: Corner/consistency_model/immediate_consistency_book_response
    """
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), customer_name="Cust IC")
    resp = api_client.book_trip(trip["id"], {"deposit_cents": 67500}, SALES_AGENT)
    booked = validate_success(resp, expected_status=200)
    assert booked["status"] == "BOOKED"
    assert booked["payment_posture"] == "DEPOSIT_PAID"
    assert booked["collected_cents"] == 67500
