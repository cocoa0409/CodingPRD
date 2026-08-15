"""Pickup cost estimate rounding order, add/remove compensation, and the dock
30-minute buffered-overlap scheduling rule."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    PICKUP_BASE_FEE,
    TEST_USERS,
    create_draft_pickup,
    get_container,
    get_pickup,
    make_pi_headers,
    schedule_window_payload,
    setup_multiple_submitted_pickups,
    setup_pickup_with_tagged_items,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_per_item_rounding_order_pinned_two_items(api):
    """PRD §3.4: "Each linked container contributes a per-item fee equal to its
    `quantity_value` multiplied by the per-gallon disposal rate for its hazard class
    — 12.50 for `FLAMMABLE`, 11.00 for `OXIDIZER`, 9.75 for `CORROSIVE`, 21.20 for
    `TOXIC`, 45.00 for `CONTROLLED_SUBSTANCE`, and 60.00 for `SELECT_AGENT` — with
    each per-item fee first rounded half-up to 2 decimal places. The `estimated_cost`
    is then the sum of those already-rounded per-item fees plus a flat base fee of
    75.00. Summing first and rounding once at the end is a different interpretation
    that can differ by cents and is not the prescribed order."
    (Two TOXIC items of 0.2375 gal: per-item 0.2375 * 21.20 = 5.035 -> 5.04 each;
    total 75.00 + 5.04 + 5.04 = 85.08, not the 85.07 of sum-then-round.)

    Design: Difficulty/combinatorial_formula/pickup_cost_per_item_rounding_order
    """
    ctx = setup_pickup_with_tagged_items(
        quantities=(0.2375, 0.2375), hazard_class="TOXIC", name="Chem D", room="104"
    )
    pickup = get_pickup(ctx["pickup"]["id"])
    assert pickup["estimated_quantity_total"] == pytest.approx(0.475, abs=1e-9)
    assert pickup["estimated_cost"] == pytest.approx(85.08, abs=0.005), (
        f"per-item rounding order must yield 85.08, got {pickup['estimated_cost']}"
    )


def test_per_item_rounding_order_pinned_three_items(api):
    """PRD §3.4: "with each per-item fee first rounded half-up to 2 decimal places.
    The `estimated_cost` is then the sum of those already-rounded per-item fees plus
    a flat base fee of 75.00. Summing first and rounding once at the end is a
    different interpretation that can differ by cents and is not the prescribed
    order."
    (Three TOXIC items of 0.2375 gal: per-item 5.04 x 3 = 15.12 + 75.00 = 90.12;
    sum-then-round would give 15.105 -> 15.11 -> 90.11.)

    Design: Difficulty/combinatorial_formula/pickup_cost_per_item_rounding_order
    """
    ctx = setup_pickup_with_tagged_items(
        quantities=(0.2375, 0.2375, 0.2375), hazard_class="TOXIC", name="Chem D3", room="104"
    )
    pickup = get_pickup(ctx["pickup"]["id"])
    assert pickup["estimated_quantity_total"] == pytest.approx(0.7125, abs=1e-9)
    assert pickup["estimated_cost"] == pytest.approx(90.12, abs=0.005), (
        f"per-item rounding order must yield 90.12, got {pickup['estimated_cost']}"
    )


def test_add_then_remove_restores_totals_to_base_fee(api):
    """PRD §3.4: "Adding sets the container's `pickup_request_id` to the request;
    removing clears it to null. Either change recomputes the request's economics and
    increments the request's `version` by 1." and "The `estimated_cost` is then the
    sum of those already-rounded per-item fees plus a flat base fee of 75.00."
    PRD §3.4: "The `estimated_quantity_total` is the sum of `quantity_value` over the
    containers linked to the request that are still `WASTE_TAGGED`."

    Design: Difficulty/compensating_invariant/pickup_totals_conserved_add_remove
    """
    ctx = setup_pickup_with_tagged_items(quantities=(2.5,), name="Lab R", room="118")
    pickup, pi, container = ctx["pickup"], ctx["pi"], ctx["containers"][0]
    # fixture already linked the item; verify the linked state, then remove it
    linked = get_pickup(pickup["id"])
    assert linked["estimated_quantity_total"] == pytest.approx(2.5, abs=1e-6)
    assert linked["estimated_cost"] == pytest.approx(75.00 + 31.25, abs=0.005)

    removed = validate_success(
        api.remove_pickup_item(
            pickup["id"], {"container_id": container["id"]}, make_pi_headers(pi["id"])
        ),
        200,
    )
    assert removed["estimated_quantity_total"] == pytest.approx(0.0, abs=1e-9)
    assert removed["estimated_cost"] == pytest.approx(PICKUP_BASE_FEE, abs=0.005), (
        "after remove-item only the 75.00 base fee remains — no rounding residue"
    )
    assert get_container(container["id"])["pickup_request_id"] is None


def test_remove_one_of_two_items_keeps_remaining_economics(api):
    """PRD §3.4: "Adding sets the container's `pickup_request_id` to the request;
    removing clears it to null. Either change recomputes the request's economics and
    increments the request's `version` by 1." and "The `estimated_quantity_total` is
    the sum of `quantity_value` over the containers linked to the request that are
    still `WASTE_TAGGED`."

    Design: Difficulty/compensating_invariant/pickup_totals_conserved_add_remove
    """
    ctx = setup_pickup_with_tagged_items(quantities=(2.5, 1.0), name="Lab R2", room="118")
    pickup, pi, containers = ctx["pickup"], ctx["pi"], ctx["containers"]

    both = get_pickup(pickup["id"])
    assert both["estimated_quantity_total"] == pytest.approx(3.5, abs=1e-6)
    # fees: round(2.5*12.50)=31.25 and round(1.0*12.50)=12.50 -> 75.00 + 43.75
    assert both["estimated_cost"] == pytest.approx(118.75, abs=0.005)

    after = validate_success(
        api.remove_pickup_item(
            pickup["id"], {"container_id": containers[0]["id"]}, make_pi_headers(pi["id"])
        ),
        200,
    )
    assert after["estimated_quantity_total"] == pytest.approx(1.0, abs=1e-6)
    assert after["estimated_cost"] == pytest.approx(87.50, abs=0.005)
    assert get_container(containers[0]["id"])["pickup_request_id"] is None
    assert get_container(containers[1]["id"])["pickup_request_id"] == pickup["id"]


def test_dock_gap_exactly_thirty_minutes_allowed(api):
    """PRD §3.4: "The dock enforces a 30-minute buffer: no other `SCHEDULED` pickup at
    the same `dock_id` may have a window that falls within 30 minutes of the new
    window on either side, while a gap of exactly 30 minutes is allowed; a violation
    is rejected with `ERR_DOCK_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/dock_thirty_minute_buffer_overlap
    """
    ctx = setup_multiple_submitted_pickups(2)
    p1, p2 = ctx["pickups"]

    scheduled1 = validate_success(
        api.schedule_pickup_request(
            p1["id"], schedule_window_payload(dock_id="DOCK-1"), ADMIN
        ),
        200,
    )
    assert scheduled1["status"] == "SCHEDULED"

    # exactly a 30-minute gap after p1's 10:00-11:00 window
    scheduled2 = validate_success(
        api.schedule_pickup_request(
            p2["id"],
            schedule_window_payload(
                dock_id="DOCK-1",
                window_start="2026-08-10T11:30:00Z",
                window_end="2026-08-10T12:30:00Z",
            ),
            ADMIN,
        ),
        200,
    )
    assert scheduled2["status"] == "SCHEDULED", "a gap of exactly 30 minutes is allowed"
    assert scheduled2["dock_id"] == "DOCK-1"
    # PRD §3.4: "Scheduling stores the dock and window on the request". PRD pins
    # the three-fractional-digit format only for server-stamped timestamps
    # (§2.4 created_at/updated_at, §2.5 mutation stamps); the serialization of a
    # client-supplied window is unspecified, so compare the instant, not the string.
    stored_start = datetime.fromisoformat(scheduled2["window_start"].replace("Z", "+00:00"))
    assert stored_start == datetime(2026, 8, 10, 11, 30, 0, tzinfo=timezone.utc)


def test_dock_gap_fifteen_minutes_conflicts(api):
    """PRD §3.4: "The dock enforces a 30-minute buffer: no other `SCHEDULED` pickup at
    the same `dock_id` may have a window that falls within 30 minutes of the new
    window on either side, while a gap of exactly 30 minutes is allowed; a violation
    is rejected with `ERR_DOCK_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/dock_thirty_minute_buffer_overlap
    """
    ctx = setup_multiple_submitted_pickups(2)
    p1, p3 = ctx["pickups"]

    validate_success(
        api.schedule_pickup_request(
            p1["id"], schedule_window_payload(dock_id="DOCK-1"), ADMIN
        ),
        200,
    )

    # only a 15-minute gap after p1's 10:00-11:00 window
    res = api.schedule_pickup_request(
        p3["id"],
        schedule_window_payload(
            dock_id="DOCK-1",
            window_start="2026-08-10T11:15:00Z",
            window_end="2026-08-10T12:00:00Z",
        ),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)
    assert get_pickup(p3["id"])["status"] == "SUBMITTED", "rejected schedule leaves status SUBMITTED"
