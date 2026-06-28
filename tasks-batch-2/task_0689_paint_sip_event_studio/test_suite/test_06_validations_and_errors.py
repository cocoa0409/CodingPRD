"""Event-config validation, BYOB gate, roster completeness, credit overdraw, and
depleted-gift-card payment rejection.

Corner queue (B): validations + errors sections.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_customer_headers, TEST_USERS, ApiErrorId,
    create_studio, create_artist, create_customer, create_gift_card,
    setup_open_event_with_customer, book_reservation, pay_reservation,
    confirm_reservation, add_attendees, event_current_version, set_clock,
)

MANAGER = TEST_USERS["manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_event_config_capacity_over_room_rejected(api):
    """PRD §3.2: "The event declares seats_capacity, its total bookable seats (at
    least 1), which must not exceed the hosting studio's room_capacity_seats ... if
    seats_capacity exceeds the host studio's room_capacity_seats ... the create is
    rejected with ERR_INVALID_EVENT_CONFIG (HTTP 422)."

    Design: Corner/validations/event_config_capacity_over_room
    """
    studio = create_studio(room_capacity_seats=5, name="V1")
    resp = api.create_event({
        "studio_id": studio["id"], "title": "Too Big", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 50, "price_cents_per_seat": 4500}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_CONFIG)


def test_fundraiser_zero_pct_config_rejected(api):
    """PRD §3.2: "fundraiser_donation_pct ... is required to be between 1 and 100
    inclusive when the event_type is FUNDRAISER, and it must be 0 for every other
    event type ... or the fundraiser-percent rule is violated for the chosen
    event_type, the create is rejected with ERR_INVALID_EVENT_CONFIG (HTTP 422)."

    Design: Corner/validations/fundraiser_pct_required_config_error
    """
    studio = create_studio(room_capacity_seats=30, name="V2")
    resp = api.create_event({
        "studio_id": studio["id"], "title": "Bad Fund", "event_type": "FUNDRAISER",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 30, "price_cents_per_seat": 4500,
        "fundraiser_donation_pct": 0}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_CONFIG)


def test_byob_check_in_underage_unsigned_waiver_fail(api):
    """PRD §3.6: "if the event is byob_allowed, every attendee must have waiver_signed
    true and an age_years of at least the event's min_age; any attendee failing either
    part is rejected with ERR_WAIVER_OR_AGE_FAIL (HTTP 422)."

    Design: Corner/validations/byob_check_in_underage_waiver_fail
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500,
        clock=None, byob_allowed=True, min_age=21)
    res = book_reservation(event["id"], customer["id"], seats=1)
    pay_reservation(res["id"], customer["id"])
    confirm_reservation(res["id"], customer["id"])
    # One attendee, age 18, no waiver — fails both halves of the gate.
    add_attendees(res["id"], customer["id"], 1, age_years=18, waiver_signed=False)

    resp = api.check_in_reservation(res["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_WAIVER_OR_AGE_FAIL)


def test_check_in_roster_incomplete_fail(api):
    """PRD §3.6: "The number of Attendee rows on the reservation must exactly equal the
    reservation's seats; a roster with too few or too many attendees is rejected with
    ERR_ATTENDEE_ROSTER_INCOMPLETE (HTTP 422)."

    Design: Corner/validations/roster_incomplete_check_in_fail
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=3)  # non-BYOB
    pay_reservation(res["id"], customer["id"])
    confirm_reservation(res["id"], customer["id"])
    add_attendees(res["id"], customer["id"], 1, age_years=40)  # only 1 of 3

    resp = api.check_in_reservation(res["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_ATTENDEE_ROSTER_INCOMPLETE)


def test_credit_debit_below_zero_rejected(api):
    """PRD §3.1: "A debit that would drive credit_balance_cents below 0 is rejected
    with ERR_CREDIT_INSUFFICIENT (HTTP 422)."

    Design: Corner/validations/credit_debit_below_zero_insufficient
    """
    customer = create_customer(email="v5@x.com", full_name="V5")
    resp = api.adjust_credit(customer["id"], {"amount_cents": -5000, "reason": "overdraw"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_CREDIT_INSUFFICIENT)
    after = get_success_data(api.get_customer(customer["id"], MANAGER))
    assert after["credit_balance_cents"] == 0, "rejected debit must not drive balance negative"


def test_pay_with_depleted_gift_card_rejected(api):
    """PRD §3.5: "Every gift card supplied to the waterfall must be ACTIVE; if any
    supplied card is DEPLETED (zero balance) when the waterfall reaches it, the
    payment is rejected with ERR_GIFT_CARD_DEPLETED (HTTP 422)."
    PRD §3.1: "The moment a redemption brings balance_cents to exactly 0, the card
    automatically transitions to DEPLETED and is no longer tappable."

    Design: Corner/errors/pay_with_depleted_gift_card_returns_depleted
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=20, seats_capacity=20, price_cents_per_seat=4500, clock=None)
    gc = create_gift_card(code="GC-DEP", issued_value_cents=5000)
    cid = customer["id"]
    # First reservation fully drains the 5000 card to 0: 2 seats = 9000 total, card
    # draws min(5000, 9000) = 5000 (balance -> 0 -> DEPLETED), remainder 4000 to CARD.
    r1 = book_reservation(event["id"], cid, seats=2)
    pay_reservation(r1["id"], cid, gift_card_ids=[gc["id"]])
    gc_after = get_success_data(api.get_gift_card(gc["id"], MANAGER))
    assert gc_after["status"] == "DEPLETED", f"card depleted after first pay, got {gc_after['status']}"

    # Second reservation supplied the now-DEPLETED card.
    r2 = book_reservation(event["id"], cid, seats=3)
    resp = api.pay_reservation(r2["id"],
                               {"gift_card_ids": [gc["id"]], "use_studio_credit": False},
                               make_customer_headers(cid))
    validate_error(resp, ApiErrorId.ERR_GIFT_CARD_DEPLETED)
