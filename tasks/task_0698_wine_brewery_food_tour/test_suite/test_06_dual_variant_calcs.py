"""Dual-variant commission (estimated vs settled), dual-path refund (weather full
vs ops tiered), the money-conservation invariant, and the 48h refund boundary.

Queue A: dual_variant_calc, compensating_invariant (money).
Queue B: calculations section (refund 48h boundary).
"""
from test_helpers import (
    validate_success,
    make_operator_headers, make_guide_headers, make_guest_headers,
    get_success_data,
    setup_two_parallel_paid_departures,
    setup_scheduled_departure_with_confirmed_stop,
    create_paid_booking, create_guest_payload, create_booking_payload,
)
from test_helpers import api_client

OP = make_operator_headers()
GUIDE = make_guide_headers()


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc
# ---------------------------------------------------------------------------
def test_commission_estimated_vs_settled_diverge_on_stop(api):
    """PRD §3.7: "The **estimated** variant runs when a departure is confirmed
    (`SCHEDULED → CONFIRMED`): its headcount is the forward-looking sum of
    `party_size` over the departure's bookings in `RESERVED` or `PAID`, and it
    is written to each stop's `estimated_commission_cents`. The **settled**
    variant runs when a departure completes (`DEPARTED → COMPLETED`): its
    headcount is the sum of `party_size` over only the departure's `CHECKED_IN`
    bookings — actual attendance, with no-shows excluded — and it is written to
    each stop's `settled_commission_cents`."

    Design: Difficulty/dual_variant_calc/commission_estimated_vs_settled_diverge_on_stop
    """
    # venue tasting 1200/guest, commission 0.10, seat_capacity 12, one CONFIRMED stop.
    s = setup_scheduled_departure_with_confirmed_stop(
        seat_capacity=12, requested_headcount=12,
        venue_overrides={"name": "Oak Ridge", "kind": "WINERY",
                         "commission_pct": 0.10, "tasting_cost_per_guest_cents": 1200},
        product_overrides={"base_price_per_person_cents": 9000, "gratuity_pct": 0.18,
                           "charter_fee_cents": 5000})
    dep_id = s["departure"]["id"]
    pickup_id = s["pickup"]["id"]
    stop_id = s["stop"]["id"]
    # BX: cleared guest, party 6, PAID (will check in).
    bx, _ = create_paid_booking(dep_id, pickup_id, 6)
    # BZ: party 6 RESERVED only (uncaptured) -> auto-cancelled no-show at depart.
    gz = get_success_data(api.create_guest(create_guest_payload(full_name="Ben Lead"), OP))
    bz = get_success_data(api.create_booking(
        create_booking_payload(dep_id, gz["id"], pickup_id, 6), make_guest_headers(gz["id"])))
    dep_v = get_success_data(api.get_departure(dep_id, OP))["version"]
    get_success_data(api.reserve_booking(bz["id"], dep_v, make_guest_headers(gz["id"])))
    # Confirm: estimated headcount = RESERVED+PAID = 6 + 6 = 12 -> round(12*1200*0.10)=1440.
    get_success_data(api.confirm_departure(dep_id, OP))
    # Depart at depart_at: BZ (uncaptured) auto-cancelled; BX still PAID then checked in.
    get_success_data(api.set_clock("2026-04-10T18:00:00Z", OP))
    get_success_data(api.depart_departure(dep_id, GUIDE))
    get_success_data(api.check_in_booking(bx["id"], GUIDE))
    # Complete at return_at: settled headcount = CHECKED_IN = 6 -> round(6*1200*0.10)=720.
    get_success_data(api.set_clock("2026-04-10T23:00:00Z", OP))
    get_success_data(api.complete_departure(dep_id, GUIDE))
    stop = validate_success(api.get_stop(stop_id, OP))
    assert stop["estimated_commission_cents"] == 1440, \
        f"expected estimated 1440, got {stop['estimated_commission_cents']}"
    assert stop["settled_commission_cents"] == 720, \
        f"expected settled 720, got {stop['settled_commission_cents']}"
    assert stop["estimated_commission_cents"] != stop["settled_commission_cents"], \
        "estimated and settled commission must diverge with a no-show"


def test_refund_weather_full_vs_leadtime_tiered_on_booking(api):
    """PRD §3.8: "This is the weather-override path: every non-terminal booking
    is moved to `CANCELLED` with `refund_cents` set to 100 percent of its
    `amount_paid_cents`"
    PRD §3.8: "refunds are not a flat 100 percent but follow the lead-time refund
    rule against `depart_at`. Every non-terminal booking is moved to `CANCELLED`
    with `refund_cents` computed by that tiered rule"
    PRD §3.7: "if it is at least 48 hours but less than 168 hours, the refund is
    50 percent"

    Design: Difficulty/dual_variant_calc/refund_weather_full_vs_leadtime_tiered_on_booking
    """
    # Two parallel CONFIRMED departures, each one PAID party-6 cheese booking.
    # base 9000 tier 5% -> 8550*6=51300 seats; add-on 1500*6=9000; subtotal 60300;
    # gratuity round(60300*0.18)=10854; total=71154 -> amount_paid 71154.
    s = setup_two_parallel_paid_departures(party_size=6, add_on_price=1500,
                                           requested_headcount=6)
    # Clock to 72h before depart_at (2026-04-10T18:00) -> ops tier is 50%.
    get_success_data(api.set_clock("2026-04-07T18:00:00Z", OP))
    get_success_data(api.cancel_departure_weather(s["dw"]["id"], "storm", OP))
    get_success_data(api.cancel_departure_ops(s["do"]["id"], "vehicle reassigned", OP))
    bw = validate_success(api.get_booking(s["bw_id"], OP))
    bo = validate_success(api.get_booking(s["bo_id"], OP))
    assert bw["refund_cents"] == 71154, \
        f"weather refund expected 71154 (100%), got {bw['refund_cents']}"
    assert bo["refund_cents"] == 35577, \
        f"ops 72h refund expected 35577 (50%), got {bo['refund_cents']}"
    assert bw["refund_cents"] != bo["refund_cents"], \
        "weather (full) and ops-72h (tiered) refunds must diverge"


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant (money)
# ---------------------------------------------------------------------------
def test_payment_ledger_conserved_under_pay_then_weather_refund(api):
    """PRD §3.6: "Capturing payment sets the `payment_status` to `CAPTURED`,
    sets `amount_paid_cents` equal to `total_cents`"
    PRD §3.8: "every non-terminal booking is moved to `CANCELLED` with
    `refund_cents` set to 100 percent of its `amount_paid_cents`"

    Design: Difficulty/compensating_invariant/payment_ledger_conserved_under_pay_then_weather_refund
    """
    # CONFIRMED departure, one PAID party-6 cheese booking (amount_paid 71154).
    s = setup_scheduled_departure_with_confirmed_stop(
        seat_capacity=12, requested_headcount=6,
        venue_overrides={"name": "Oak", "kind": "WINERY", "commission_pct": 0.10,
                         "tasting_cost_per_guest_cents": 1200},
        product_overrides={"base_price_per_person_cents": 9000, "gratuity_pct": 0.18})
    addon = get_success_data(api.create_add_on(
        {"tour_product_id": s["product"]["id"], "name": "Cheese",
         "price_per_person_cents": 1500}, OP))
    booking, _ = create_paid_booking(s["departure"]["id"], s["pickup"]["id"], 6,
                                     add_on_id=addon["id"])
    assert booking["amount_paid_cents"] == 71154, \
        f"setup expected amount_paid 71154, got {booking['amount_paid_cents']}"
    get_success_data(api.confirm_departure(s["departure"]["id"], OP))
    get_success_data(api.cancel_departure_weather(s["departure"]["id"], "storm", OP))
    final = validate_success(api.get_booking(booking["id"], OP))
    assert final["amount_paid_cents"] == 71154, \
        f"expected amount_paid 71154, got {final['amount_paid_cents']}"
    assert final["refund_cents"] == 71154, \
        f"expected refund 71154 (100% weather), got {final['refund_cents']}"
    assert final["amount_paid_cents"] - final["refund_cents"] == 0, \
        "net charge (amount_paid - refund) must be conserved at 0"


# ---------------------------------------------------------------------------
# Queue B: calculations (refund 48h boundary)
# ---------------------------------------------------------------------------
def test_refund_leadtime_48h_boundary_exact(api):
    """PRD §3.7: "if it is at least 48 hours but less than 168 hours, the refund
    is 50 percent ... These boundaries are inclusive on the lower edge — exactly
    48 hours out yields 50 percent"

    Design: Corner/calculations/refund_leadtime_48h_boundary_exact
    """
    # base 8000, party 4, tier 5%: 7600*4=30400 seats; gratuity round(30400*0.18)=5472;
    # total 35872 -> amount_paid 35872. Cancel exactly 48h before -> 50% = 17936.
    from test_helpers import setup_scheduled_departure
    base = setup_scheduled_departure(seat_capacity=12,
                                     product_overrides={"base_price_per_person_cents": 8000,
                                                        "gratuity_pct": 0.18})
    booking, guest = create_paid_booking(base["departure"]["id"], base["pickup"]["id"], 4)
    assert booking["amount_paid_cents"] == 35872, \
        f"setup expected amount_paid 35872, got {booking['amount_paid_cents']}"
    # depart_at default is 2026-04-10T18:00; exactly 48h before -> 2026-04-08T18:00.
    get_success_data(api.set_clock("2026-04-08T18:00:00Z", OP))
    cancelled = validate_success(api.cancel_booking(booking["id"], make_guest_headers(guest["id"])))
    assert cancelled["refund_cents"] == 17936, \
        f"expected 50% refund 17936 at exactly 48h, got {cancelled['refund_cents']}"
