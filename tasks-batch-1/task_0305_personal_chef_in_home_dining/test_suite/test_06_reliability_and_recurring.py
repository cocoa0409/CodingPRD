"""Chef reliability scores (settled vs projected divergence) and the parallel /
cyclic state machines (booking lifecycle x payment axes; recurring-plan cycling).

Queue A / Difficulty: dual_variant_calc (chef reliability), non_linear_state_machine.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    make_chef_headers, make_client_headers,
    pin_clock, create_active_chef, create_chef, create_client,
    create_menu_payload, create_recurring_plan_payload,
    setup_confirmed_booking, setup_recurring_plan,
    pay_deposit,
)


def _reliability_chef_with_one_decline_two_confirms(display_name):
    """Build the canonical reliability scenario:
    one DECLINED terminal booking + two CONFIRMED bookings on one active chef.
    Returns the chef dict after the final confirm."""
    pin_clock()
    chef, menu, zone = create_active_chef(
        chef_overrides={"display_name": display_name, "equipment_inventory": [],
                        "max_bookings_per_day": 5},
    )
    ch = make_chef_headers(chef["id"])
    client = create_client()
    cl = make_client_headers(client["id"])

    # 1) DECLINED booking.
    b_decl = get_success_data(api_client.create_booking({
        "chef_id": chef["id"], "client_id": client["id"], "menu_package_id": menu["id"],
        "party_size": 6, "service_zip": "94110",
        "event_start_utc": "2026-08-10T18:00:00Z", "event_end_utc": "2026-08-10T22:00:00Z",
    }, cl))
    validate_success(api_client.decline_booking(b_decl["id"], ch), 200)

    # 2) First CONFIRMED booking.
    b_c1 = get_success_data(api_client.create_booking({
        "chef_id": chef["id"], "client_id": client["id"], "menu_package_id": menu["id"],
        "party_size": 6, "service_zip": "94110",
        "event_start_utc": "2026-08-11T18:00:00Z", "event_end_utc": "2026-08-11T22:00:00Z",
    }, cl))
    v1 = get_success_data(api_client.get_chef(chef["id"], ch))["version"]
    validate_success(api_client.confirm_booking(b_c1["id"], {"expected_chef_version": v1}, ch), 200)

    # 3) Second CONFIRMED booking.
    b_c2 = get_success_data(api_client.create_booking({
        "chef_id": chef["id"], "client_id": client["id"], "menu_package_id": menu["id"],
        "party_size": 6, "service_zip": "94110",
        "event_start_utc": "2026-08-12T18:00:00Z", "event_end_utc": "2026-08-12T22:00:00Z",
    }, cl))
    v2 = get_success_data(api_client.get_chef(chef["id"], ch))["version"]
    validate_success(api_client.confirm_booking(b_c2["id"], {"expected_chef_version": v2}, ch), 200)

    return get_success_data(api_client.get_chef(chef["id"], ch))


# ─── Difficulty / dual_variant_calc: chef reliability projected vs settled ───

def test_chef_settled_and_projected_scores_have_expected_values(api):
    """PRD §3.7: "Starting from a base of 50, it walks those terminal bookings in
    chronological order ... a `COMPLETED` booking adds 10, a `DECLINED` booking subtracts 8
    (the chef turned a request away), and a `CANCELLED` booking adds nothing ...". PRD §3.7:
    "It takes the same chronological accumulation as the settled score **before** that final
    clamp is applied, then adds 10 for each of the chef's bookings currently in `CONFIRMED`
    or `IN_PREP` — counting not-yet-completed work optimistically as if it will complete —
    and clamps that sum to the inclusive range 0 to 100."

    Design: Difficulty/dual_variant_calc/chef_reliability_projected_vs_settled_divergence
    """
    chef = _reliability_chef_with_one_decline_two_confirms("Chef R")
    # settled: only the DECLINED terminal booking counts -> 50 - 8 = 42.
    assert chef["settled_reliability_score"] == 42
    # projected: 42 + 2 CONFIRMED * 10 = 62.
    assert chef["projected_reliability_score"] == 62


def test_chef_projected_diverges_from_settled_with_confirmed_bookings(api):
    """PRD §3.7: "Because the base is 50, well below the ceiling of 100, the projected score
    is observably higher than the settled score whenever the chef has any `CONFIRMED` or
    `IN_PREP` bookings, and equals it when there are none."

    Design: Difficulty/dual_variant_calc/chef_reliability_projected_vs_settled_divergence
    """
    chef = _reliability_chef_with_one_decline_two_confirms("Chef R2")
    assert chef["projected_reliability_score"] != chef["settled_reliability_score"]
    assert chef["projected_reliability_score"] > chef["settled_reliability_score"]


# ─── Difficulty / non_linear_state_machine: parallel lifecycle x payment ─────

def test_deposit_advances_payment_axis_without_moving_lifecycle(api):
    """PRD §3.6: "A booking's `payment_status` axis runs independently of its lifecycle."
    PRD §3.6: "On success the booking's `payment_status` moves from `UNPAID` to
    `DEPOSIT_PAID` ...". PRD §3.6: "A payment is minted with `status` `CAPTURED`, carries a
    `refunded_cents` that starts at 0, and adds its amount to the booking's
    `amount_captured_cents`, after which `balance_due_cents` is recomputed."

    Design: Difficulty/non_linear_state_machine/booking_parallel_lifecycle_and_payment_axes
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        chef_overrides={"display_name": "Chef P"},
        booking_overrides={"service_zip": "94120", "event_start_utc": "2026-08-25T18:00:00Z",
                           "event_end_utc": "2026-08-25T22:00:00Z"},
    )
    assert booking["lifecycle_status"] == "CONFIRMED"
    assert booking["payment_status"] == "UNPAID"
    pay_deposit(client["id"], booking["id"], 26196)
    after = validate_success(api.get_booking(booking["id"], make_chef_headers(chef["id"])), 200)
    # payment axis advanced, lifecycle axis unchanged.
    assert after["payment_status"] == "DEPOSIT_PAID"
    assert after["lifecycle_status"] == "CONFIRMED"
    assert after["amount_captured_cents"] == 26196
    assert after["balance_due_cents"] == 61124


def test_deposit_payment_does_not_change_lifecycle_status(api):
    """PRD §3.6: "A booking's `payment_status` axis runs independently of its lifecycle. It
    begins at `UNPAID` and is advanced by payments ...". PRD §3.3: "Confirmation is the
    chef's decision to take a `REQUESTED` booking, advancing its `lifecycle_status` from
    `REQUESTED` to `CONFIRMED`."

    Design: Difficulty/non_linear_state_machine/booking_parallel_lifecycle_and_payment_axes
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        chef_overrides={"display_name": "Chef Pb"},
        booking_overrides={"service_zip": "94121", "event_start_utc": "2026-08-26T18:00:00Z",
                           "event_end_utc": "2026-08-26T22:00:00Z"},
    )
    pay_deposit(client["id"], booking["id"], 26196)
    after = validate_success(api.get_booking(booking["id"], make_chef_headers(chef["id"])), 200)
    assert after["lifecycle_status"] == "CONFIRMED"
    assert after["payment_status"] == "DEPOSIT_PAID"


# ─── Difficulty / non_linear_state_machine: cyclic ACTIVE<->PAUSED ───────────

def test_recurring_plan_cycles_active_paused_active(api):
    """PRD §3.10: "A plan owner may pause an `ACTIVE` plan, moving its `status` to
    `PAUSED`." PRD §3.10: "A `PAUSED` plan may be resumed back to `ACTIVE` by its owner,
    after which generation is allowed again."

    Design: Difficulty/non_linear_state_machine/recurring_plan_cyclic_active_paused_active
    """
    chef, menu, client, plan = setup_recurring_plan(
        chef_overrides={"display_name": "Chef C"}, publish_menu=False, with_zone=False,
        plan_overrides={"party_size": 4, "service_zip": "94110"},
    )
    assert plan["status"] == "ACTIVE"
    paused = validate_success(api.pause_recurring_plan(plan["id"], make_client_headers(client["id"])), 200)
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_recurring_plan(plan["id"], make_client_headers(client["id"])), 200)
    assert resumed["status"] == "ACTIVE"


def test_recurring_plan_resume_returns_to_active(api):
    """PRD §3.10: "A `PAUSED` plan may be resumed back to `ACTIVE` by its owner, after which
    generation is allowed again." PRD §3.10: "Generating an occurrence spawns the next
    booking from an `ACTIVE` plan for a supplied `occurrence_date`."

    Design: Difficulty/non_linear_state_machine/recurring_plan_cyclic_active_paused_active
    """
    chef, menu, client, plan = setup_recurring_plan(
        chef_overrides={"display_name": "Chef Cb"}, publish_menu=False, with_zone=False,
        plan_overrides={"party_size": 4, "service_zip": "94110"},
    )
    validate_success(api.pause_recurring_plan(plan["id"], make_client_headers(client["id"])), 200)
    resumed = validate_success(api.resume_recurring_plan(plan["id"], make_client_headers(client["id"])), 200)
    assert resumed["status"] == "ACTIVE"
    # Re-reading confirms the resumed state persists.
    refetched = validate_success(api.get_recurring_plan(plan["id"], make_client_headers(client["id"])), 200)
    assert refetched["status"] == "ACTIVE"
