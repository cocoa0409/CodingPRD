"""Exchange settlement (combinatorial formula) and invoice reconciliation rounding."""
from test_helpers import (
    validate_success,
    make_approved_trip, book, trip_version, exchange, make_invoice,
    credits_for_traveler,
    TEST_USERS,
)

MGR = TEST_USERS["travel_manager_headers"]
FIN = TEST_USERS["finance_officer_headers"]


def _booked_nonref_ticket(api, fare_cents=250000):
    """Approved trip with one TICKETED NONREFUNDABLE AIR booking consuming the rate."""
    ctx = make_approved_trip(with_rate=True, market_estimate=420000)
    trip, trav, ven, rate = ctx["trip"], ctx["traveler"], ctx["vendor"], ctx["rate"]
    booking = book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"],
                   negotiated_rate_id=rate["id"], segment_type="AIR",
                   fare_basis="NONREFUNDABLE", fare_cents=fare_cents)
    return ctx, booking


def test_exchange_downgrade_sets_new_fare_and_penalty_fee(api):
    """PRD §3.4: "The exchange moves the old booking to `EXCHANGED` and creates a fresh
    `TICKETED` booking carrying the new fare."
    PRD §3.4: "The new booking's `exchange_fee_cents` is set to the penalty."

    Design: Difficulty/combinatorial_formula/exchange_settlement_downgrade_residual_credit
    """
    ctx, old = _booked_nonref_ticket(api)
    trav = ctx["traveler"]
    new = exchange(old["id"], trav["id"], new_fare_cents=200000)
    assert new["fare_cents"] == 200000, f"new booking fare should be 200000, got {new['fare_cents']}"
    assert new["exchange_fee_cents"] == 15000, (
        f"exchange fee should equal policy penalty 15000, got {new['exchange_fee_cents']}"
    )
    old_after = validate_success(api.get_booking(old["id"], MGR))
    assert old_after["status"] == "EXCHANGED", f"old booking should be EXCHANGED, got {old_after['status']}"


def test_exchange_downgrade_issues_residual_credit(api):
    """PRD §3.4: "The residual credit is the old fare minus the new fare minus the penalty,
    floored at zero — that is, the greater of zero and (old `fare_cents` − `new_fare_cents`
    − penalty)."
    PRD §3.4: "When that residual is positive (a genuine downgrade after absorbing the
    penalty), an `UnusedTicketCredit` of exactly that residual value is issued to the traveler."

    Design: Difficulty/combinatorial_formula/exchange_settlement_downgrade_residual_credit
    """
    ctx, old = _booked_nonref_ticket(api)
    trav = ctx["traveler"]
    exchange(old["id"], trav["id"], new_fare_cents=200000)
    # residual = max(0, 250000 - 200000 - 15000) = 35000
    credits = credits_for_traveler(trav["id"])
    assert len(credits) == 1, f"exactly one residual credit expected, got {len(credits)}"
    credit = credits[0]
    assert credit["residual_value_cents"] == 35000, (
        f"residual credit should be 35000, got {credit['residual_value_cents']}"
    )
    assert credit["face_value_cents"] == 35000


def _two_nonref_bookings(api, fare_cents=300):
    """Auto-approved trip with two non-overlapping NONREFUNDABLE AIR bookings."""
    ctx = make_approved_trip(with_rate=False, market_estimate=50000,
                             trip_overrides={"return_date": "2026-08-20T09:00:00Z"})
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    b1 = book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"],
              segment_type="AIR", fare_basis="NONREFUNDABLE", fare_cents=fare_cents,
              depart_datetime="2026-08-01T09:00:00Z", return_datetime="2026-08-01T20:00:00Z")
    v2 = trip_version(trip["id"], trav["id"])
    b2 = book(trip["id"], trav["id"], v2, vendor_id=ven["id"], segment_type="AIR",
              fare_basis="NONREFUNDABLE", fare_cents=fare_cents,
              depart_datetime="2026-08-10T09:00:00Z", return_datetime="2026-08-10T20:00:00Z")
    return ctx, b1, b2


def test_invoice_reconciled_total_rounds_fee_per_line_before_summing(api):
    """PRD §3.8: "The invoice's `reconciled_total_cents` is the sum, over all lines, of each
    line's matched amount plus that line's management fee, where the fee is the matched
    amount multiplied by the 0.035 management rate and rounded half-up to whole cents per
    line before the summation (§2.5)."

    Design: Difficulty/combinatorial_formula/invoice_reconciliation_per_line_rounding_order
    """
    ctx, b1, b2 = _two_nonref_bookings(api, fare_cents=300)
    ven = ctx["vendor"]
    inv = make_invoice(ven["id"], invoiced_total_cents=622, lines=[
        {"booking_id": b1["id"], "billed_amount_cents": 300},
        {"booking_id": b2["id"], "billed_amount_cents": 300},
    ])
    reconciled = validate_success(api.reconcile_invoice(inv["id"], FIN))
    # round_half_up(300*0.035)=round(10.5)=11 per line -> (300+11)+(300+11) = 622 (not 621).
    assert reconciled["reconciled_total_cents"] == 622, (
        f"per-line-before-sum rounding should give 622, got {reconciled['reconciled_total_cents']}"
    )


def test_invoice_zero_variance_moves_to_reconciled(api):
    """PRD §3.8: "The `variance_cents` is the vendor's `invoiced_total_cents` minus the
    computed `reconciled_total_cents`."
    PRD §3.8: "If the variance comes out to exactly zero, reconciliation moves the invoice
    from `RECEIVED` to `RECONCILED`; if the variance is non-zero, it moves the invoice to
    `DISPUTED`."

    Design: Difficulty/combinatorial_formula/invoice_reconciliation_per_line_rounding_order
    """
    ctx, b1, b2 = _two_nonref_bookings(api, fare_cents=300)
    ven = ctx["vendor"]
    inv = make_invoice(ven["id"], invoiced_total_cents=622, lines=[
        {"booking_id": b1["id"], "billed_amount_cents": 300},
        {"booking_id": b2["id"], "billed_amount_cents": 300},
    ])
    reconciled = validate_success(api.reconcile_invoice(inv["id"], FIN))
    assert reconciled["variance_cents"] == 0, f"variance should be 0, got {reconciled['variance_cents']}"
    assert reconciled["status"] == "RECONCILED", f"expected RECONCILED, got {reconciled['status']}"


def test_invoice_price_variance_line_moves_invoice_to_disputed(api):
    """PRD §3.8: "if the line's `billed_amount_cents` equals that matched amount the
    `match_status` is `MATCHED`, otherwise it is `PRICE_VARIANCE`."
    PRD §3.8: "if the variance is non-zero, it moves the invoice to `DISPUTED`."

    Design: Corner/calculations/invoice_reconcile_variance_moves_to_disputed
    """
    ctx = make_approved_trip(with_rate=False, market_estimate=50000)
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    b1 = book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"],
              segment_type="AIR", fare_basis="NONREFUNDABLE", fare_cents=250000)
    inv = make_invoice(ven["id"], invoiced_total_cents=260000, lines=[
        {"booking_id": b1["id"], "billed_amount_cents": 260000},
    ])
    reconciled = validate_success(api.reconcile_invoice(inv["id"], FIN))
    assert reconciled["status"] == "DISPUTED", f"expected DISPUTED, got {reconciled['status']}"
    assert reconciled["variance_cents"] != 0, "variance must be non-zero for a price mismatch"
    line_rows = validate_success(api.list_invoice_lines(FIN, params={"invoice_id": inv["id"]}))
    assert line_rows[0]["match_status"] == "PRICE_VARIANCE", (
        f"line billed 260000 vs matched 250000 should be PRICE_VARIANCE, got {line_rows[0]['match_status']}"
    )
