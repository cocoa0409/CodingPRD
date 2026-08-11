"""Amendment, cancellation, notice-priced refunds, terminal-state guards, and
inventory reservation release / consumption.

Queue A (Difficulty): non_linear_state_machine, transitive_cascade,
dual_variant_calc (refund variants), compensating_invariant.
Queue B (Corner): state_machines, errors.
"""
from test_helpers import (
    api_client,
    fixtures as fx,
    validate_success, validate_error,
    ApiErrorId,
)

ERR = ApiErrorId


def _refund_payments(ctx, booking_id):
    res = api_client.list_booking_payments(booking_id, fx.OPS)
    return [p for p in res.json()["data"] if p["kind"] == "REFUND"]


# ─── non_linear_state_machine / booking_amend_cycle_confirmed_quote_confirmed ───

def _confirmed_far_future_booking():
    """CONFIRMED booking whose event (2026-05-20) is more than 48h ahead of the
    pinned clock, so the amendment window is open."""
    return fx.setup_confirmed_booking(
        package_kind="FLAT", accept=True,
        booking_overrides={"event_start": "2026-05-20T10:00:00Z",
                           "event_end": "2026-05-20T12:00:00Z"})


def test_amend_rolls_confirmed_booking_back_to_quote_preserving_deposit(api):
    """PRD §3.8: "When an amendment changes the package, cart, service window, guest
    count, distance, or the attached add-ons, the booking rolls back from
    `CONFIRMED` to `QUOTE` and the amendment re-runs the creation-time validations
    — event window, venue compatibility, guest range, and the cart's buffered
    schedule check."
    PRD §3.8: "any `DEPOSIT` payments remain `SUCCEEDED` — the credit is carried
    forward, so `deposit_paid_cents` is unchanged."

    Amending guest_count on a CONFIRMED booking cycles it back to QUOTE while the
    18600-cent deposit already settled stays on the books.

    Design: Difficulty/non_linear_state_machine/booking_amend_cycle_confirmed_quote_confirmed
    """
    ctx = _confirmed_far_future_booking()
    assert ctx["booking"]["status"] == "CONFIRMED", ctx["booking"]
    assert ctx["booking"]["deposit_paid_cents"] == 18600, ctx["booking"]

    amended = validate_success(
        api_client.amend_booking(ctx["booking"]["id"], {"guest_count": 50},
                                 ctx["client_headers"]), 200)
    assert amended["status"] == "QUOTE", amended
    assert amended["deposit_paid_cents"] == 18600, amended

    payments_res = api_client.list_booking_payments(ctx["booking"]["id"], fx.OPS)
    deposits = [p for p in payments_res.json()["data"] if p["kind"] == "DEPOSIT"]
    assert len(deposits) == 1, deposits
    assert deposits[0]["status"] == "SUCCEEDED", deposits


def test_resubmission_after_amend_reenters_pending_deposit(api):
    """PRD §3.8: "The booking then awaits a fresh submission to be repriced."
    PRD §3.5: "A successful submission reprices the booking within the same request:
    `quoted_subtotal_cents`, `quoted_travel_fee_cents`, and `quoted_total_cents`
    are recomputed per the pricing and travel variants of §3.3,
    `pricing_variant_used` and `travel_variant_used` are pinned to record which
    algorithms produced the numbers, and `deposit_due_cents` is recomputed from
    the fresh total."

    After the amend-driven rollback to QUOTE, a fresh submission re-prices the
    amended booking and moves it to PENDING_DEPOSIT — completing the
    QUOTE -> PENDING_DEPOSIT -> CONFIRMED -> QUOTE -> PENDING_DEPOSIT cycle.

    Design: Difficulty/non_linear_state_machine/booking_amend_cycle_confirmed_quote_confirmed
    """
    ctx = _confirmed_far_future_booking()
    amended = validate_success(
        api_client.amend_booking(ctx["booking"]["id"], {"guest_count": 50},
                                 ctx["client_headers"]), 200)
    assert amended["status"] == "QUOTE", amended

    resubmitted = fx.submit_quote(ctx, ctx["booking"]["id"])
    assert resubmitted["status"] == "PENDING_DEPOSIT", resubmitted
    assert resubmitted["pricing_variant_used"] == "FLAT_PACKAGE", resubmitted
    assert resubmitted["quoted_total_cents"] == 62000, resubmitted
    assert resubmitted["deposit_due_cents"] == 18600, resubmitted
    assert resubmitted["deposit_paid_cents"] == 18600, resubmitted


# ─── transitive_cascade / cancel_cascade_booking_assignment_barista ───────

def _confirmed_in_week_booking_with_zero_refund_tier():
    """CONFIRMED booking (accepted assignment, 2 committed hours) on an in-week
    event; a catch-all 0%-refund tier keeps the cancel refund at zero so the test
    isolates the assignment/hours cascade."""
    fx.set_clock()
    fx.create_cancellation_tier(tier_code="T0", min_notice_hours=0,
                                max_notice_hours=-1, deposit_refund_pct=0.0,
                                balance_waived=True)
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    booking = fx.create_quote_booking(
        ctx, event_start=fx.IN_WEEK_LATE_EVENT_START,
        event_end=fx.IN_WEEK_LATE_EVENT_END)
    assignment = fx.offer_primary_assignment(ctx, booking["id"])
    validate_success(
        api_client.accept_assignment(assignment["id"], ctx["barista_headers"]), 200)
    booking = fx.submit_quote(ctx, booking["id"])
    fx.pay_deposit(ctx, booking["id"], booking["deposit_due_cents"])
    booking = validate_success(api_client.get_booking(booking["id"], fx.OPS), 200)
    assert booking["status"] == "CONFIRMED", booking
    ctx.update({"booking": booking, "assignment": assignment})
    return ctx


def _committed_hours(ctx):
    barista = validate_success(api_client.get_barista(ctx["barista"]["id"], fx.OPS), 200)
    return barista["committed_hours_this_week"]


def test_cancel_from_confirmed_cascades_assignment_to_cancelled(api):
    """PRD §3.8: "The unwind releases everything: assignments in `OFFERED`,
    `ACCEPTED`, or `CONFIRMED` move to `CANCELLED` with the affected baristas'
    weekly hours recomputed downward; reservations in `RESERVED` or `COMMITTED`
    move to `RELEASED` with `reserved_units` decremented per release; and the
    cart's derived `committed_event_count` drops."
    PRD §3.8: "It is permitted only while the logical clock still precedes the
    `event_start` — once service has begun, cancellation is rejected with
    `ERR_CANCEL_WINDOW_CLOSED` (HTTP 409)."

    Cancelling a CONFIRMED booking before event start moves the booking to
    CANCELLED and its CONFIRMED assignment to CANCELLED (cascade link one).

    Design: Difficulty/transitive_cascade/cancel_cascade_booking_assignment_barista
    """
    ctx = _confirmed_in_week_booking_with_zero_refund_tier()
    asg_pre = validate_success(
        api_client.get_assignment(ctx["assignment"]["id"], fx.OPS), 200)
    assert asg_pre["status"] == "CONFIRMED", asg_pre

    cancelled = validate_success(
        api_client.cancel_booking(ctx["booking"]["id"], {}, ctx["client_headers"]), 200)
    assert cancelled["status"] == "CANCELLED", cancelled

    asg_post = validate_success(
        api_client.get_assignment(ctx["assignment"]["id"], fx.OPS), 200)
    assert asg_post["status"] == "CANCELLED", asg_post


def test_cancel_from_confirmed_releases_barista_weekly_hours(api):
    """PRD §3.4: "When a booking is cancelled, every assignment in `OFFERED`,
    `ACCEPTED`, or `CONFIRMED` moves to `CANCELLED`, and cancelling a `CONFIRMED`
    assignment subtracts its hours from the barista's weekly tally."

    The assignment's own cancellation then releases the barista's committed hours
    (2 -> 0) — the second link of the cancel cascade.

    Design: Difficulty/transitive_cascade/cancel_cascade_booking_assignment_barista
    """
    ctx = _confirmed_in_week_booking_with_zero_refund_tier()
    assert _committed_hours(ctx) == 2

    validate_success(
        api_client.cancel_booking(ctx["booking"]["id"], {}, ctx["client_headers"]), 200)
    assert _committed_hours(ctx) == 0


# ─── dual_variant_calc / refund_variant_forward_vs_chronological ──────────

def _confirmed_booking_with_tiers(event_start, event_end):
    fx.set_clock()
    fx.seed_default_cancellation_tiers()
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    booking = fx.create_quote_booking(ctx, event_start=event_start, event_end=event_end)
    fx.offer_primary_assignment(ctx, booking["id"])
    booking = fx.submit_quote(ctx, booking["id"])
    fx.pay_deposit(ctx, booking["id"], booking["deposit_due_cents"])
    booking = validate_success(api_client.get_booking(booking["id"], fx.OPS), 200)
    assert booking["status"] == "CONFIRMED", booking
    ctx["booking"] = booking
    return ctx


def test_long_notice_cancellation_refunds_full_deposit(api):
    """PRD §3.8: "The notice in hours is the whole number of hours between the logical
    clock and the `event_start` — the difference in seconds, divided by an hour,
    with any fraction discarded. The applicable tier is the first `ACTIVE`
    CancellationPolicyTier whose band contains that notice: the `min_notice_hours`
    is inclusive, so a notice exactly equal to a tier's minimum belongs to that
    tier, while the `max_notice_hours` is exclusive, so a notice exactly equal to
    a tier's maximum belongs to the next tier up, and a maximum of minus one
    leaves the band unbounded above."
    PRD §3.8: "With at least one hundred sixty-eight hours of notice — seven full
    days — the refund is the `deposit_paid_cents` multiplied by the tier's
    `deposit_refund_pct`, with any fractional cent discarded."
    PRD §3.8: "Whenever the resulting refund is positive, the cancellation
    automatically creates a `REFUND` payment in `PENDING` status for exactly that
    amount, and its eventual success carries the booking from `CANCELLED` to
    `REFUNDED`."

    Clock 2026-05-01T00:00:00Z against an event_start of 2026-05-09T08:00:00Z is
    200 notice hours (>= 168, tier T1 at pct 1.0): the auto-created refund is the
    full 18600-cent deposit, forward-looking with no haircut.

    Design: Difficulty/dual_variant_calc/refund_variant_forward_vs_chronological
    """
    ctx = _confirmed_booking_with_tiers("2026-05-09T08:00:00Z", "2026-05-09T10:00:00Z")
    cancelled = validate_success(
        api_client.cancel_booking(ctx["booking"]["id"], {}, ctx["client_headers"]), 200)
    assert cancelled["status"] == "CANCELLED", cancelled

    refunds = _refund_payments(ctx, ctx["booking"]["id"])
    assert len(refunds) == 1, refunds
    assert refunds[0]["amount_cents"] == 18600, refunds
    assert refunds[0]["status"] == "PENDING", refunds


def test_short_notice_cancellation_applies_half_haircut(api):
    """PRD §3.8: "With at least one hundred sixty-eight hours of notice — seven full
    days — the refund is the `deposit_paid_cents` multiplied by the tier's
    `deposit_refund_pct`, with any fractional cent discarded. With less notice
    than that, the same product is additionally halved — multiplied by a
    short-notice factor of one half — before the fraction is discarded."
    PRD §3.8: "Whenever the resulting refund is positive, the cancellation
    automatically creates a `REFUND` payment in `PENDING` status for exactly that
    amount, and its eventual success carries the booking from `CANCELLED` to
    `REFUNDED`."

    Clock 2026-05-01T00:00:00Z against an event_start of 2026-05-05T04:00:00Z is
    100 notice hours (< 168, tier T2 at pct 0.5): the chronological variant halves
    the product — floor(18600 x 0.5 x 0.5) = 4650 — diverging from the
    forward-looking full-rate refund on an identical deposit.

    Design: Difficulty/dual_variant_calc/refund_variant_forward_vs_chronological
    """
    ctx = _confirmed_booking_with_tiers("2026-05-05T04:00:00Z", "2026-05-05T06:00:00Z")
    cancelled = validate_success(
        api_client.cancel_booking(ctx["booking"]["id"], {}, ctx["client_headers"]), 200)
    assert cancelled["status"] == "CANCELLED", cancelled

    refunds = _refund_payments(ctx, ctx["booking"]["id"])
    assert len(refunds) == 1, refunds
    assert refunds[0]["amount_cents"] == 4650, refunds
    assert refunds[0]["status"] == "PENDING", refunds


# ─── Corner/state_machines: terminal COMPLETED cannot be cancelled ────────

def test_cancel_from_completed_rejected(api):
    """PRD §2.10: "State-level checks come fifth: whether the target entity's status
    permits the requested transition (`ERR_INVALID_STATE`, HTTP 409) and whether
    referenced catalog entities are `ACTIVE` (the per-entity codes of §2.9).
    Business rules are evaluated last, in the endpoint-specific orders stated
    throughout §3."
    PRD §3.8: "Cancellation splits by how far the booking had progressed."

    Cancellation is defined from QUOTE, PENDING_DEPOSIT, and CONFIRMED only; a
    COMPLETED booking permits no such transition, so the state guard rejects it.

    Design: Corner/state_machines/cancel_from_completed_rejected_terminal
    """
    ctx = fx.setup_completed_booking()
    assert ctx["booking"]["status"] == "COMPLETED", ctx["booking"]

    res = api_client.cancel_booking(ctx["booking"]["id"], {}, ctx["client_headers"])
    validate_error(res, ERR.ERR_INVALID_STATE, expected_status=409)


# ─── compensating_invariant / inventory_reserved_units_conserved_across_reserve_release ───

def test_reservation_creation_increments_reserved_units(api):
    """PRD §3.2: "A new reservation starts in `RESERVED` status, and the item's
    `reserved_units` immediately grows by `qty_units`."

    Reserving 25 units against a QUOTE booking raises the item's reserved tally
    from 0 to 25 (the forward action of the conservation pair).

    Design: Difficulty/compensating_invariant/inventory_reserved_units_conserved_across_reserve_release
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    item = fx.create_inventory_item(on_hand_units=100)
    booking = fx.create_quote_booking(ctx)

    reservation = fx.create_reservation(ctx, booking["id"], item["id"], 25)
    assert reservation["status"] == "RESERVED", reservation

    item_after = validate_success(api_client.get_inventory_item(item["id"], fx.OPS), 200)
    assert item_after["reserved_units"] == 25, item_after


def test_cancel_from_quote_releases_reserved_units(api):
    """PRD §3.8: "From `QUOTE`, cancelling moves every assignment in `OFFERED` or
    `ACCEPTED` to `CANCELLED`, moves every reservation in `RESERVED` to `RELEASED`
    with each item's `reserved_units` dropping by the released quantity, and
    computes no refund because nothing was ever paid."
    PRD §3.7: "Creating a reservation and later releasing it must leave
    `reserved_units` exactly where it started; recording consumption is never
    compensated, but it is fully accounted, since `on_hand_units` and
    `consumed_units_lifetime` move together by the consumed quantity."

    Reserve 25 (reserved_units 0 -> 25), then cancel the QUOTE booking: the
    reservation RELEASES and the tally returns to exactly 0 — the compensating
    action conserves the invariant.

    Design: Difficulty/compensating_invariant/inventory_reserved_units_conserved_across_reserve_release
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    item = fx.create_inventory_item(on_hand_units=100)
    booking = fx.create_quote_booking(ctx)
    reservation = fx.create_reservation(ctx, booking["id"], item["id"], 25)
    item_mid = validate_success(api_client.get_inventory_item(item["id"], fx.OPS), 200)
    assert item_mid["reserved_units"] == 25, item_mid

    cancelled = validate_success(
        api_client.cancel_booking(booking["id"], {}, ctx["client_headers"]), 200)
    assert cancelled["status"] == "CANCELLED", cancelled

    reservation_after = validate_success(
        api_client.get_reservation(reservation["id"], fx.OPS), 200)
    assert reservation_after["status"] == "RELEASED", reservation_after

    item_after = validate_success(api_client.get_inventory_item(item["id"], fx.OPS), 200)
    assert item_after["reserved_units"] == 0, item_after


# ─── Corner/errors: consumption range guard ───────────────────────────────

def test_record_consumption_above_reserved_quantity_rejected(api):
    """PRD §3.7: "Consumption is recorded per reservation. Against a `COMMITTED`
    reservation — while its booking is `IN_PROGRESS`, or `COMPLETED` and still
    pending reconciliation — the operator writes the `qty_consumed`, which must
    lie between zero and the reservation's `qty_units` inclusive; anything outside
    that range is rejected with `ERR_CONSUMPTION_OUT_OF_RANGE` (HTTP 422)."

    Recording 11 consumed units against a 10-unit COMMITTED reservation is
    rejected while the event is mid-service (IN_PROGRESS).

    Design: Corner/errors/err_consumption_out_of_range
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    item = fx.create_inventory_item(on_hand_units=100)
    booking = fx.create_quote_booking(
        ctx, event_start="2026-05-03T10:00:00Z", event_end="2026-05-03T12:00:00Z")
    assignment = fx.offer_primary_assignment(ctx, booking["id"])
    validate_success(
        api_client.accept_assignment(assignment["id"], ctx["barista_headers"]), 200)
    reservation = fx.create_reservation(ctx, booking["id"], item["id"], 10)
    booking = fx.submit_quote(ctx, booking["id"])
    fx.pay_deposit(ctx, booking["id"], booking["deposit_due_cents"])
    booking = validate_success(api_client.get_booking(booking["id"], fx.OPS), 200)
    assert booking["status"] == "CONFIRMED", booking

    fx.set_clock("2026-05-03T11:00:00Z")  # mid-event: auto-transition IN_PROGRESS
    in_progress = validate_success(api_client.get_booking(booking["id"], fx.OPS), 200)
    assert in_progress["status"] == "IN_PROGRESS", in_progress

    res = api_client.record_consumption(reservation["id"], {"qty_consumed": 11}, fx.OPS)
    validate_error(res, ERR.ERR_CONSUMPTION_OUT_OF_RANGE, expected_status=422)
