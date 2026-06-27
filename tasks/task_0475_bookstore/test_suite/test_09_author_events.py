"""Author events & ticketing: pinned-order ticket pricing, sold-out seat quota,
past-event guard, cancel cascade refunds, and refund credit reconciliation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    create_author_event_payload, book_ticket_payload, create_title_payload,
    make_member, make_title,
    setup_event, setup_event_with_ticket,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]
ADMIN = TEST_USERS["store_admin_headers"]


def _book(api, event_id, member):
    mh = make_member_headers(member["id"])
    return api.book_ticket(event_id, book_ticket_payload(member["id"]), mh)


def test_ticket_price_high_demand_gold_surcharge_then_discount(api):
    """PRD §3.10: "when the featured title's `demand_flag` is `HIGH`, the surcharge
    is the event's `base_price_cents` multiplied by a high-demand surcharge of
    twenty-five hundredths, rounded half-up to whole cents". And: "The gross price
    is the `base_price_cents` plus that surcharge. It then forms a discount: for a
    `GOLD` member the discount is the gross multiplied by five hundredths, rounded
    half-up to whole cents". And: "The ticket's `price_paid_cents` is the gross
    minus the discount, floored at zero."

    Design: Difficulty/combinatorial_formula/ticket_price_surcharge_then_discount_nonlinear
    """
    member = make_member(tier="GOLD")
    title = make_title(list_price_cents=3000, demand_flag="HIGH")
    event = validate_success(
        api.create_author_event(
            create_author_event_payload(title["id"], "2026-02-01T18:00:00Z",
                                        capacity=10, base_price_cents=2000),
            BOOKSELLER),
        expected_status=201,
    )
    resp = _book(api, event["id"], member)
    ticket = validate_success(resp, expected_status=201)
    # base 2000 + surcharge round(2000*0.25)=500 = gross 2500;
    # discount round(2500*0.05)=125; price 2375.
    assert ticket["price_paid_cents"] == 2375
    assert ticket["state"] == "BOOKED"


def test_ticket_price_discount_computed_on_post_surcharge_gross(api):
    """PRD §3.10: "The order is binding: surcharge from the base, add to get gross,
    discount from the gross, subtract."

    Design: Difficulty/combinatorial_formula/ticket_price_surcharge_then_discount_nonlinear
    """
    # Distinct numbers: base 4000, HIGH surcharge round(4000*0.25)=1000 -> gross 5000;
    # GOLD discount round(5000*0.05)=250 -> price 4750. Computing the discount on the
    # base (4000) instead of the gross would give 4000*0.05=200 -> 4800, a different value.
    member = make_member(tier="GOLD")
    title = make_title(list_price_cents=3000, demand_flag="HIGH")
    event = validate_success(
        api.create_author_event(
            create_author_event_payload(title["id"], "2026-02-01T18:00:00Z",
                                        capacity=10, base_price_cents=4000),
            BOOKSELLER),
        expected_status=201,
    )
    ticket = validate_success(_book(api, event["id"], member), expected_status=201)
    assert ticket["price_paid_cents"] == 4750


def test_ticket_price_regular_normal_is_base(api):
    """PRD §3.10: "otherwise the surcharge is zero" (NORMAL demand) and "for a
    `REGULAR` member it is zero" (discount). "The ticket's `price_paid_cents` is
    the gross minus the discount, floored at zero."

    Design: Corner/calculations/ticket_price_regular_normal_is_base
    """
    member = make_member(tier="REGULAR")
    title = make_title(list_price_cents=1000, demand_flag="NORMAL")
    event = validate_success(
        api.create_author_event(
            create_author_event_payload(title["id"], "2026-07-01T18:00:00Z",
                                        capacity=5, base_price_cents=2000),
            BOOKSELLER),
        expected_status=201,
    )
    ticket = validate_success(_book(api, event["id"], member), expected_status=201)
    assert ticket["price_paid_cents"] == 2000


def test_book_sold_out_capacity_one_rejected(api):
    """PRD §3.10: "a seat must be available: the event's `tickets_sold` must be
    below its `capacity`, and a booking once sold-out is rejected with
    `ERR_EVENT_SOLD_OUT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/event_sold_out_at_exact_capacity_empty_seat_set
    """
    title = make_title(list_price_cents=1000)
    event = validate_success(
        api.create_author_event(
            create_author_event_payload(title["id"], "2026-04-01T18:00:00Z",
                                        capacity=1, base_price_cents=1000),
            BOOKSELLER),
        expected_status=201,
    )
    m1 = make_member()
    m2 = make_member()
    validate_success(_book(api, event["id"], m1), expected_status=201)
    resp = _book(api, event["id"], m2)
    validate_error(resp, ApiErrorId.ERR_EVENT_SOLD_OUT)


def test_book_at_capacity_minus_one_still_succeeds(api):
    """PRD §3.10: "the event's `tickets_sold` must be below its `capacity`".

    Design: Difficulty/boundary_precision_check/event_sold_out_at_exact_capacity_empty_seat_set
    """
    title = make_title(list_price_cents=1000)
    event = validate_success(
        api.create_author_event(
            create_author_event_payload(title["id"], "2026-04-01T18:00:00Z",
                                        capacity=1, base_price_cents=1000),
            BOOKSELLER),
        expected_status=201,
    )
    m1 = make_member()
    # tickets_sold 0 < capacity 1 -> the single seat books successfully.
    ticket = validate_success(_book(api, event["id"], m1), expected_status=201)
    assert ticket["state"] == "BOOKED"
    ev = validate_success(api.get_author_event(event["id"], BOOKSELLER))
    assert ev["tickets_sold"] == 1


def test_seat_quota_overlap_third_booking_rejected(api):
    """PRD §3.10: "a booking once sold-out is rejected with `ERR_EVENT_SOLD_OUT`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/event_seat_quota_overlap_on_capacity
    """
    title = make_title(list_price_cents=1000)
    event = validate_success(
        api.create_author_event(
            create_author_event_payload(title["id"], "2026-05-01T18:00:00Z",
                                        capacity=2, base_price_cents=1000),
            BOOKSELLER),
        expected_status=201,
    )
    ma, mb, mc = make_member(), make_member(), make_member()
    validate_success(_book(api, event["id"], ma), expected_status=201)
    validate_success(_book(api, event["id"], mb), expected_status=201)
    resp = _book(api, event["id"], mc)
    validate_error(resp, ApiErrorId.ERR_EVENT_SOLD_OUT)


def test_seat_quota_fills_exactly_to_capacity(api):
    """PRD §3.10: "the event's `tickets_sold` must be below its `capacity`".

    Design: Difficulty/resource_temporal_overlap/event_seat_quota_overlap_on_capacity
    """
    title = make_title(list_price_cents=1000)
    event = validate_success(
        api.create_author_event(
            create_author_event_payload(title["id"], "2026-05-01T18:00:00Z",
                                        capacity=2, base_price_cents=1000),
            BOOKSELLER),
        expected_status=201,
    )
    ma, mb = make_member(), make_member()
    validate_success(_book(api, event["id"], ma), expected_status=201)
    validate_success(_book(api, event["id"], mb), expected_status=201)
    ev = validate_success(api.get_author_event(event["id"], BOOKSELLER))
    assert ev["tickets_sold"] == 2, "two bookings fill capacity 2 exactly"


def test_book_past_event_rejected(api):
    """PRD §3.10: "the event must lie in the future: its `starts_at` must be
    strictly after the current logical clock, and a booking on an event that does
    not start strictly after now is rejected with `ERR_EVENT_PAST` (HTTP 422)."

    Design: Corner/validations/book_ticket_on_past_event_rejected
    """
    title = make_title(list_price_cents=1000)
    event = validate_success(
        api.create_author_event(
            create_author_event_payload(title["id"], "2026-08-01T18:00:00Z",
                                        capacity=5, base_price_cents=1000),
            BOOKSELLER),
        expected_status=201,
    )
    member = make_member()
    # Advance the clock past the event's start.
    validate_success(api.set_clock("2026-08-02T00:00:00Z", ADMIN))
    resp = _book(api, event["id"], member)
    validate_error(resp, ApiErrorId.ERR_EVENT_PAST)


def test_event_cancel_refunds_booked_ticket(api):
    """PRD §3.10: "**Cancelling** the whole event ... cascades a refund to every
    still-booked seat: each `BOOKED` ticket transitions to `REFUNDED`, each
    appending a `CreditLedgerEntry` with `reason` `EVENT_REFUND` and a positive
    `delta_cents` equal to that ticket's `price_paid_cents` to its holder and
    recomputing that holder's `store_credit_cents`."

    Design: Difficulty/transitive_cascade/event_cancel_to_tickets_refunded_to_member_credit
    """
    ctx = setup_event_with_ticket(starts_at="2026-03-01T18:00:00Z", capacity=5,
                                  base_price_cents=2000, demand_flag="NORMAL",
                                  member_tier="REGULAR", list_price_cents=1500)
    validate_success(api.cancel_author_event(ctx["event"]["id"], BOOKSELLER))
    ticket = validate_success(api.get_event_ticket(ctx["ticket"]["id"], BOOKSELLER))
    assert ticket["state"] == "REFUNDED"
    member = validate_success(api.get_member(ctx["member"]["id"], ADMIN))
    assert member["store_credit_cents"] == 2000


def test_event_cancel_recomputes_tickets_sold(api):
    """PRD §3.10: "The event's `tickets_sold` is then recomputed and its `version`
    increments."

    Design: Difficulty/transitive_cascade/event_cancel_to_tickets_refunded_to_member_credit
    """
    ctx = setup_event_with_ticket(starts_at="2026-03-01T18:00:00Z", capacity=5,
                                  base_price_cents=2000, demand_flag="NORMAL",
                                  member_tier="REGULAR", list_price_cents=1500)
    cancelled = validate_success(api.cancel_author_event(ctx["event"]["id"],
                                                        BOOKSELLER))
    assert cancelled["state"] == "CANCELLED"
    assert cancelled["tickets_sold"] == 0, \
        "refunded tickets are no longer BOOKED, so tickets_sold recomputes to 0"


def test_cancel_event_twice_rejected(api):
    """PRD §3.10: "The event starts `SCHEDULED` with `tickets_sold` at zero; its
    alternate state is `CANCELLED`."
    PRD §2.5: "Only then does the system check that the target resource is in a
    state from which the requested transition is defined (`ERR_INVALID_STATE`,
    409)."

    Design: Corner/state_machines/terminal_event_cancel_twice_returns_invalid_state
    """
    ctx = setup_event(starts_at="2026-06-01T18:00:00Z", capacity=5,
                      base_price_cents=1000)
    validate_success(api.cancel_author_event(ctx["event"]["id"], BOOKSELLER))
    resp = api.cancel_author_event(ctx["event"]["id"], BOOKSELLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_ticket_refund_reconciles_member_balance(api):
    """PRD §3.10: "**Refunding** a ticket ... moves it from `BOOKED` to
    `REFUNDED`: it appends a `CreditLedgerEntry` with `reason` `EVENT_REFUND` and a
    positive `delta_cents` equal to the ticket's `price_paid_cents`, recomputes the
    holder's `store_credit_cents`".
    PRD §2.8: "Each `Member` carries a computed `store_credit_cents` balance that
    is, at all times, the sum of the `delta_cents` of every `CreditLedgerEntry`
    belonging to that member."

    Design: Corner/cross_cutting_complexity_layers/event_refund_credit_reconciles_member_balance
    """
    ctx = setup_event_with_ticket(starts_at="2026-09-01T18:00:00Z", capacity=5,
                                  base_price_cents=2000, demand_flag="NORMAL",
                                  member_tier="REGULAR", list_price_cents=1000)
    mh = make_member_headers(ctx["member"]["id"])
    refunded = validate_success(api.refund_ticket(ctx["ticket"]["id"], mh))
    assert refunded["state"] == "REFUNDED"
    member = validate_success(api.get_member(ctx["member"]["id"], ADMIN))
    assert member["store_credit_cents"] == 2000
