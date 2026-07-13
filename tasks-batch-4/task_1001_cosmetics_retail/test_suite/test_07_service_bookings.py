"""In-store services: the reschedule cycle, the artist's buffered interval, completion."""

from test_helpers import (
    ApiErrorId,
    assert_service_booking,
    book_service,
    create_booking_payload,
    make_artist_headers,
    make_customer_headers,
    new_customer,
    new_store,
    read_booking,
    read_customer,
    read_ledger,
    setup_artist_and_customer,
    setup_booking_at_max_reschedules,
    setup_booking_linked_to_order,
    setup_confirmed_booking,
    setup_draft_order,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ARTIST_ID = "44444444-4444-4444-8444-444444444444"
UNKNOWN_BOOKING_ID = "88888888-8888-4888-8888-888888888888"


# ─── The reschedule cycle ─────────────────────────────

def test_reschedule_cycle_returns_the_booking_to_confirmed(api):
    """PRD §3.8: "A `Customer` may propose a new time, supplying `proposed_start_at`;
    the booking moves from `CONFIRMED` to `RESCHEDULE_PENDING` and records the
    proposal, and its `version` increments."
    PRD §3.8: "A `BeautyArtist` then accepts, which moves the booking back from
    `RESCHEDULE_PENDING` to `CONFIRMED`: the proposed instant is written into
    `start_at`, `proposed_start_at` is cleared to null, `reschedule_count` increments,
    and the `version` increments."

    Design: Difficulty/non_linear_state_machine/booking_reschedule_cycle_returns_to_confirmed_twice
    """
    ctx = setup_confirmed_booking(start_at="2026-06-05T10:00:00Z")
    booking, artist, customer = ctx["booking"], ctx["artist"], ctx["customer"]
    assert booking["status"] == "CONFIRMED" and booking["reschedule_count"] == 0

    pending = validate_success(
        api.reschedule_booking(
            booking["id"], "2026-06-05T13:00:00Z", make_customer_headers(customer["id"])
        )
    )
    assert pending["status"] == "RESCHEDULE_PENDING"

    back = validate_success(
        api.confirm_booking(booking["id"], make_artist_headers(artist["id"]))
    )
    assert_service_booking(back)
    assert back["status"] == "CONFIRMED", "the cycle traverses CONFIRMED a second time"
    assert back["reschedule_count"] == 1
    assert back["start_at"].startswith("2026-06-05T13:00:00")
    assert back["proposed_start_at"] is None, "the proposal is cleared on confirm"


def test_each_confirm_increments_the_reschedule_count(api):
    """PRD §3.8: "A `BeautyArtist` then accepts, which moves the booking back from
    `RESCHEDULE_PENDING` to `CONFIRMED`: the proposed instant is written into
    `start_at`, `proposed_start_at` is cleared to null, `reschedule_count` increments,
    and the `version` increments."
    PRD §3.8: "A booking may be rescheduled at most twice: a proposal is only permitted
    while `reschedule_count` is strictly below 2, and a third attempt — when the count
    already stands at 2 — is rejected with `ERR_MAX_RESCHEDULES` (HTTP 409)."

    Two completed loops take the count 0 -> 1 -> 2, and `start_at` ends on the second
    proposal, not the first.

    Design: Difficulty/non_linear_state_machine/booking_reschedule_cycle_returns_to_confirmed_twice
    """
    ctx = setup_booking_at_max_reschedules()
    booking = read_booking(ctx["booking"]["id"])

    assert booking["status"] == "CONFIRMED"
    assert booking["reschedule_count"] == 2, "two completed loops"
    assert booking["start_at"].startswith("2026-06-05T16:00:00")
    assert booking["proposed_start_at"] is None


def test_third_reschedule_is_rejected(api):
    """PRD §3.8: "A booking may be rescheduled at most twice: a proposal is only
    permitted while `reschedule_count` is strictly below 2, and a third attempt — when
    the count already stands at 2 — is rejected with `ERR_MAX_RESCHEDULES` (HTTP 409)."

    Design: Corner/state_machines/third_reschedule_returns_max_reschedules
    """
    ctx = setup_booking_at_max_reschedules()

    resp = api.reschedule_booking(
        ctx["booking"]["id"],
        "2026-06-05T18:00:00Z",
        make_customer_headers(ctx["customer"]["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_MAX_RESCHEDULES.value)

    after = read_booking(ctx["booking"]["id"])
    assert after["status"] == "CONFIRMED"
    assert after["reschedule_count"] == 2
    assert after["start_at"].startswith("2026-06-05T16:00:00")


# ─── The artist's buffered interval ───────────────────

def test_booking_starting_inside_the_sanitation_buffer_is_rejected(api):
    """PRD §3.8: "A booking occupies its artist from `start_at` up to but not including
    the instant fifteen minutes after the service ends — that is, `start_at` plus
    `duration_minutes` plus a fifteen-minute sanitation buffer. Two bookings for the
    same artist collide when those buffered windows intersect; because the window is
    half-open at its end, touching endpoints do *not* collide, and a booking that begins
    at the exact instant the previous booking's buffered window closes is accepted."
    PRD §3.8: "A collision is rejected with `ERR_ARTIST_TIME_CONFLICT` (HTTP 409), and
    the check runs both when a booking is first made and when a proposed new time is
    accepted."

    A BROW at 10:00 runs 30 minutes and so holds its artist until 10:45. A second
    booking at 10:44 lands inside that window.

    Design: Difficulty/resource_temporal_overlap/artist_sanitation_buffer_is_half_open_touching_end_is_allowed
    """
    ctx = setup_artist_and_customer(skills=["BROW", "MAKEOVER"])
    book_service(ctx, "2026-06-05T10:00:00Z", service_type="BROW")

    other = new_customer()
    resp = api.create_service_booking(
        create_booking_payload(
            other["id"], ctx["store"]["id"], ctx["artist"]["id"],
            "2026-06-05T10:44:00Z", service_type="BROW",
        ),
        make_customer_headers(other["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_ARTIST_TIME_CONFLICT.value)


def test_booking_starting_exactly_at_the_buffered_end_is_accepted(api, admin_headers):
    """PRD §3.8: "Two bookings for the same artist collide when those buffered windows
    intersect; because the window is half-open at its end, touching endpoints do *not*
    collide, and a booking that begins at the exact instant the previous booking's
    buffered window closes is accepted."

    10:00 + 30 minutes + a 15-minute buffer closes at exactly 10:45, so a booking at
    10:45 touches the end and is accepted.

    Design: Difficulty/resource_temporal_overlap/artist_sanitation_buffer_is_half_open_touching_end_is_allowed
    """
    ctx = setup_artist_and_customer(skills=["BROW", "MAKEOVER"])
    first = book_service(ctx, "2026-06-05T10:00:00Z", service_type="BROW")

    other = new_customer()
    touching = validate_success(
        api.create_service_booking(
            create_booking_payload(
                other["id"], ctx["store"]["id"], ctx["artist"]["id"],
                "2026-06-05T10:45:00Z", service_type="BROW",
            ),
            make_customer_headers(other["id"]),
        ),
        201,
    )

    assert touching["status"] == "CONFIRMED", "touching the buffered end is not an overlap"

    listed, meta = validate_paginated(
        api.list_service_bookings(
            admin_headers, params={"artist_id": ctx["artist"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert {b["id"] for b in listed} == {first["id"], touching["id"]}


def test_cancelling_a_booking_frees_the_artist_interval(api, admin_headers):
    """PRD §3.8: "Only bookings whose `status` is `CONFIRMED` or `RESCHEDULE_PENDING`
    occupy the artist; `COMPLETED`, `NO_SHOW` and `CANCELLED` bookings release the
    interval and no longer block anything."
    PRD §3.8: "A `Customer` or a `StoreAssociate` may cancel a booking from either
    `CONFIRMED` or `RESCHEDULE_PENDING`. The booking becomes `CANCELLED`, and the
    artist's interval is released"

    Design: Corner/state_machines/cancelling_a_booking_frees_the_artist_buffered_interval
    """
    ctx = setup_confirmed_booking(start_at="2026-06-05T10:00:00Z", skills=["BROW"])
    customer_headers = make_customer_headers(ctx["customer"]["id"])
    first = ctx["booking"]

    cancelled = validate_success(
        api.cancel_booking(first["id"], customer_headers)
    )
    assert cancelled["status"] == "CANCELLED"

    # The identical start_at is now free.
    second = validate_success(
        api.create_service_booking(
            create_booking_payload(
                ctx["customer"]["id"], ctx["store"]["id"], ctx["artist"]["id"],
                "2026-06-05T10:00:00Z", service_type="BROW",
            ),
            customer_headers,
        ),
        201,
    )
    assert second["status"] == "CONFIRMED", "the freed slot is immediately re-bookable"

    listed, meta = validate_paginated(
        api.list_service_bookings(
            admin_headers, params={"artist_id": ctx["artist"]["id"]}
        )
    )
    assert meta["total_count"] == 2


# ─── Completion, the linked order and the bonus ───────

def test_completing_a_booking_with_an_uncaptured_linked_order_is_rejected(api):
    """PRD §3.8: "When a booking completes and it carries a `linked_order_id`, the
    linked order's `payment_status` must be `CAPTURED` — otherwise the completion is
    rejected with `ERR_PAYMENT_NOT_CAPTURED` (HTTP 409) — and on success a service bonus
    of 200 points is written to `bonus_points_awarded`, a ledger entry of type
    `SERVICE_BONUS` is appended with a `delta_points` of positive 200, and the
    customer's `points_balance` rises by 200."

    The booking is CONFIRMED and the artist is entitled to close it; the refusal comes
    entirely from the state of a *different* entity — the linked Order.

    Design: Difficulty/cross_entity_state_dependency/booking_completion_blocked_when_linked_order_payment_not_captured
    """
    ctx = setup_booking_linked_to_order(capture_payment=False)
    assert ctx["order"]["payment_status"] == "AUTHORIZED"

    resp = api.complete_booking(
        ctx["booking"]["id"], "COMPLETED", make_artist_headers(ctx["artist"]["id"])
    )

    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED.value)
    assert read_booking(ctx["booking"]["id"])["status"] == "CONFIRMED"


def test_completion_awards_the_service_bonus_once_the_order_is_captured(
    api, associate_headers
):
    """PRD §3.8: "When a booking completes and it carries a `linked_order_id`, the
    linked order's `payment_status` must be `CAPTURED` — otherwise the completion is
    rejected with `ERR_PAYMENT_NOT_CAPTURED` (HTTP 409) — and on success a service bonus
    of 200 points is written to `bonus_points_awarded`, a ledger entry of type
    `SERVICE_BONUS` is appended with a `delta_points` of positive 200, and the
    customer's `points_balance` rises by 200."

    Design: Difficulty/cross_entity_state_dependency/booking_completion_blocked_when_linked_order_payment_not_captured
    """
    ctx = setup_booking_linked_to_order(capture_payment=False)

    validate_error(
        api.complete_booking(
            ctx["booking"]["id"], "COMPLETED", make_artist_headers(ctx["artist"]["id"])
        ),
        ApiErrorId.ERR_PAYMENT_NOT_CAPTURED.value,
    )

    validate_success(api.pay_order(ctx["order"]["id"], "CAPTURE", associate_headers))

    completed = validate_success(
        api.complete_booking(
            ctx["booking"]["id"], "COMPLETED", make_artist_headers(ctx["artist"]["id"])
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["bonus_points_awarded"] == 200

    assert read_customer(ctx["customer"]["id"])["points_balance"] == 200
    bonuses = [
        e for e in read_ledger(ctx["customer"]["id"]) if e["entry_type"] == "SERVICE_BONUS"
    ]
    assert len(bonuses) == 1 and bonuses[0]["delta_points"] == 200


def test_no_show_outcome_awards_nothing(api):
    """PRD §3.8: "A `BeautyArtist` closes a `CONFIRMED` booking with an `outcome`. An
    outcome of `COMPLETED` moves the booking to `COMPLETED`; an outcome of `NO_SHOW`
    moves it to `NO_SHOW`, which awards nothing and is terminal."

    Design: Corner/state_machines/booking_no_show_outcome_awards_no_points
    """
    ctx = setup_booking_linked_to_order(capture_payment=True)
    assert ctx["order"]["payment_status"] == "CAPTURED"

    closed = validate_success(
        api.complete_booking(
            ctx["booking"]["id"], "NO_SHOW", make_artist_headers(ctx["artist"]["id"])
        )
    )

    assert closed["status"] == "NO_SHOW"
    assert closed["bonus_points_awarded"] == 0

    assert read_customer(ctx["customer"]["id"])["points_balance"] == 0
    assert not [
        e for e in read_ledger(ctx["customer"]["id"]) if e["entry_type"] == "SERVICE_BONUS"
    ], "a no-show writes no SERVICE_BONUS entry, even with a captured linked order"


def test_booking_linked_to_another_customers_order_is_rejected(api, admin_headers):
    """PRD §3.8: "A booking may optionally name a `linked_order_id`, tying it to a
    purchase; when supplied, that order must belong to the *same* customer and the
    *same* store as the booking, and a mismatch on either is rejected with
    `ERR_BOOKING_ORDER_MISMATCH` (HTTP 422)."

    Design: Corner/validations/booking_linked_to_another_customers_order_returns_booking_order_mismatch
    """
    ctx = setup_draft_order(quantity=1)
    artist = validate_success(
        api.create_artist(
            {"store_id": ctx["store"]["id"], "name": "Ada", "skills": ["BROW"]},
            admin_headers,
        ),
        201,
    )
    other = new_customer()

    resp = api.create_service_booking(
        create_booking_payload(
            other["id"], ctx["store"]["id"], artist["id"], "2026-06-05T10:00:00Z",
            service_type="BROW", linked_order_id=ctx["order"]["id"],
        ),
        make_customer_headers(other["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_BOOKING_ORDER_MISMATCH.value)

    listed, meta = validate_paginated(
        api.list_service_bookings(admin_headers, params={"customer_id": other["id"]})
    )
    assert meta["total_count"] == 0, "no booking was created"


# ─── Path and body existence on the booking surface ───

def test_booking_with_an_unknown_artist_returns_artist_not_found(api):
    """PRD §2.9: "5. Body-reference existence — every foreign key inside the request
    body resolves to an existing row, reported with the same 404 family as step 3
    (`ERR_STORE_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`). This
    applies to order creation, line addition, inventory-lot creation, service-booking
    creation, return-request creation and promotion creation."

    Design: Corner/errors/error_artist_not_found_on_booking_with_unknown_artist
    """
    store = new_store()
    customer = new_customer()

    resp = api.create_service_booking(
        create_booking_payload(
            customer["id"], store["id"], UNKNOWN_ARTIST_ID, "2026-06-05T10:00:00Z",
            service_type="BROW",
        ),
        make_customer_headers(customer["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_ARTIST_NOT_FOUND.value)


def test_confirm_with_an_unknown_booking_returns_booking_not_found(api):
    """PRD §2.11: "The same discipline applies to every action hung off an order, a
    lot, a booking or a return request: the parent named in the path must exist before
    any body field, any state rule or any business rule is considered."
    PRD §2.9: "3. Path existence — every resource named in the URL path exists, checked
    left to right, so that the leftmost missing identifier is the one reported."

    Design: Corner/errors/error_booking_not_found_on_confirm_with_unknown_booking
    """
    ctx = setup_artist_and_customer(skills=["BROW"])

    resp = api.confirm_booking(
        UNKNOWN_BOOKING_ID, make_artist_headers(ctx["artist"]["id"])
    )

    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND.value)
