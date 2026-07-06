"""Boundary precision (inclusive thresholds) and temporal overlap semantics."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_client_admin_headers, make_location_manager_headers,
    TEST_USERS,
    set_clock, create_plan, create_client, create_location, create_product,
    create_par_level, create_subscription, activate_subscription,
    get_first_rotation_cycle, create_delivery,
    setup_active_subscription,
    close_and_get_invoice,
)


# ─────────────────────────────────────────────────────────────
# Difficulty rule 6 — boundary_precision_check
# ─────────────────────────────────────────────────────────────

def test_subscription_fee_headcount_at_threshold_applies_discount(api):
    """PRD §3.7: "If the client's headcount is at least the plan's
    volume_discount_threshold_headcount (the boundary is inclusive), the raw amount is
    multiplied by one minus volume_discount_pct to yield a discounted amount."

    Design: Difficulty/boundary_precision_check/subscription_fee_headcount_at_threshold_inclusive
    """
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        plan_overrides={
            "tier": "G-BND", "billing_type": "PER_EMPLOYEE",
            "base_fee_cents": 1000, "per_employee_fee_cents": 200,
            "volume_discount_threshold_headcount": 50, "volume_discount_pct": 0.10,
        },
        client_overrides={"name": "Edge-BND", "headcount": 50},
    )
    state = close_and_get_invoice(state, close_clock="2026-07-05T00:00:00Z")
    # At threshold-inclusive: raw = 200*50 = 10000; discounted = 9000 (rounded no-op);
    # fee = 1000 + 9000 = 10000.
    assert state["invoice"]["subscription_fee_cents"] == 10000, \
        f"headcount==threshold must apply discount; expected 10000, got {state['invoice']['subscription_fee_cents']}"


def test_subscription_fee_headcount_one_below_threshold_no_discount(api):
    """PRD §3.7: "If headcount is strictly less than the threshold, no discount is applied
    and the raw per-employee amount is used as-is."

    Design: Difficulty/boundary_precision_check/subscription_fee_headcount_at_threshold_inclusive
    """
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        plan_overrides={
            "tier": "G-BND2", "billing_type": "PER_EMPLOYEE",
            "base_fee_cents": 1000, "per_employee_fee_cents": 200,
            "volume_discount_threshold_headcount": 50, "volume_discount_pct": 0.10,
        },
        client_overrides={"name": "Edge-BND2", "headcount": 49},
    )
    state = close_and_get_invoice(state, close_clock="2026-07-05T00:00:00Z")
    # Below threshold: no discount. raw = 200*49 = 9800; fee = 1000 + 9800 = 10800.
    assert state["invoice"]["subscription_fee_cents"] == 10800, \
        f"headcount<threshold: no discount; expected 10800, got {state['invoice']['subscription_fee_cents']}"


def test_delivery_schedule_gap_at_exactly_24h_allowed(api):
    """PRD §2.10: "Deliveries at the same location must be spaced with a 24-hour buffer:
    a proposed scheduled_at must be at least 24 hours later than any existing non-cancelled
    delivery's scheduled_at at that same location. An exact 24-hour gap is permitted;
    anything strictly less than 24 hours is rejected with ERR_DELIVERY_SCHEDULE_CONFLICT
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/delivery_schedule_gap_at_exactly_24h_allowed
    """
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        location_overrides={"capacity_units": 20},
    )
    # First delivery at 12:00 on 2026-06-01.
    d1 = create_delivery(state["rotation_cycle"]["id"], state["location"]["id"], "2026-06-01T12:00:00Z")
    # Second delivery exactly 24h later — must succeed.
    d2_res = api.create_delivery(
        state["rotation_cycle"]["id"],
        {"location_id": state["location"]["id"], "scheduled_at": "2026-06-02T12:00:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    d2 = validate_success(d2_res, expected_status=201)
    assert d2["status"] == "SCHEDULED", f"exact-24h delivery should succeed; got {d2['status']!r}"


def test_delivery_schedule_slightly_under_24h_rejected(api):
    """PRD §2.10: "anything strictly less than 24 hours is rejected with
    ERR_DELIVERY_SCHEDULE_CONFLICT (HTTP 409)."

    Design: Difficulty/boundary_precision_check/delivery_schedule_gap_at_exactly_24h_allowed
    """
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        location_overrides={"capacity_units": 20},
    )
    from test_helpers import create_delivery as _create_delivery
    _create_delivery(state["rotation_cycle"]["id"], state["location"]["id"], "2026-06-01T12:00:00Z")
    # Slightly under 24h (23:59) — must be rejected.
    res = api.create_delivery(
        state["rotation_cycle"]["id"],
        {"location_id": state["location"]["id"], "scheduled_at": "2026-06-02T11:59:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(res, "ERR_DELIVERY_SCHEDULE_CONFLICT", expected_status=409)


# ─────────────────────────────────────────────────────────────
# Difficulty rule 8 — resource_temporal_overlap
# ─────────────────────────────────────────────────────────────

def test_delivery_schedule_buffer_less_than_24h_rejected(api):
    """PRD §2.10: "a proposed scheduled_at must be at least 24 hours later than any
    existing non-cancelled delivery's scheduled_at at that same location. An exact 24-hour
    gap is permitted; anything strictly less than 24 hours is rejected with
    ERR_DELIVERY_SCHEDULE_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/delivery_scheduled_at_buffer_24h_violation
    """
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        location_overrides={"capacity_units": 20},
    )
    create_delivery(state["rotation_cycle"]["id"], state["location"]["id"], "2026-06-01T12:00:00Z")
    # Second delivery ~ 23h59m later — must be rejected.
    res = api.create_delivery(
        state["rotation_cycle"]["id"],
        {"location_id": state["location"]["id"], "scheduled_at": "2026-06-02T11:59:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(res, "ERR_DELIVERY_SCHEDULE_CONFLICT", expected_status=409)


def test_two_deliveries_at_different_locations_bypass_buffer(api):
    """PRD §2.10: "a proposed scheduled_at must be at least 24 hours later than any
    existing non-cancelled delivery's scheduled_at at that same location."

    Design: Difficulty/resource_temporal_overlap/delivery_scheduled_at_buffer_24h_violation
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="TL-1", billing_type="FLAT", flat_fee_cents=1000,
                      volume_discount_threshold_headcount=50)
    client = create_client(name="TL-Co", headcount=5)
    loc1 = create_location(client["id"], name="L1", kind="PANTRY", capacity_units=20)
    loc2 = create_location(client["id"], name="L2", kind="PANTRY", capacity_units=20)
    prod = create_product(sku="TL-P", name="P", category="SNACK", unit_cost_cents=100)
    create_par_level(loc1["id"], prod["id"], 1)
    create_par_level(loc2["id"], prod["id"], 1)
    sub = create_subscription(client["id"], plan["id"], client["version"])
    activate_subscription(sub["id"])
    rc = get_first_rotation_cycle(sub["id"])
    # Delivery at loc1 at 12:00, delivery at loc2 only 1h later — different location so 24h buffer doesn't apply.
    from test_helpers import create_delivery as _create_delivery
    _create_delivery(rc["id"], loc1["id"], "2026-06-01T12:00:00Z")
    res = api.create_delivery(
        rc["id"],
        {"location_id": loc2["id"], "scheduled_at": "2026-06-01T13:00:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    d = validate_success(res, expected_status=201)
    assert d["status"] == "SCHEDULED", \
        f"cross-location deliveries share no buffer; expected SCHEDULED, got {d['status']!r}"


def test_delivery_outside_rotation_cycle_window_rejected(api):
    """PRD §2.10: "A delivery whose scheduled_at falls outside its cycle's
    [effective_from, effective_to) is rejected with ERR_ROTATION_CYCLE_OVERLAP (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/rotation_cycle_half_open_disjointness
    """
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
    )
    # RC window is 2026-06-01T00:00:00Z..2026-07-01T00:00:00Z (30 days). 2026-08-15 is outside.
    res = api.create_delivery(
        state["rotation_cycle"]["id"],
        {"location_id": state["location"]["id"], "scheduled_at": "2026-08-15T00:00:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(res, "ERR_ROTATION_CYCLE_OVERLAP", expected_status=422)


def test_delivery_before_rotation_cycle_start_rejected(api):
    """PRD §2.10: "The window is expressed as a half-open interval
    [effective_from, effective_to) — inclusive at the start, exclusive at the end. A
    delivery whose scheduled_at falls outside its cycle's [effective_from, effective_to)
    is rejected with ERR_ROTATION_CYCLE_OVERLAP (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/rotation_cycle_half_open_disjointness
    """
    state = setup_active_subscription(clock="2026-06-01T00:00:00Z")
    # RC window is [2026-06-01, 2026-07-01). A scheduled_at strictly before effective_from is outside.
    res = api.create_delivery(
        state["rotation_cycle"]["id"],
        {"location_id": state["location"]["id"], "scheduled_at": "2026-05-15T00:00:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(res, "ERR_ROTATION_CYCLE_OVERLAP", expected_status=422)
