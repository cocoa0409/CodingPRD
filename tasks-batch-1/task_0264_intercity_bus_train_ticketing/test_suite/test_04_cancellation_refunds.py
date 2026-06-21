"""Cancellation, refunds, travel credit, the depth-3 service-date cancel cascade,
conserved-quantity restorations, and the pass exhaust/restore cycle.

Traces queue-A `dual_variant_calc` (refund_cash_vs_travel_credit_on_booking),
`transitive_cascade` (service_date_cancel_depth3_cash_refund),
`compensating_invariant` (pass_rides + seat_inventory), plus queue-B
`state_machines` (pass cyclic) and `errors` (not_paid).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_passenger_headers,
    TEST_USERS,
    assert_settlement_note,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _only_note(booking_id, passenger_id):
    notes = fx.settlement_notes_for_booking(booking_id, passenger_id)
    assert len(notes) == 1, f"expected exactly one settlement note, got {len(notes)}"
    return notes[0]


# ─── dual_variant_calc: refund cash vs travel credit ──
def test_travel_credit_refund_uses_lenient_penalty(api):
    """PRD §3.6: "For the travel-credit variant the penalty percentage is the base
    penalty percentage minus 0.10, floored at 0.00 ... A travel-credit refund moves
    `payment_status` from `PAID` to `CREDITED`".
    PRD §3.6: "if it is at least 1 day but fewer than 7 it is 0.25".

    total_paid 3600; cancel 2026-06-12, dbd=3 (vs departure 2026-06-15) => base 0.25;
    credit penalty 0.15 => penalty 540, net 3060.

    Design: Difficulty/dual_variant_calc/refund_cash_vs_travel_credit_on_booking
    """
    cat = fx.setup_paid_booking(refundable=True, base_fare_cents=4000, departure_date="2026-06-15")
    passenger = cat["passenger"]
    booking = cat["booking"]
    assert booking["total_paid_cents"] == 3600
    fx.set_clock("2026-06-12T00:00:00Z")

    resp = api.cancel_booking(
        booking["id"], f.cancel_payload("TRAVEL_CREDIT"), make_passenger_headers(passenger["id"])
    )
    after = validate_success(resp, 200)
    assert after["payment_status"] == "CREDITED"
    note = _only_note(booking["id"], passenger["id"])
    assert_settlement_note(note)
    assert note["settlement_kind"] == "TRAVEL_CREDIT"
    assert note["gross_cents"] == 3600
    assert note["penalty_cents"] == 540, f"credit penalty must be round(3600*0.15)=540, got {note['penalty_cents']}"
    assert note["net_cents"] == 3060


def test_cash_refund_uses_base_penalty(api):
    """PRD §3.6: "For the cash variant the penalty percentage is exactly the base
    penalty percentage ... A cash refund moves `payment_status` from `PAID` to
    `REFUNDED`".
    PRD §3.6: "if it is at least 1 day but fewer than 7 it is 0.25".

    Same total_paid 3600, same dbd=3 (base 0.25): cash penalty 900, net 2700 — a
    different number than the credit variant on identical inputs.

    Design: Difficulty/dual_variant_calc/refund_cash_vs_travel_credit_on_booking
    """
    cat = fx.setup_paid_booking(refundable=True, base_fare_cents=4000, departure_date="2026-06-15")
    passenger = cat["passenger"]
    booking = cat["booking"]
    assert booking["total_paid_cents"] == 3600
    fx.set_clock("2026-06-12T00:00:00Z")

    resp = api.cancel_booking(
        booking["id"], f.cancel_payload("CASH"), make_passenger_headers(passenger["id"])
    )
    after = validate_success(resp, 200)
    assert after["payment_status"] == "REFUNDED"
    note = _only_note(booking["id"], passenger["id"])
    assert note["settlement_kind"] == "CASH"
    assert note["gross_cents"] == 3600
    assert note["penalty_cents"] == 900, f"cash penalty must be round(3600*0.25)=900, got {note['penalty_cents']}"
    assert note["net_cents"] == 2700


# ─── transitive_cascade: depth-3 service-date cancel ──
def test_service_date_cancel_cascades_three_hops(api):
    """PRD §3.2: "Hop one: every `ACTIVE` booking leg whose `service_date_id` equals
    this trip has its owning booking force-cancelled, setting that booking's
    `booking_status` to `CANCELLED`. Hop two: each force-cancelled booking releases all
    of its legs, setting each `BookingLeg.leg_state` to `RELEASED`. Hop three runs three
    parallel restorations: each released leg's ticket, if currently `ISSUED`, is moved
    to `VOID` ... if the force-cancelled booking was a `PAID` cash booking, a cash
    settlement note is created with a penalty percentage of 0 (a full refund) and the
    booking's `payment_status` is set to `REFUNDED`".

    Design: Difficulty/transitive_cascade/service_date_cancel_depth3_cash_refund
    """
    cat = fx.setup_paid_booking(refundable=True, base_fare_cents=4000, departure_date="2026-06-15", seats_total=10)
    passenger = cat["passenger"]
    booking = cat["booking"]
    sd = cat["service_date"]

    resp = api.cancel_service_date(sd["id"], TEST_USERS["schedule_manager_headers"])
    sd_after = validate_success(resp, 200)
    assert sd_after["lifecycle"] == "CANCELLED"

    booking_after = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))
    assert booking_after["booking_status"] == "CANCELLED"
    assert booking_after["payment_status"] == "REFUNDED"

    legs = fx.legs_for_booking(booking["id"], passenger["id"])
    assert all(leg["leg_state"] == "RELEASED" for leg in legs), "hop2: every leg RELEASED"
    tickets = fx.tickets_for_booking(booking["id"])
    assert all(t["state"] == "VOID" for t in tickets), "hop3: every issued ticket VOID"

    note = _only_note(booking["id"], passenger["id"])
    assert note["settlement_kind"] == "CASH"
    assert note["penalty_cents"] == 0, "system cascade refund is full (penalty 0)"
    assert note["net_cents"] == 3600


def test_service_date_cancel_releases_sold_seat(api):
    """PRD §3.2: "each released leg's ticket, if currently `ISSUED`, is moved to `VOID`
    and the seat counters are recomputed".
    PRD §2.6: "The available count, `seats_available`, is the physical capacity
    `seats_total` minus `seats_held` minus `seats_sold`".

    After the cascade, the previously-sold seat returns to available: seats_sold 0.

    Design: Difficulty/transitive_cascade/service_date_cancel_depth3_cash_refund
    """
    cat = fx.setup_paid_booking(refundable=True, base_fare_cents=4000, departure_date="2026-06-15", seats_total=10)
    sd = cat["service_date"]
    api.cancel_service_date(sd["id"], TEST_USERS["schedule_manager_headers"])
    sd_after = get_success_data(api.get_service_date(sd["id"], TEST_USERS["schedule_manager_headers"]))
    assert sd_after["seats_sold"] == 0, f"cascade must release the sold seat, got {sd_after['seats_sold']}"


# ─── compensating_invariant: pass rides conserved ──
def test_pass_rides_conserved_on_confirm_then_cancel(api):
    """PRD §3.10: "A pass-funded booking confirm consumes one ride per leg; a
    cancellation or service-date cascade restores them by decrementing
    `rides_consumed`." and "`rides_remaining`, which is `rides_total` minus
    `rides_consumed` and is never allowed to go negative".

    Confirm: consumed 1 / remaining 9 (sum 10). Cancel: consumed 0 / remaining 10
    (sum still 10, no drift).

    Design: Difficulty/compensating_invariant/pass_rides_conserved_on_cancel
    """
    cat = fx.setup_pass_booking_confirmed(rides_total=10)
    passenger = cat["passenger"]
    booking = cat["booking"]
    travel_pass = cat["travel_pass"]

    before = get_success_data(api.get_pass(travel_pass["id"], make_passenger_headers(passenger["id"])))
    assert before["rides_consumed"] == 1 and before["rides_remaining"] == 9
    assert before["rides_consumed"] + before["rides_remaining"] == 10

    get_success_data(api.cancel_booking(booking["id"], f.cancel_payload(), make_passenger_headers(passenger["id"])))
    after = get_success_data(api.get_pass(travel_pass["id"], make_passenger_headers(passenger["id"])))
    assert after["rides_consumed"] == 0 and after["rides_remaining"] == 10
    assert after["rides_consumed"] + after["rides_remaining"] == 10


def test_pass_rides_invariant_holds_after_confirm(api):
    """PRD §3.10: "`rides_remaining`, which is `rides_total` minus `rides_consumed` and
    is never allowed to go negative." and "A pass-funded booking confirm consumes one
    ride per leg".

    On a rides_total=2 pass, a single-leg confirm consumes 1: consumed 1, remaining 1,
    and the conserved sum consumed + remaining == rides_total holds at the confirm step.

    Design: Difficulty/compensating_invariant/pass_rides_conserved_on_cancel
    """
    cat = fx.setup_pass_booking_confirmed(rides_total=2)
    passenger = cat["passenger"]
    travel_pass = cat["travel_pass"]
    after = get_success_data(api.get_pass(travel_pass["id"], make_passenger_headers(passenger["id"])))
    assert after["rides_consumed"] == 1
    assert after["rides_remaining"] == 1
    assert after["rides_consumed"] + after["rides_remaining"] == after["rides_total"] == 2


# ─── compensating_invariant: seat inventory conserved ──
def test_seat_inventory_conserved_on_confirm_then_cancel(api):
    """PRD §2.6: "The available count, `seats_available`, is the physical capacity
    `seats_total` minus `seats_held` minus `seats_sold`; this value is an invariant
    that is never allowed to go negative."
    PRD §3.6: "every `ACTIVE` leg is set to `RELEASED`, each affected service date's
    `seats_sold` decreases by 1 with counters and `load_factor` recomputed".

    Before cancel: sold 1, held 0, available 9 (sum 10). After: sold 0, held 0,
    available 10 (sum still 10).

    Design: Difficulty/compensating_invariant/seat_inventory_conserved_on_cancel
    """
    cat = fx.setup_paid_booking(refundable=True, base_fare_cents=4000, departure_date="2026-06-15", seats_total=10)
    passenger = cat["passenger"]
    booking = cat["booking"]
    sd = cat["service_date"]

    before = get_success_data(api.get_service_date(sd["id"], TEST_USERS["schedule_manager_headers"]))
    assert before["seats_sold"] == 1 and before["seats_held"] == 0 and before["seats_available"] == 9
    assert before["seats_held"] + before["seats_sold"] + before["seats_available"] == 10

    get_success_data(api.cancel_booking(booking["id"], f.cancel_payload("CASH"), make_passenger_headers(passenger["id"])))
    after = get_success_data(api.get_service_date(sd["id"], TEST_USERS["schedule_manager_headers"]))
    assert after["seats_sold"] == 0 and after["seats_held"] == 0 and after["seats_available"] == 10
    assert after["seats_held"] + after["seats_sold"] + after["seats_available"] == 10


def test_seat_inventory_sum_holds_with_mixed_held_and_sold(api):
    """PRD §2.6: "The available count, `seats_available`, is the physical capacity
    `seats_total` minus `seats_held` minus `seats_sold`; this value is an invariant
    that is never allowed to go negative."

    With one CONFIRMED (sold) and one HELD leg on a seats_total=10 trip, the three
    counters still sum exactly to seats_total: sold 1 + held 1 + available 8 == 10.

    Design: Difficulty/compensating_invariant/seat_inventory_conserved_on_cancel
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10, "base_fare_cents": 4000})
    p_sold = fx.create_passenger(full_name="Sold", email="sold@x.com")
    fx.hold_and_confirm(p_sold["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    p_held = fx.create_passenger(full_name="Held", email="held@x.com")
    fx.hold_booking(p_held["id"], cat["service_date"]["id"], cat["fare_class"]["id"])

    sd = get_success_data(api.get_service_date(cat["service_date"]["id"], TEST_USERS["schedule_manager_headers"]))
    assert sd["seats_sold"] == 1
    assert sd["seats_held"] == 1
    assert sd["seats_available"] == 8
    assert sd["seats_held"] + sd["seats_sold"] + sd["seats_available"] == sd["seats_total"] == 10


# ─── state_machines (corner): pass exhaust then restore ──
def test_pass_exhausts_then_restores_on_cancel(api):
    """PRD §3.10: "The pass status is re-derived from the balance: when
    `rides_remaining` reaches 0 the pass auto-transitions from `ACTIVE` to `EXHAUSTED`,
    and when a restore brings `rides_remaining` back above 0 an `EXHAUSTED` pass reverts
    to `ACTIVE`."

    A rides_total=1 pass goes ACTIVE->EXHAUSTED on confirm, then EXHAUSTED->ACTIVE
    when the booking is cancelled.

    Design: Corner/state_machines/pass_exhausts_then_restores_revert
    """
    cat = fx.setup_pass_booking_confirmed(rides_total=1)
    passenger = cat["passenger"]
    booking = cat["booking"]
    travel_pass = cat["travel_pass"]

    before = get_success_data(api.get_pass(travel_pass["id"], make_passenger_headers(passenger["id"])))
    assert before["status"] == "EXHAUSTED" and before["rides_remaining"] == 0

    get_success_data(api.cancel_booking(booking["id"], f.cancel_payload(), make_passenger_headers(passenger["id"])))
    after = get_success_data(api.get_pass(travel_pass["id"], make_passenger_headers(passenger["id"])))
    assert after["status"] == "ACTIVE"
    assert after["rides_remaining"] == 1


# ─── validations (corner): cash refund blocked on non-refundable ──
def test_cash_refund_blocked_on_nonrefundable_fare(api):
    """PRD §3.6: "A cash refund moves `payment_status` from `PAID` to `REFUNDED` and is
    permitted for a passenger only when every leg's fare class is refundable; if any
    leg's fare class has `refundable` false, a cash refund is rejected with
    `ERR_REFUND_NOT_ALLOWED` and only travel credit is available."

    Design: Corner/validations/cash_refund_blocked_on_nonrefundable_fare
    """
    cat = fx.setup_paid_booking(refundable=False, base_fare_cents=4000, departure_date="2026-06-15")
    passenger = cat["passenger"]
    booking = cat["booking"]
    resp = api.cancel_booking(
        booking["id"], f.cancel_payload("CASH"), make_passenger_headers(passenger["id"])
    )
    validate_error(resp, ApiErrorId.ERR_REFUND_NOT_ALLOWED.value, 409)
    after = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))
    assert after["payment_status"] == "PAID"


# ─── errors (corner): not paid blocks exchange ──
def test_not_paid_blocks_exchange(api):
    """PRD §3.6: "a refund/exchange attempted on a booking that is not paid, is
    rejected with `ERR_NOT_PAID` where the booking is not in a paid state."

    A CONFIRMED-but-UNPAID cash booking cannot be exchanged.

    Design: Corner/errors/not_paid_blocks_exchange
    """
    fx.set_clock()
    operator = fx.create_operator(exchange_fee_cents=1000)
    fare_class = fx.create_fare_class(operator["id"])
    route = fx.create_published_route(operator["id"])
    sd1 = fx.create_service_date(route["id"], seats_total=10, base_fare_cents=4000, departure_date="2026-06-15")
    sd2 = fx.create_service_date(route["id"], seats_total=10, base_fare_cents=4000, departure_date="2026-06-16")
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], sd1["id"], fare_class["id"])
    confirmed = fx.confirm_booking(booking["id"], passenger["id"], sd1["id"])
    b_v = confirmed["version"]
    resp = api.exchange_booking(
        booking["id"], f.exchange_payload(sd2["id"], fare_class["id"], b_v),
        make_passenger_headers(passenger["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_PAID.value, 409)
    after = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))
    assert after["booking_status"] == "CONFIRMED"
