"""Cancellation lead-time refunds and the void cascade, plus the conserved-quantity
invariants (money payout and calendar capacity) and the plan-pause depth-2 cascade.

Queue A / Difficulty: transitive_cascade, boundary_precision_check (refund),
compensating_invariant.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    assert_chef_payout_invariant,
    make_chef_headers, make_client_headers,
    setup_confirmed_booking, setup_confirmed_with_finalized_grocery,
    setup_confirmed_with_deposit_paid, setup_recurring_plan,
    generate_occurrence,
)


# ─── Difficulty / transitive_cascade: cancel -> void grocery -> re-pin quote ─

def test_cancel_voids_finalized_grocery_run_and_repins_quote(api):
    """PRD §3.8: "If the booking has a `FINALIZED` grocery run, that run transitions to
    `VOIDED`, which zeroes the booking's `actual_grocery_total_cents` and re-pins
    `quote_total_cents` back to the estimated grocery basis (the estimated-vs-actual swap
    of §3.4 in reverse) ...". PRD §3.8: "Finally `lifecycle_status` moves to `CANCELLED`
    (terminal) ...".

    Design: Difficulty/transitive_cascade/cancel_voids_grocery_run_repins_quote_depth3
    """
    chef, menu, zone, client, booking, run = setup_confirmed_with_finalized_grocery(
        chef_overrides={"display_name": "Chef D3", "equipment_inventory": ["SOUS_VIDE"]},
        booking_overrides={"service_zip": "94130", "event_start_utc": "2026-08-30T18:00:00Z",
                           "event_end_utc": "2026-08-30T22:00:00Z"},
        line_items=[
            {"label": "a", "actual_cost_cents": 10000},
            {"label": "b", "actual_cost_cents": 10000},
            {"label": "c", "actual_cost_cents": 5000},
        ],
    )
    assert booking["actual_grocery_total_cents"] == 29500
    assert booking["quote_total_cents"] == 88500
    cancelled = validate_success(api.cancel_booking(booking["id"], make_client_headers(client["id"])), 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"
    voided_run = validate_success(api.get_grocery_run(run["id"], make_chef_headers(chef["id"])), 200)
    assert voided_run["status"] == "VOIDED"
    after = validate_success(api.get_booking(booking["id"], make_chef_headers(chef["id"])), 200)
    assert after["actual_grocery_total_cents"] == 0
    assert after["quote_total_cents"] == 87320


def test_cancel_grocery_void_zeroes_actual_total(api):
    """PRD §3.8: "If the booking has a `FINALIZED` grocery run, that run transitions to
    `VOIDED`, which zeroes the booking's `actual_grocery_total_cents` and re-pins
    `quote_total_cents` back to the estimated grocery basis (the estimated-vs-actual swap
    of §3.4 in reverse); `balance_due_cents` is recomputed from that re-pinned quote."

    Design: Difficulty/transitive_cascade/cancel_voids_grocery_run_repins_quote_depth3
    """
    chef, menu, zone, client, booking, run = setup_confirmed_with_finalized_grocery(
        chef_overrides={"display_name": "Chef D3b", "equipment_inventory": ["SOUS_VIDE"]},
        booking_overrides={"service_zip": "94131", "event_start_utc": "2026-08-30T18:00:00Z",
                           "event_end_utc": "2026-08-30T22:00:00Z"},
        line_items=[
            {"label": "a", "actual_cost_cents": 10000},
            {"label": "b", "actual_cost_cents": 10000},
            {"label": "c", "actual_cost_cents": 5000},
        ],
    )
    validate_success(api.cancel_booking(booking["id"], make_client_headers(client["id"])), 200)
    after = validate_success(api.get_booking(booking["id"], make_chef_headers(chef["id"])), 200)
    # quote re-pinned to estimate (87320) implies balance recomputed from it.
    assert after["actual_grocery_total_cents"] == 0
    assert after["quote_total_cents"] == 87320


# ─── Difficulty / transitive_cascade: pause plan -> cancel REQUESTED child ───

def test_pause_plan_cancels_requested_child(api):
    """PRD §3.10: "Pausing is a depth-two cascade: every child booking spawned by the plan
    that is still in `REQUESTED` is cancelled with a refund rate of 0 (none have been paid),
    and any such child that happened to hold a `BOOKING_HOLD` has that block moved to
    `RELEASED`." PRD §3.10: "A plan owner may pause an `ACTIVE` plan, moving its `status`
    to `PAUSED`."

    Design: Difficulty/transitive_cascade/pause_plan_cancels_child_releases_hold_depth2
    """
    chef, menu, client, plan = setup_recurring_plan(
        chef_overrides={"display_name": "Chef D2"},
        plan_overrides={"service_zip": "94110"},
    )
    child = generate_occurrence(client["id"], plan["id"], "2026-08-04")
    paused = validate_success(api.pause_recurring_plan(plan["id"], make_client_headers(client["id"])), 200)
    assert paused["status"] == "PAUSED"
    child_after = validate_success(api.get_booking(child["id"], make_chef_headers(chef["id"])), 200)
    assert child_after["lifecycle_status"] == "CANCELLED"
    assert child_after["recurring_plan_id"] == plan["id"]


def test_pause_plan_marks_status_paused_and_child_links_plan(api):
    """PRD §3.10: "A new plan starts `ACTIVE` with `occurrences_generated` at 0."
    PRD §3.10: "The spawned booking is created in `REQUESTED` status with its
    `recurring_plan_id` set to the plan ...". PRD §3.10: "Pausing is a depth-two cascade:
    every child booking spawned by the plan that is still in `REQUESTED` is cancelled with
    a refund rate of 0 (none have been paid) ...".

    Design: Difficulty/transitive_cascade/pause_plan_cancels_child_releases_hold_depth2
    """
    chef, menu, client, plan = setup_recurring_plan(
        chef_overrides={"display_name": "Chef D2b"},
        plan_overrides={"service_zip": "94110"},
    )
    assert plan["status"] == "ACTIVE"
    child = generate_occurrence(client["id"], plan["id"], "2026-08-11")
    assert child["recurring_plan_id"] == plan["id"]
    assert child["lifecycle_status"] == "REQUESTED"
    validate_success(api.pause_recurring_plan(plan["id"], make_client_headers(client["id"])), 200)
    child_after = validate_success(api.get_booking(child["id"], make_chef_headers(chef["id"])), 200)
    assert child_after["lifecycle_status"] == "CANCELLED"


# ─── Difficulty / boundary_precision_check: refund lead-time 14 days = full ──

def test_refund_lead_time_14_days_full(api):
    """PRD §3.8: "If the lead time is at least 14 days, `cancellation_refund_rate` is 1.00
    (full refund); if it is at least 7 but fewer than 14 days, the rate is 0.50; otherwise
    the rate is 0.00." PRD §3.8: "Each of the booking's `CAPTURED` payments is then refunded
    by setting its `refunded_cents` to its `amount_cents` multiplied by the refund rate,
    rounded half up per payment ...".

    Design: Difficulty/boundary_precision_check/refund_lead_time_boundary_14_days_full
    """
    # Clock 2026-07-01, event 2026-07-15 => exactly 14 days => full refund 1.0.
    chef, menu, zone, client, booking, payment = setup_confirmed_with_deposit_paid(
        deposit_cents=26196,
        chef_overrides={"display_name": "Chef BP1"},
        booking_overrides={"service_zip": "94150", "event_start_utc": "2026-07-15T00:00:00Z",
                           "event_end_utc": "2026-07-15T04:00:00Z"},
    )
    cancelled = validate_success(api.cancel_booking(booking["id"], make_client_headers(client["id"])), 200)
    assert cancelled["cancellation_refund_rate"] == 1.0
    assert cancelled["amount_refunded_cents"] == 26196
    pay_after = validate_success(api.get_payment(payment["id"], make_client_headers(client["id"])), 200)
    assert pay_after["refunded_cents"] == 26196


def test_refund_lead_time_13_days_half(api):
    """PRD §3.8: "At the boundaries: 14 days gives a full refund, 13 days gives half, 7 days
    gives half, and 6 days gives nothing." PRD §3.8: "Each of the booking's `CAPTURED`
    payments is then refunded by setting its `refunded_cents` to its `amount_cents`
    multiplied by the refund rate, rounded half up per payment ...".

    Design: Difficulty/boundary_precision_check/refund_lead_time_boundary_14_days_full
    """
    # Clock 2026-07-01, event 2026-07-14 => exactly 13 days => half refund 0.5.
    # deposit 26196 * 0.5 = 13098.
    chef, menu, zone, client, booking, payment = setup_confirmed_with_deposit_paid(
        deposit_cents=26196,
        chef_overrides={"display_name": "Chef BP1b"},
        booking_overrides={"service_zip": "94151", "event_start_utc": "2026-07-14T00:00:00Z",
                           "event_end_utc": "2026-07-14T04:00:00Z"},
    )
    cancelled = validate_success(api.cancel_booking(booking["id"], make_client_headers(client["id"])), 200)
    assert cancelled["cancellation_refund_rate"] == 0.5
    assert cancelled["amount_refunded_cents"] == 13098


# ─── Difficulty / compensating_invariant: money payout conserved ─────────────

def test_cancel_refund_preserves_chef_payout_money_invariant(api):
    """PRD §3.6: "`captured_payments_cents` is the running sum across the chef's bookings of
    all `Payment.amount_cents` whose status is `CAPTURED` or `REFUNDED`;
    `refunded_payments_cents` is the running sum of all `Payment.refunded_cents`; and
    `payout_accrued_cents` is `captured_payments_cents` minus `refunded_payments_cents`."
    PRD §3.8: "If the lead time is at least 14 days, `cancellation_refund_rate` is 1.00
    (full refund); if it is at least 7 but fewer than 14 days, the rate is 0.50; otherwise
    the rate is 0.00."

    Design: Difficulty/compensating_invariant/cancel_refund_preserves_chef_payout_money_invariant
    """
    # event 2026-07-14 from clock 2026-07-01 => 13 days => half refund: 26196*0.5=13098.
    chef, menu, zone, client, booking, payment = setup_confirmed_with_deposit_paid(
        deposit_cents=26196,
        chef_overrides={"display_name": "Chef CI1"},
        booking_overrides={"service_zip": "94180", "event_start_utc": "2026-07-14T00:00:00Z",
                           "event_end_utc": "2026-07-14T04:00:00Z"},
    )
    cancelled = validate_success(api.cancel_booking(booking["id"], make_client_headers(client["id"])), 200)
    assert cancelled["cancellation_refund_rate"] == 0.5
    chef_after = validate_success(api.get_chef(chef["id"], make_chef_headers(chef["id"])), 200)
    assert chef_after["captured_payments_cents"] == 26196
    assert chef_after["refunded_payments_cents"] == 13098
    assert chef_after["payout_accrued_cents"] == 13098


def test_payout_invariant_holds_after_capture_and_refund(api):
    """PRD §2.10: "The first is money at the chef level: a chef's `payout_accrued_cents`
    always equals its `captured_payments_cents` minus its `refunded_payments_cents`, and
    any operation that captures or refunds a payment recomputes all three together so the
    identity holds after every step." PRD §3.6: "That identity holds after every capture and
    every refund — a cancel-and-refund pair never makes the payout drift from captured minus
    refunded."

    Design: Difficulty/compensating_invariant/cancel_refund_preserves_chef_payout_money_invariant
    """
    chef, menu, zone, client, booking, payment = setup_confirmed_with_deposit_paid(
        deposit_cents=26196,
        chef_overrides={"display_name": "Chef CI1c"},
        booking_overrides={"service_zip": "94181", "event_start_utc": "2026-07-14T00:00:00Z",
                           "event_end_utc": "2026-07-14T04:00:00Z"},
    )
    # Invariant holds after the capture.
    chef_mid = validate_success(api.get_chef(chef["id"], make_chef_headers(chef["id"])), 200)
    assert_chef_payout_invariant(chef_mid)
    validate_success(api.cancel_booking(booking["id"], make_client_headers(client["id"])), 200)
    # And after the compensating refund.
    chef_after = validate_success(api.get_chef(chef["id"], make_chef_headers(chef["id"])), 200)
    assert_chef_payout_invariant(chef_after)


# ─── Difficulty / compensating_invariant: capacity conserved ─────────────────

def test_cancel_restores_active_booking_count(api):
    """PRD §2.10: "The second is calendar capacity: a chef's `active_booking_count` is the
    number of its bookings currently in a `CONFIRMED` or `IN_PREP` state, incremented when
    a booking is confirmed and decremented when it leaves those states by completion or
    cancellation." PRD §3.8: "If the booking had been `CONFIRMED` or `IN_PREP`, its
    `BOOKING_HOLD` availability block is moved to `RELEASED` so the slot is freed, and the
    chef's `active_booking_count` is decremented to restore capacity."

    Design: Difficulty/compensating_invariant/cancel_restores_chef_active_booking_count_capacity_invariant
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        chef_overrides={"display_name": "Chef CI2"},
        booking_overrides={"service_zip": "94185", "event_start_utc": "2026-09-25T18:00:00Z",
                           "event_end_utc": "2026-09-25T22:00:00Z"},
    )
    confirmed_chef = validate_success(api.get_chef(chef["id"], make_chef_headers(chef["id"])), 200)
    assert confirmed_chef["active_booking_count"] == 1
    validate_success(api.cancel_booking(booking["id"], make_client_headers(client["id"])), 200)
    chef_after = validate_success(api.get_chef(chef["id"], make_chef_headers(chef["id"])), 200)
    assert chef_after["active_booking_count"] == 0


def test_cancel_releases_booking_hold_block(api):
    """PRD §3.8: "If the booking had been `CONFIRMED` or `IN_PREP`, its `BOOKING_HOLD`
    availability block is moved to `RELEASED` so the slot is freed, and the chef's
    `active_booking_count` is decremented to restore capacity." PRD §2.7: "A block's
    `status` is either `HELD`, meaning it currently occupies the calendar, or `RELEASED`,
    meaning it no longer does."

    Design: Difficulty/compensating_invariant/cancel_restores_chef_active_booking_count_capacity_invariant
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        chef_overrides={"display_name": "Chef CI2b"},
        booking_overrides={"service_zip": "94186", "event_start_utc": "2026-09-26T18:00:00Z",
                           "event_end_utc": "2026-09-26T22:00:00Z"},
    )
    validate_success(api.cancel_booking(booking["id"], make_client_headers(client["id"])), 200)
    blocks, _meta = api_module_list_blocks(api, chef["id"], booking["id"])
    assert len(blocks) == 1, f"expected exactly one BOOKING_HOLD, got {len(blocks)}"
    assert blocks[0]["status"] == "RELEASED"


def api_module_list_blocks(api, chef_id, booking_id):
    """Helper: list this booking's availability blocks (validate_paginated)."""
    from test_helpers import validate_paginated, make_chef_headers
    return validate_paginated(
        api.list_availability_blocks(make_chef_headers(chef_id), params={"booking_id": booking_id})
    )
