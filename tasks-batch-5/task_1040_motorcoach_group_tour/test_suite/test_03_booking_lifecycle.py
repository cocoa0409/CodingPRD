"""Booking confirmation: parallel dimensions, the guarantee cycle, and confirm-time guards."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_open_departure, add_confirmed_booking,
    create_booking, create_hotel_block, get_departure,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Parallel dimensions: reservation_status vs payment_status are independent axes
# ---------------------------------------------------------------------------

def test_confirm_with_deposit_only_sets_reservation_confirmed(api):
    """PRD §3.7: "Confirming a booking advances its reservation_status from DRAFT to
    CONFIRMED and is where the heavy consistency work happens."

    Design: Difficulty/non_linear_state_machine/booking_parallel_reservation_and_payment_dims
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5)
    bk = add_confirmed_booking(s["dep"]["id"], pax_count=2, rooms_requested=0)
    assert bk["reservation_status"] == "CONFIRMED", \
        f"expected CONFIRMED, got {bk['reservation_status']}"


def test_confirm_with_deposit_only_leaves_payment_deposit_paid(api):
    """PRD §3.6: "A booking becomes DEPOSIT_PAID once its amount_paid_cents reaches or
    exceeds its deposit_due_cents while still remaining below its booking_total_cents."

    Design: Difficulty/non_linear_state_machine/booking_parallel_reservation_and_payment_dims
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5)
    bk = add_confirmed_booking(s["dep"]["id"], pax_count=2, rooms_requested=0)
    # Deposit 40000 paid, still below booking_total -> DEPOSIT_PAID, not forced to a terminal.
    assert bk["payment_status"] == "DEPOSIT_PAID", \
        f"expected DEPOSIT_PAID alongside CONFIRMED, got {bk['payment_status']}"


# ---------------------------------------------------------------------------
# Departure OPEN <-> GUARANTEED cycle driven by confirm / cancel
# ---------------------------------------------------------------------------

def test_confirm_reaching_min_advances_open_to_guaranteed(api):
    """PRD §3.2: "When a booking is confirmed and the departure's resulting confirmed_pax
    reaches or exceeds its guaranteed_min_pax, the departure automatically advances from
    OPEN to GUARANTEED with no field reset."

    Design: Difficulty/non_linear_state_machine/departure_cyclic_open_guaranteed_open
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=2)
    dep_id = s["dep"]["id"]
    add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    dep = get_departure(dep_id)
    assert dep["confirmed_pax"] == 2 and dep["status"] == "GUARANTEED", \
        f"expected GUARANTEED at confirmed_pax 2, got {dep['status']}/{dep['confirmed_pax']}"


def test_cancel_dropping_below_min_reverts_guaranteed_to_open(api, sales_headers):
    """PRD §3.2: "Conversely, when a cancellation drops confirmed_pax back below
    guaranteed_min_pax, a GUARANTEED departure reverts to OPEN."

    Design: Difficulty/non_linear_state_machine/departure_cyclic_open_guaranteed_open
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=2)
    dep_id = s["dep"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    validate_success(api.cancel_booking(bk["id"], {"reason": "cycle back"}, sales_headers))
    dep = get_departure(dep_id)
    assert dep["confirmed_pax"] == 0 and dep["status"] == "OPEN", \
        f"expected OPEN at confirmed_pax 0, got {dep['status']}/{dep['confirmed_pax']}"


# ---------------------------------------------------------------------------
# Guarantee threshold boundary: confirmed_pax exactly == guaranteed_min_pax
# ---------------------------------------------------------------------------

def test_guarantee_boundary_pax_exactly_equals_min_flips_guaranteed(api):
    """PRD §3.2: "When a booking is confirmed and the departure's resulting confirmed_pax
    reaches or exceeds its guaranteed_min_pax, the departure automatically advances from
    OPEN to GUARANTEED with no field reset."

    Design: Difficulty/boundary_precision_check/guarantee_threshold_pax_exactly_equals_min
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=2)
    dep_id = s["dep"]["id"]
    add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    dep = get_departure(dep_id)
    assert dep["confirmed_pax"] == 2, f"expected confirmed_pax 2, got {dep['confirmed_pax']}"
    assert dep["status"] == "GUARANTEED", f"expected GUARANTEED at the >= boundary, got {dep['status']}"


def test_guarantee_boundary_pax_one_below_min_stays_open(api):
    """PRD §3.2: "When a booking is confirmed and the departure's resulting confirmed_pax
    reaches or exceeds its guaranteed_min_pax, the departure automatically advances from
    OPEN to GUARANTEED with no field reset."

    Design: Difficulty/boundary_precision_check/guarantee_threshold_pax_exactly_equals_min
    """
    # min 3, confirm 2 -> below boundary -> no flip.
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=3)
    dep_id = s["dep"]["id"]
    add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    dep = get_departure(dep_id)
    assert dep["confirmed_pax"] == 2, f"expected confirmed_pax 2, got {dep['confirmed_pax']}"
    assert dep["status"] == "OPEN", f"expected OPEN below the boundary, got {dep['status']}"


# ---------------------------------------------------------------------------
# Confirm-time business guards (each in an isolated single-failure scenario)
# ---------------------------------------------------------------------------

def test_confirm_exceeding_coach_capacity_rejected(api, sales_headers):
    """PRD §3.7: "if a coach is assigned, the departure's confirmed_pax plus this booking's
    pax_count must not exceed that coach's seat_capacity, or the confirm is rejected with
    ERR_COACH_CAPACITY_EXCEEDED"

    Design: Corner/validations/corner_coach_capacity_exceeded_on_confirm
    """
    s = setup_open_departure(coach=True, seat_capacity=1, guaranteed_min_pax=5)
    dep_id = s["dep"]["id"]
    bk = fx.create_booking(dep_id, pax_count=2, rooms_requested=0)
    fx.add_passenger(bk["id"], full_name="P1", is_lead=True)
    fx.add_passenger(bk["id"], full_name="P2")
    fx.pay(bk["id"], "DEPOSIT", bk["deposit_due_cents"])
    resp = api.confirm_booking(bk["id"], sales_headers)
    validate_error(resp, ApiErrorId.ERR_COACH_CAPACITY_EXCEEDED.value)


def test_confirm_passenger_count_mismatch_rejected(api, sales_headers):
    """PRD §3.7: "the number of passengers actually attached to the booking must equal its
    pax_count, or it is rejected with ERR_PASSENGER_COUNT_MISMATCH"

    Design: Corner/validations/corner_passenger_count_mismatch_on_confirm
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5)
    dep_id = s["dep"]["id"]
    bk = fx.create_booking(dep_id, pax_count=2, rooms_requested=0)
    fx.add_passenger(bk["id"], full_name="Solo", is_lead=True)  # only 1 of 2
    fx.pay(bk["id"], "DEPOSIT", bk["deposit_due_cents"])
    resp = api.confirm_booking(bk["id"], sales_headers)
    validate_error(resp, ApiErrorId.ERR_PASSENGER_COUNT_MISMATCH.value)


def test_confirm_insufficient_hotel_block_rejected(api, sales_headers):
    """PRD §3.7: "for each hotel block, the block's rooms_committed plus this booking's
    rooms_requested must not exceed the block's room_count, or it is rejected with
    ERR_HOTEL_BLOCK_INSUFFICIENT"

    Design: Corner/validations/corner_hotel_block_insufficient_on_confirm
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5)
    dep_id = s["dep"]["id"]
    create_hotel_block(dep_id, hotel_name="Tiny Inn", city="DC", room_count=0,
                       nights=1, rate_per_room_night_cents=12000)
    bk = fx.create_booking(dep_id, pax_count=2, rooms_requested=1)
    fx.add_passenger(bk["id"], full_name="H1", is_lead=True)
    fx.add_passenger(bk["id"], full_name="H2")
    fx.pay(bk["id"], "DEPOSIT", bk["deposit_due_cents"])
    resp = api.confirm_booking(bk["id"], sales_headers)
    validate_error(resp, ApiErrorId.ERR_HOTEL_BLOCK_INSUFFICIENT.value)


def test_confirm_without_deposit_rejected(api, sales_headers):
    """PRD §3.7: "Finally, the deposit must be paid — the booking's payment_status must be
    DEPOSIT_PAID or PAID_IN_FULL, otherwise the confirm is rejected with ERR_DEPOSIT_UNPAID."

    Design: Corner/validations/corner_deposit_unpaid_on_confirm
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5)
    dep_id = s["dep"]["id"]
    bk = fx.create_booking(dep_id, pax_count=2, rooms_requested=0)
    fx.add_passenger(bk["id"], full_name="U1", is_lead=True)
    fx.add_passenger(bk["id"], full_name="U2")
    # No payment recorded.
    resp = api.confirm_booking(bk["id"], sales_headers)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_UNPAID.value)
