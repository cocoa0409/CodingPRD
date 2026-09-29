"""Two-dimensional booking state, the refund bands and the allotment identity."""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_allotment,
    assert_booking_conserved,
    assert_booking_state,
    assert_instant_equals,
    assert_pct,
)
from test_helpers.fixtures import (
    DEFAULT_INSTANT,
    captured_booking,
    hotel_agency_offer,
    two_leg_package,
)
from test_helpers.test_users import (
    BOOKING_AGENT,
    BOOKING_AGENT_USER_ID,
    PLATFORM_ADMIN,
    supplier_user_headers,
)

ARRIVAL_AT = "2026-09-20T15:00:00Z"


def test_capture_and_confirm_advance_the_two_booking_dimensions_separately(b, client):
    """Capture touches only the money side and confirmation only the inventory side.

    PRD 3.8: "Capture touches only the money side; confirmation touches only the
    inventory side", and confirmation moves the offer's units so that "`allotment_held`
    decrements by 1 and `allotment_sold` increments by 1".

    Design: Difficulty/non_linear_state_machine/booking_payment_and_fulfillment_dimensions_advance_independently
    """
    ctx = hotel_agency_offer(b)
    booking = b.booking(offer=ctx.offer)
    assert_booking_state(booking, payment_status="AUTHORIZED", fulfillment_status="RESERVED")

    captured = b.capture(booking["id"])
    assert_booking_state(captured, payment_status="CAPTURED", fulfillment_status="RESERVED")
    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=2, held=1, sold=0, total=3)

    confirmed = validate_success(
        client.confirm_booking(
            booking["id"],
            {"supplier_confirmation_code": "LUT-88213"},
            supplier_user_headers(ctx.supplier["id"]),
        )
    )
    assert_booking_state(confirmed, payment_status="CAPTURED", fulfillment_status="CONFIRMED")
    assert confirmed["supplier_confirmation_code"] == "LUT-88213"
    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=2, held=0, sold=1, total=3)


def test_a_completed_stay_can_still_fall_into_chargeback(b, client):
    """The acquirer moves the money dimension alone, even on a completed stay.

    PRD 3.8: the chargeback "moves `payment_status` `CAPTURED → CHARGEBACK` while
    leaving the fulfilment dimension exactly as it was, so a traveller whose stay is
    `CONFIRMED` or even `COMPLETED` may still be in chargeback."

    Design: Difficulty/non_linear_state_machine/booking_payment_and_fulfillment_dimensions_advance_independently
    """
    ctx = captured_booking(b, confirm=True)
    booking = ctx.booking

    assert booking["charged_total_cents"] == 24240
    assert booking["marketplace_margin_cents"] == 3600
    assert booking["supplier_payable_cents"] == 20400
    assert booking["taxes_fees_cents"] == 240
    assert booking["collection_model"] == "AGENCY"
    assert_instant_equals(booking["arrival_at"], ARRIVAL_AT)

    b.set_clock(ARRIVAL_AT)
    completed = validate_success(
        client.complete_booking(
            booking["id"], {}, supplier_user_headers(ctx.supplier["id"])
        )
    )
    assert_booking_state(
        completed, payment_status="CAPTURED", fulfillment_status="COMPLETED"
    )

    charged_back = validate_success(
        client.simulate_chargeback(
            {"booking_id": booking["id"], "reason_code": "13.1"}, PLATFORM_ADMIN
        )
    )
    assert_booking_state(
        charged_back, payment_status="CHARGEBACK", fulfillment_status="COMPLETED"
    )


def test_cancelling_exactly_on_the_cutoff_returns_the_whole_charge(b, client):
    """The cutoff comparison is inclusive, so 48 hours out still refunds in full.

    PRD 3.8: "Under a `FLEX` policy the refund is the whole amount when the hours
    remaining are at or above the cutoff, and half otherwise. ... In every band the
    comparison against the cutoff is inclusive, so a cancellation landing exactly on
    the cutoff receives the more generous band."

    Design: Difficulty/boundary_precision_check/refund_exactly_at_free_cancel_cutoff_returns_the_full_refund
    """
    ctx = captured_booking(b)
    b.set_clock("2026-09-18T15:00:00Z")

    cancelled = validate_success(
        client.cancel_booking(
            ctx.booking["id"],
            {"cancellation_reason": "cancelled exactly at the free-cancellation cutoff"},
            BOOKING_AGENT,
        )
    )

    assert_pct(cancelled["cancellation_refund_pct"], 1.00)
    assert cancelled["refunded_cents"] == 24240
    assert cancelled["last_refund_clawback_cents"] == 3600
    assert cancelled["last_refund_supplier_debit_cents"] == 20400
    assert cancelled["last_refund_tax_cents"] == 240
    assert cancelled["marketplace_margin_cents"] == 0
    assert cancelled["supplier_payable_cents"] == 0
    assert cancelled["taxes_fees_cents"] == 0
    assert_booking_state(
        cancelled, payment_status="REFUNDED_FULL", fulfillment_status="CANCELLED"
    )
    assert_booking_conserved(cancelled)

    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=3, held=0, sold=0, total=3)


def test_cancelling_one_hour_inside_the_cutoff_halves_the_refund(b, client):
    """An hour past the cutoff drops to the half band and the tax share is the residual.

    PRD 3.8: under FLEX the refund is "half otherwise", and "The tax portion is
    deliberately **not** rounded independently: it is the residual, computed as the
    cash returned minus the margin clawback minus the supplier debit".

    Design: Difficulty/boundary_precision_check/refund_exactly_at_free_cancel_cutoff_returns_the_full_refund
    """
    ctx = captured_booking(b)
    b.set_clock("2026-09-18T16:00:00Z")

    cancelled = validate_success(
        client.cancel_booking(
            ctx.booking["id"],
            {"cancellation_reason": "cancelled an hour inside the cutoff"},
            BOOKING_AGENT,
        )
    )

    assert_pct(cancelled["cancellation_refund_pct"], 0.50)
    assert cancelled["refunded_cents"] == 12120
    assert cancelled["last_refund_clawback_cents"] == 1800
    assert cancelled["last_refund_supplier_debit_cents"] == 10200
    assert cancelled["last_refund_tax_cents"] == 120
    assert cancelled["marketplace_margin_cents"] == 1800
    assert cancelled["supplier_payable_cents"] == 10200
    assert cancelled["taxes_fees_cents"] == 120
    assert_booking_state(
        cancelled, payment_status="REFUNDED_PARTIAL", fulfillment_status="CANCELLED"
    )
    assert_booking_conserved(cancelled)


def test_the_allotment_identity_holds_through_confirm_and_cancel(b, client):
    """Units move between buckets and come back to remaining, never to held.

    PRD 3.4: "the invariant that `allotment_total` always equals
    `allotment_remaining` plus `allotment_held` plus `allotment_sold` holds from that
    moment onward"; PRD 3.8: "a booking cancelled from `CONFIRMED` has
    `allotment_sold` decremented by 1, and either way `allotment_remaining` increments
    by 1."

    Design: Difficulty/compensating_invariant/confirm_then_cancel_conserves_the_offer_allotment_identity
    """
    ctx = hotel_agency_offer(b)
    assert_allotment(ctx.offer, remaining=3, held=0, sold=0, total=3)

    booking = b.booking(offer=ctx.offer)
    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=2, held=1, sold=0, total=3)
    assert booking["fulfillment_status"] == "RESERVED"

    b.capture(booking["id"])
    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=2, held=1, sold=0, total=3)

    confirmed = b.confirm(booking["id"], ctx.supplier["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED"
    after_confirm = b.read_offer(ctx.offer["id"])
    assert_allotment(after_confirm, remaining=2, held=0, sold=1, total=3)
    assert after_confirm["version"] > ctx.offer["version"]

    b.cancel(booking["id"], reason="traveller cancelled well before the cutoff")
    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=3, held=0, sold=0, total=3)


def test_a_full_refund_moves_every_retained_share_into_refunded(b, client):
    """The conserved identity still closes once the whole charge has been returned.

    PRD 3.8: "before and after any cancellation, `charged_total_cents` equals
    `supplier_payable_cents` plus `marketplace_margin_cents` plus `taxes_fees_cents`
    plus `refunded_cents`."

    Design: Difficulty/compensating_invariant/confirm_then_cancel_conserves_the_offer_allotment_identity
    """
    ctx = hotel_agency_offer(b)
    booking = b.booking(offer=ctx.offer)
    b.capture(booking["id"])
    b.confirm(booking["id"], ctx.supplier["id"])

    cancelled = b.cancel(
        booking["id"], reason="traveller cancelled well before the cutoff"
    )

    assert_pct(cancelled["cancellation_refund_pct"], 1.00)
    assert cancelled["refunded_cents"] == 24240
    assert cancelled["marketplace_margin_cents"] == 0
    assert cancelled["supplier_payable_cents"] == 0
    assert cancelled["taxes_fees_cents"] == 0
    assert cancelled["payment_status"] == "REFUNDED_FULL"
    assert_booking_conserved(cancelled)
    assert_instant_equals(cancelled["cancelled_at"], DEFAULT_INSTANT)

    assert b.read_offer(ctx.offer["id"])["status"] == "LIVE"


def test_a_suppressed_offer_is_reported_before_the_stale_quote(b, client):
    """Target state is checked before the quoted figure, so the state error reports.

    PRD 2.10 evaluates "9. State precondition" before "31. Quoted price agreement on
    booking creation", and PRD 3.8 rejects "booking an offer that is not `LIVE` ...
    with `ERR_OFFER_NOT_LIVE`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_booking_a_suppressed_offer_with_a_stale_quote
    """
    ctx = hotel_agency_offer(b)
    b.suppress_offer(ctx.offer["id"], reason="content defect found in the listing")

    refused = client.create_booking(
        f.booking_payload(20000, offer_id=ctx.offer["id"]), BOOKING_AGENT
    )
    body = validate_error(refused, E.ERR_OFFER_NOT_LIVE, 409)
    assert body["error_id"] != E.ERR_PRICE_CHANGED

    _rows, meta = validate_paginated(
        client.list_bookings(PLATFORM_ADMIN, params={"offer_id": ctx.offer["id"]})
    )
    assert meta["total_count"] == 0
    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=3, held=0, sold=0, total=3)


def test_the_stale_quote_is_reported_once_the_offer_is_live_again(b, client):
    """With the state fault repaired the fiscal check becomes the reported one.

    PRD 3.8: "The quoted figure must equal the server's own current charged total ...
    and any discrepancy is rejected with `ERR_PRICE_CHANGED`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_booking_a_suppressed_offer_with_a_stale_quote
    """
    ctx = hotel_agency_offer(b)
    b.suppress_offer(ctx.offer["id"], reason="content defect found in the listing")
    republished = b.publish_offer(ctx.offer["id"])
    assert republished["status"] == "LIVE"

    refused = client.create_booking(
        f.booking_payload(20000, offer_id=ctx.offer["id"]), BOOKING_AGENT
    )
    validate_error(refused, E.ERR_PRICE_CHANGED, 409)

    _rows, meta = validate_paginated(
        client.list_bookings(PLATFORM_ADMIN, params={"offer_id": ctx.offer["id"]})
    )
    assert meta["total_count"] == 0


def test_a_new_booking_starts_authorized_and_reserved(b, client):
    """Creation writes the money decomposition, the arrival hour and both start states.

    PRD 3.8: "`refunded_cents`, `last_refund_clawback_cents`,
    `last_refund_supplier_debit_cents` and `last_refund_tax_cents` all start at 0, and
    `cancellation_refund_pct`, `cancelled_at` and `supplier_confirmation_code` start
    null" and it "computes `arrival_at` as the booked inventory's `travel_date` at
    15:00 UTC".

    Design: Corner/state_machines/booking_starts_in_authorized_and_reserved
    """
    ctx = hotel_agency_offer(b)

    booking = validate_success(
        client.create_booking(
            {
                "offer_id": ctx.offer["id"],
                "traveler_reference": "PNR-K2",
                "quoted_total_cents": 24240,
                "payment_token": "tok_live_10",
            },
            BOOKING_AGENT,
        ),
        201,
    )

    assert_booking_state(booking, payment_status="AUTHORIZED", fulfillment_status="RESERVED")
    assert booking["charged_total_cents"] == 24240
    assert booking["marketplace_margin_cents"] == 3600
    assert booking["supplier_payable_cents"] == 20400
    assert booking["taxes_fees_cents"] == 240
    assert booking["refunded_cents"] == 0
    assert booking["last_refund_clawback_cents"] == 0
    assert booking["last_refund_supplier_debit_cents"] == 0
    assert booking["last_refund_tax_cents"] == 0
    assert booking["cancellation_refund_pct"] is None
    assert booking["cancelled_at"] is None
    assert booking["supplier_confirmation_code"] is None
    assert booking["collection_model"] == "AGENCY"
    assert_instant_equals(booking["arrival_at"], ARRIVAL_AT)
    assert booking["booked_by_user_id"] == BOOKING_AGENT_USER_ID

    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=2, held=1, sold=0, total=3)


def test_a_booking_quoted_below_the_display_total_is_rejected(b, client):
    """A stale screen price never becomes a booked liability.

    PRD 3.8: "any discrepancy is rejected with `ERR_PRICE_CHANGED`, which is how a
    stale price on a channel's screen is prevented from becoming a booked liability."

    Design: Corner/validations/booking_with_a_stale_quoted_total_is_rejected
    """
    ctx = hotel_agency_offer(b)

    refused = client.create_booking(
        {
            "offer_id": ctx.offer["id"],
            "traveler_reference": "PNR-V1",
            "quoted_total_cents": 24000,
            "payment_token": "tok_live_12",
        },
        BOOKING_AGENT,
    )
    validate_error(refused, E.ERR_PRICE_CHANGED, 409)

    _rows, meta = validate_paginated(
        client.list_bookings(PLATFORM_ADMIN, params={"offer_id": ctx.offer["id"]})
    )
    assert meta["total_count"] == 0
    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=3, held=0, sold=0, total=3)


def test_a_booking_quoted_at_the_exact_display_total_succeeds(b, client):
    """The matching quote books the unit and names only the offer target.

    PRD 3.8: "The quoted figure must equal the server's own current charged total —
    the offer's `display_total_cents` for a single-offer sale".

    Design: Corner/validations/booking_with_the_exact_display_total_succeeds
    """
    ctx = hotel_agency_offer(b)

    booking = validate_success(
        client.create_booking(
            {
                "offer_id": ctx.offer["id"],
                "traveler_reference": "PNR-V2",
                "quoted_total_cents": 24240,
                "payment_token": "tok_live_13",
            },
            BOOKING_AGENT,
        ),
        201,
    )

    assert booking["charged_total_cents"] == 24240
    assert booking["payment_status"] == "AUTHORIZED"
    assert booking["offer_id"] == ctx.offer["id"]
    assert booking["package_id"] is None
    assert_allotment(b.read_offer(ctx.offer["id"]), remaining=2, held=1, sold=0, total=3)


def test_a_booking_must_name_exactly_one_target(b, client):
    """Naming both targets and naming neither are the same invalid-target failure.

    PRD 3.8: "A **Booking** is taken by a `BookingAgent` against exactly one target
    ... Supplying neither, or supplying both, is rejected with
    `ERR_BOOKING_TARGET_INVALID`".

    Design: Corner/endpoints/booking_with_both_offer_and_package_targets_is_rejected
    """
    ctx = two_leg_package(b, publish=True)
    assert ctx.package["status"] == "PUBLISHED"
    assert ctx.package["package_total_cents"] == 157306

    both = client.create_booking(
        {
            "offer_id": ctx.offer["id"],
            "package_id": ctx.package["id"],
            "traveler_reference": "PNR-E1",
            "quoted_total_cents": 157306,
            "payment_token": "tok_live_15",
        },
        BOOKING_AGENT,
    )
    validate_error(both, E.ERR_BOOKING_TARGET_INVALID, 422)

    neither = client.create_booking(
        {
            "traveler_reference": "PNR-E2",
            "quoted_total_cents": 157306,
            "payment_token": "tok_live_16",
        },
        BOOKING_AGENT,
    )
    validate_error(neither, E.ERR_BOOKING_TARGET_INVALID, 422)

    _rows, meta = validate_paginated(client.list_bookings(PLATFORM_ADMIN))
    assert meta["total_count"] == 0
    assert b.read_offer(ctx.offer["id"])["allotment_held"] == 0
    package = b.read_package(ctx.package["id"])
    assert package["status"] == "PUBLISHED"
    assert package["package_total_cents"] == 157306


def test_capturing_an_already_captured_booking_is_rejected(b, client):
    """Capture is only available from AUTHORIZED and the retry changes nothing.

    PRD 3.8: "Capture requires `payment_status` to be `AUTHORIZED`, otherwise
    `ERR_PAYMENT_NOT_AUTHORIZED`".

    Design: Corner/state_machines/capture_an_already_captured_booking_is_rejected
    """
    ctx = captured_booking(b)

    refused = client.capture_booking(ctx.booking["id"], {"note": "retry"}, BOOKING_AGENT)
    validate_error(refused, E.ERR_PAYMENT_NOT_AUTHORIZED, 409)

    after = b.read_booking(ctx.booking["id"])
    assert_booking_state(after, payment_status="CAPTURED", fulfillment_status="RESERVED")
    assert after["charged_total_cents"] == 24240
    assert after["refunded_cents"] == 0


def test_completing_a_stay_before_its_arrival_instant_is_rejected(b, client):
    """Completion waits for the clock to reach the arrival instant.

    PRD 3.8: completion "requires the logical clock to have reached or passed the
    booking's `arrival_at` ... Completing a booking that is not `CONFIRMED`, or
    completing one before the clock reaches `arrival_at`, is rejected with
    `ERR_BOOKING_NOT_CONFIRMED`."

    Design: Corner/state_machines/complete_a_confirmed_booking_before_arrival_is_rejected
    """
    ctx = captured_booking(b, confirm=True)

    refused = client.complete_booking(
        ctx.booking["id"], {}, supplier_user_headers(ctx.supplier["id"])
    )
    validate_error(refused, E.ERR_BOOKING_NOT_CONFIRMED, 409)

    after = b.read_booking(ctx.booking["id"])
    assert_booking_state(after, payment_status="CAPTURED", fulfillment_status="CONFIRMED")
    assert_instant_equals(after["arrival_at"], ARRIVAL_AT)


def test_the_chargeback_simulation_needs_a_captured_payment(b, client):
    """It moves only the payment dimension, and refuses an uncaptured booking.

    PRD 3.8: "A booking whose `payment_status` is not `CAPTURED` is rejected with
    `ERR_PAYMENT_NOT_CAPTURED`".

    Design: Corner/endpoints/chargeback_simulation_moves_only_the_payment_dimension
    """
    ctx = captured_booking(b)
    authorized_only = b.booking(offer=b.read_offer(ctx.offer["id"]))

    charged_back = validate_success(
        client.simulate_chargeback(
            {"booking_id": ctx.booking["id"], "reason_code": "FRAUDULENT_TRANSACTION"},
            PLATFORM_ADMIN,
        )
    )
    assert_booking_state(
        charged_back, payment_status="CHARGEBACK", fulfillment_status="RESERVED"
    )
    assert charged_back["charged_total_cents"] == 24240
    assert charged_back["refunded_cents"] == 0

    refused = client.simulate_chargeback(
        {"booking_id": authorized_only["id"], "reason_code": "FRAUDULENT_TRANSACTION"},
        PLATFORM_ADMIN,
    )
    validate_error(refused, E.ERR_PAYMENT_NOT_CAPTURED, 409)
    assert b.read_booking(authorized_only["id"])["payment_status"] == "AUTHORIZED"
