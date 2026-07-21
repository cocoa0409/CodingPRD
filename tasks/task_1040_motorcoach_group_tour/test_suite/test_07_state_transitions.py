"""Invalid / terminal state transitions and idempotency guards."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_tour_product, create_departure,
    setup_open_departure, add_confirmed_booking, first_voucher_id,
)
from test_helpers import fixtures as fx


def test_publish_already_open_departure_rejected(api, ops_headers):
    """PRD §3.2: "Publishing a departure advances it from PLANNING to OPEN and requires
    that it have at least one entry in its itinerary_days; once OPEN, bookings against it
    may be confirmed."

    Design: Corner/state_machines/corner_publish_twice_returns_invalid_state
    """
    tp = create_tour_product()
    dep = create_departure(tp["id"])
    fx.publish_departure(dep["id"])  # PLANNING -> OPEN
    resp = api.publish_departure(dep["id"], ops_headers)  # OPEN is not a valid from-state
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_departure_rejected(api, ops_headers):
    """PRD §2.8: "a departure already in a terminal state (CANCELLED or SETTLED) is rejected
    with ERR_DEPARTURE_TERMINAL ahead of the operation-specific business rules; this applies
    to departure publish, assign, depart, cancel, and settle, and to hotel-block confirm."

    Design: Corner/state_machines/corner_cancel_departure_twice_returns_terminal
    """
    tp = create_tour_product()
    dep = create_departure(tp["id"])
    fx.publish_departure(dep["id"])
    validate_success(api.cancel_departure(dep["id"], {"reason": "first cancel"}, ops_headers))
    resp = api.cancel_departure(dep["id"], {"reason": "second cancel"}, ops_headers)
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_TERMINAL.value)


def test_redeem_already_redeemed_voucher_rejected(api, sales_headers):
    """PRD §3.9: "Redemption is permitted only when the voucher is currently ISSUED;
    redeeming a voucher in any other status is rejected with ERR_VOUCHER_NOT_ISSUED."

    Design: Corner/state_machines/corner_voucher_redeem_twice_returns_not_issued
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=2)
    bk = add_confirmed_booking(s["dep"]["id"], pax_count=2, rooms_requested=0)
    vid = first_voucher_id(bk["id"])
    validate_success(api.redeem_voucher(vid, sales_headers))  # ISSUED -> REDEEMED
    resp = api.redeem_voucher(vid, sales_headers)
    validate_error(resp, ApiErrorId.ERR_VOUCHER_NOT_ISSUED.value)


def test_depart_without_full_crew_rejected(api, ops_headers):
    """PRD §3.2: "The precondition checked at this step is that a coach, driver, and guide
    are all assigned — that coach_id, driver_id, and guide_id are all set; if any is missing
    the request is rejected with ERR_DEPARTURE_NOT_ASSIGNED."

    Design: Corner/validations/corner_depart_missing_crew_returns_not_assigned
    """
    # Only a coach assigned; booking drives the departure to GUARANTEED.
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=2)
    dep_id = s["dep"]["id"]
    add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    resp = api.depart_departure(dep_id, ops_headers)
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_NOT_ASSIGNED.value)
