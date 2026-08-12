"""Event registrations: sales-window gating, event-status gating, parallel
payment/attendance dimensions, sold-out posture, and the confirm/refund
compensating pair (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_registration,
    create_record,
    create_event,
    register,
    confirm,
    register_and_confirm,
    setup_open_event,
    current_event,
    TEST_USERS,
    make_alumni_headers,
)

STAFF = TEST_USERS["staff_headers"]


def _open_event_ctx(api, event_date="2026-09-01T18:00:00Z", sales_end="2026-09-01T00:00:00Z",
                    clock_iso="2026-06-01T00:00:00Z", **tier_kw):
    tier_overrides = {
        "name": "GA", "base_price_cents": 1000, "capacity": 0,
        "sales_start": "2026-05-01T00:00:00Z", "sales_end": sales_end,
    }
    tier_overrides.update(tier_kw)
    return setup_open_event(
        event_overrides={"event_date": event_date},
        tier_overrides=tier_overrides,
        clock_iso=clock_iso,
    )


# ---------------------------------------------------------------------------
# Parallel payment / attendance dimensions
# ---------------------------------------------------------------------------

def test_check_in_moves_attendance_while_payment_stays_confirmed(api):
    """PRD §3.4: "The registration's two status dimensions then evolve in
    parallel" and "On the attendance dimension, staff check in a registration
    — `NOT_CHECKED_IN → CHECKED_IN` — when the parent event's `status` is
    `OPEN_FOR_REGISTRATION` or `HELD` and the payment dimension sits at
    `CONFIRMED`."

    Design: Difficulty/non_linear_state_machine/registration_parallel_payment_and_attendance_dimensions
    """
    ctx = _open_event_ctx(api)
    guest = create_record(full_name="Guest A", primary_email="guesta@x.com")
    confirmed = register_and_confirm(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])

    checked_in = validate_success(api.check_in_registration(confirmed["id"], STAFF))
    assert_registration(checked_in)
    assert checked_in["attendance_status"] == "CHECKED_IN"
    assert checked_in["payment_status"] == "CONFIRMED", (
        "Attendance movement must not disturb the payment dimension"
    )


def test_check_in_requires_confirmed_payment_dimension(api):
    """PRD §3.4: check-in is permitted only when "the payment dimension sits
    at `CONFIRMED`"; PRD §2.10: "**State** — the target resource is in a
    valid from-state for the requested transition (`ERR_INVALID_STATE`, all
    action endpoints)." A PENDING_PAYMENT registration is not in the
    `CONFIRMED` from-state that check-in requires.

    Design: Difficulty/non_linear_state_machine/registration_parallel_payment_and_attendance_dimensions
    """
    ctx = _open_event_ctx(api)
    guest = create_record(full_name="Guest A2", primary_email="guesta2@x.com")
    pending = register(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])
    assert pending["payment_status"] == "PENDING_PAYMENT"

    resp = api.check_in_registration(pending["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    row = validate_success(api.get_registration(pending["id"], STAFF))
    assert row["attendance_status"] == "NOT_CHECKED_IN"


# ---------------------------------------------------------------------------
# Cross-entity gate: confirm-payment requires an OPEN_FOR_REGISTRATION event
# ---------------------------------------------------------------------------

def _held_event_with_pending_registration(api):
    """Event OPEN with unlimited tier; one PENDING registration; clock moved
    past event_date; event marked HELD."""
    ctx = _open_event_ctx(
        api, event_date="2026-06-10T18:00:00Z", sales_end="2026-06-10T00:00:00Z",
        clock_iso="2026-06-01T00:00:00Z",
    )
    guest = create_record(full_name="Guest E", primary_email="gueste@x.com")
    pending = register(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])
    validate_success(api.set_clock("2026-06-11T00:00:00Z", STAFF))
    validate_success(api.mark_held(ctx["event"]["id"], STAFF))
    return ctx, guest, pending


def test_confirm_payment_rejected_once_event_held(api):
    """PRD §3.4: "confirmation — again personal to the registrant — moves
    `PENDING_PAYMENT → CONFIRMED` but only while the parent event's `status`
    is `OPEN_FOR_REGISTRATION` (`ERR_EVENT_NOT_OPEN`)".

    Design: Difficulty/cross_entity_state_dependency/registration_create_gated_by_event_status
    """
    ctx, guest, pending = _held_event_with_pending_registration(api)

    resp = api.confirm_payment(pending["id"], make_alumni_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_OPEN)

    row = validate_success(api.get_registration(pending["id"], STAFF))
    assert row["payment_status"] == "PENDING_PAYMENT"


def test_confirm_payment_succeeds_while_event_open(api):
    """PRD §3.4: "Confirmation computes `final_price_cents` via the FINAL
    variant, increments the tier's `sold_count` by one, adds
    `final_price_cents` to the event's `total_revenue_cents`" — permitted
    "while the parent event's `status` is `OPEN_FOR_REGISTRATION`". With no
    early-bird discount, no committee membership, and the clock outside the
    late-fee window, the FINAL price is the bare list price.

    Design: Difficulty/cross_entity_state_dependency/registration_create_gated_by_event_status
    """
    ctx = _open_event_ctx(
        api, event_date="2026-06-10T18:00:00Z", sales_end="2026-06-10T00:00:00Z",
        clock_iso="2026-06-01T00:00:00Z",
    )
    guest = create_record(full_name="Guest E2", primary_email="gueste2@x.com")
    pending = register(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])

    confirmed = confirm(pending["id"], guest["id"])
    assert confirmed["payment_status"] == "CONFIRMED"
    assert confirmed["final_price_cents"] == 1000


# ---------------------------------------------------------------------------
# Confirm / refund compensating pair
# ---------------------------------------------------------------------------

def test_confirm_increments_sold_count_and_revenue(api):
    """PRD §3.4: "Confirmation computes `final_price_cents` via the FINAL
    variant, increments the tier's `sold_count` by one, adds
    `final_price_cents` to the event's `total_revenue_cents`, re-derives
    posture, and recomputes the registrant's `engagement_score`."

    Design: Difficulty/compensating_invariant/tier_sold_count_and_revenue_invariant_under_confirm_and_refund
    """
    ctx = _open_event_ctx(api, clock_iso="2026-06-01T00:00:00Z", base_price_cents=4000)
    guest = create_record(full_name="Guest F", primary_email="guestf@x.com")
    confirmed = register_and_confirm(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])
    assert confirmed["final_price_cents"] == 4000

    tier = validate_success(api.get_ticket_tier(ctx["tier"]["id"], STAFF))
    assert tier["sold_count"] == 1
    event = validate_success(api.get_event(ctx["event"]["id"], STAFF))
    assert event["total_revenue_cents"] == 4000


def test_refund_compensates_sold_count_and_revenue_exactly(api):
    """PRD §3.4: "refunding moves it to `REFUNDED`, decrements `sold_count`
    by one, subtracts `final_price_cents` from `total_revenue_cents`, leaves
    `attendance_status` at `NOT_CHECKED_IN`, and re-derives posture."

    Design: Difficulty/compensating_invariant/tier_sold_count_and_revenue_invariant_under_confirm_and_refund
    """
    ctx = _open_event_ctx(api, clock_iso="2026-06-01T00:00:00Z", base_price_cents=4000)
    guest = create_record(full_name="Guest F2", primary_email="guestf2@x.com")
    confirmed = register_and_confirm(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])

    refunded = validate_success(api.refund_registration(confirmed["id"], STAFF))
    assert refunded["payment_status"] == "REFUNDED"
    assert refunded["attendance_status"] == "NOT_CHECKED_IN"

    tier = validate_success(api.get_ticket_tier(ctx["tier"]["id"], STAFF))
    assert tier["sold_count"] == 0, "confirm +1 then refund -1 leaves no drift"
    event = validate_success(api.get_event(ctx["event"]["id"], STAFF))
    assert event["total_revenue_cents"] == 0


# ---------------------------------------------------------------------------
# Corner coverage: sales window, cancel idempotency, per-event listing,
# sold-out posture
# ---------------------------------------------------------------------------

def test_sales_window_closed_registration_rejected(api):
    """PRD §3.4: "the logical clock must fall inside the tier's half-open
    sales window, on pain of `ERR_SALES_WINDOW_CLOSED`."

    Design: Corner/validations/sales_window_closed_registration_rejected
    """
    ctx = _open_event_ctx(
        api, sales_end="2026-06-01T00:00:00Z", clock_iso="2026-05-15T00:00:00Z",
    )
    guest = create_record(full_name="WG", primary_email="wg@x.com")
    validate_success(api.set_clock("2026-06-05T00:00:00Z", STAFF))

    resp = api.create_registration(
        ctx["event"]["id"],
        {"tier_id": ctx["tier"]["id"], "alumni_id": guest["id"]},
        make_alumni_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SALES_WINDOW_CLOSED)


def test_registration_cancel_idempotent_second_cancel_rejected(api):
    """PRD §3.4: "The registrant may cancel a registration that is still in
    `PENDING_PAYMENT`, moving it to `CANCELLED` with `cancelled_reason` of
    `REGISTRANT`"; PRD §2.10: "**State** — the target resource is in a valid
    from-state for the requested transition (`ERR_INVALID_STATE`, all action
    endpoints)." A second cancel finds no valid from-state.

    Design: Corner/state_machines/registration_cancel_idempotent_second_cancel_rejected
    """
    ctx = _open_event_ctx(api)
    guest = create_record(full_name="IGuest", primary_email="iguest@x.com")
    pending = register(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])

    cancelled = validate_success(
        api.cancel_registration(pending["id"], make_alumni_headers(guest["id"]))
    )
    assert cancelled["payment_status"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "REGISTRANT"

    resp = api.cancel_registration(pending["id"], make_alumni_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_fk_reverse_reachability_registrations_of_event(api):
    """PRD §3.4: "Registrations can be listed per event with a
    `payment_status` filter, or across the system filtered by `alumni_id`,
    `tier_id`, `event_id`, or `payment_status`."

    Design: Corner/endpoints/fk_reverse_reachability_registrations_of_event
    """
    ctx = _open_event_ctx(api)
    guest1 = create_record(full_name="FG1", primary_email="fg1@x.com")
    guest2 = create_record(full_name="FG2", primary_email="fg2@x.com")
    register(ctx["event"]["id"], ctx["tier"]["id"], guest1["id"])
    register(ctx["event"]["id"], ctx["tier"]["id"], guest2["id"])

    resp = api.list_event_registrations(ctx["event"]["id"], STAFF)
    data, _meta = validate_paginated(resp)
    assert len(data) == 2
    assert all(row["event_id"] == ctx["event"]["id"] for row in data)


def test_posture_sold_out_derivation(api):
    """PRD §3.4: "otherwise it is `SOLD_OUT` when no tier remains bookable —
    every tier having a positive `capacity` fully reached by its `sold_count`
    — and `OPEN` when at least one tier is bookable." Refunding "re-derives
    posture", returning the event to OPEN once the seat is released.

    Design: Corner/calculations/posture_sold_out_derivation
    """
    ctx = _open_event_ctx(api, capacity=1)
    guest = create_record(full_name="SG", primary_email="sg@x.com")
    confirmed = register_and_confirm(ctx["event"]["id"], ctx["tier"]["id"], guest["id"])

    event = validate_success(api.get_event(ctx["event"]["id"], STAFF))
    assert event["posture"] == "SOLD_OUT", (
        "Single capacity-1 tier with sold_count == 1 leaves no bookable tier"
    )

    validate_success(api.refund_registration(confirmed["id"], STAFF))
    event = validate_success(api.get_event(ctx["event"]["id"], STAFF))
    assert event["posture"] == "OPEN"
