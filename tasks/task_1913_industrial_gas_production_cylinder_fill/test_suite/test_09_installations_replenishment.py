"""Bulk installations and replenishment: spacing buffer, OCC supersede,
low-level auto-creation, and installation state gating (PRD §3.8, §3.1, §2.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_test_customer,
    create_test_installation,
    get_installation,
    set_logical_clock,
    setup_active_installation,
    validate_error,
    validate_paginated,
    validate_success,
)

LC = TEST_USERS["logistics_coordinator_headers"]
PM = TEST_USERS["plant_manager_headers"]


# --- Difficulty: resource_temporal_overlap / replenishment_gap_buffer_semantics ---

def _setup_delivered_installation():
    """ACTIVE installation (level 2000 / cap 5000 / max order 3000) with one
    order DELIVERED at 2026-08-02T08:00:00Z. Returns (ctx, order, version)."""
    ctx = setup_active_installation()
    inst = ctx["installation"]
    version = get_installation(inst["id"])["version"]
    order = validate_success(
        api_client.create_replenishment_order(
            {"installation_id": inst["id"],
             "scheduled_delivery_at": "2026-08-02T08:00:00Z",
             "expected_installation_version": version},
            LC,
        ),
        201,
    )
    set_logical_clock("2026-08-02T08:00:00Z")
    delivered = validate_success(
        api_client.set_replenishment_order_status(order["id"], {"target_status": "DELIVERED"}, LC),
        200,
    )
    assert delivered["status"] == "DELIVERED"
    # Delivery topped the installation: 2000 + 3000 = 5000 (at capacity).
    assert get_installation(inst["id"])["current_level_liters"] == pytest.approx(
        5000.0, abs=0.01
    )
    return ctx, delivered


def test_replenishment_inside_24h_gap_rejected(api):
    """PRD §3.8: "Spacing is enforced against delivery history: the scheduled
    instant must be at least 24 hours after the `delivered_at` of the
    installation's most recently delivered order; with no prior delivered order,
    there is no spacing constraint, and a violation is rejected with
    `ERR_REPLENISHMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/replenishment_gap_buffer_semantics
    """
    ctx, delivered = _setup_delivered_installation()
    inst = ctx["installation"]
    version = get_installation(inst["id"])["version"]
    res = api.create_replenishment_order(
        {"installation_id": inst["id"],
         "scheduled_delivery_at": "2026-08-03T07:59:00Z",
         "expected_installation_version": version},
        LC,
    )
    validate_error(res, ApiErrorId.ERR_REPLENISHMENT_WINDOW_CONFLICT.value)


def test_replenishment_at_exact_24h_gap_allowed(api):
    """PRD §3.8: "the scheduled instant must be at least 24 hours after the
    `delivered_at` of the installation's most recently delivered order" —
    exactly 24 hours satisfies "at least".
    PRD §3.8: "The order quantity is fixed at creation as `requested_qty_liters`,
    the smallest of three values — the installation's remaining capacity (its
    capacity minus its current level), the 20000-liter truck capacity, and the
    installation's `max_order_qty_liters`; a result of zero or less is rejected
    with `ERR_INVALID_REQUEST`."
    PRD §3.1: "the governing reading is the one with the greatest `measured_at`,
    with ties broken in favor of the later `created_at` — a later-recorded
    reading wins an equal `measured_at`."

    Design: Difficulty/resource_temporal_overlap/replenishment_gap_buffer_semantics
    """
    ctx, delivered = _setup_delivered_installation()
    inst = ctx["installation"]
    # Dip reading at the same measured_at as the delivery reading; recorded
    # later, it wins the tie and drops the current level to 1000.
    validate_success(
        api.create_telemetry_reading(
            {"installation_id": inst["id"], "measured_level_liters": 1000,
             "measured_at": "2026-08-02T08:00:00Z", "source": "MANUAL_DIP"},
            LC,
        ),
        201,
    )
    inst_after = get_installation(inst["id"])
    assert inst_after["current_level_liters"] == pytest.approx(1000.0, abs=0.01)

    res = api.create_replenishment_order(
        {"installation_id": inst["id"],
         "scheduled_delivery_at": "2026-08-03T08:00:00Z",
         "expected_installation_version": inst_after["version"]},
        LC,
    )
    order = validate_success(res, 201)
    assert order["status"] == "PENDING"
    assert order["requested_qty_liters"] == pytest.approx(3000.0, abs=0.01), (
        "min(5000 - 1000, 20000, 3000) evaluated at creation"
    )


# --- Corner: complexity_layers / occ_replenishment_supersede_and_stale_create ---

def test_replenishment_stale_version_rejected_and_fresh_supersedes(api):
    """PRD §2.7: "Creating a replenishment order via
    `POST /api/replenishment-orders` requires a non-optional
    `expected_installation_version` carrying the caller's last observed `version`
    of the installation. A mismatch with the installation's current `version` is
    rejected with `ERR_STALE_VERSION` (HTTP 412); creation supersedes any pending
    order on the installation, and a caller whose view is stale cannot have seen
    the order its request would supersede."
    PRD §3.8: "Creating an order supersedes any existing `PENDING` order on the
    same installation: the older order moves to `SUPERSEDED` with its
    `superseded_by_order_id` pointing at the new order, and the installation's
    `version` increments."

    Design: Corner/complexity_layers/occ_replenishment_supersede_and_stale_create
    """
    ctx = setup_active_installation()
    inst = ctx["installation"]
    version = get_installation(inst["id"])["version"]

    first = validate_success(
        api.create_replenishment_order(
            {"installation_id": inst["id"],
             "scheduled_delivery_at": "2026-08-05T08:00:00Z",
             "expected_installation_version": version},
            LC,
        ),
        201,
    )
    assert first["requested_qty_liters"] == pytest.approx(3000.0, abs=0.01), (
        "min(5000 - 2000, 20000, 3000)"
    )

    # Replaying the pre-first-create version is now stale.
    stale = api.create_replenishment_order(
        {"installation_id": inst["id"],
         "scheduled_delivery_at": "2026-08-06T08:00:00Z",
         "expected_installation_version": version},
        LC,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    fresh_version = get_installation(inst["id"])["version"]
    second = validate_success(
        api.create_replenishment_order(
            {"installation_id": inst["id"],
             "scheduled_delivery_at": "2026-08-06T08:00:00Z",
             "expected_installation_version": fresh_version},
            LC,
        ),
        201,
    )
    assert second["status"] == "PENDING"
    superseded = validate_success(
        api_client.get_replenishment_order(first["id"], LC), 200
    )
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_order_id"] == second["id"]


# --- Corner: complexity_layers / auto_replenishment_created_on_low_installation_level ---

def test_low_level_reading_auto_creates_one_pending_order(api):
    """PRD §3.1: "When a reading posted against a bulk installation leaves the
    installation's current level at or below its reorder point and no
    replenishment order is currently `PENDING` for it, the system automatically
    creates a replenishment order — quantity computed per §3.8, delivery
    scheduled 24 hours after the current clock instant — and increments the
    installation's `version`."

    Design: Corner/complexity_layers/auto_replenishment_created_on_low_installation_level
    """
    ctx = setup_active_installation()
    inst = ctx["installation"]
    set_logical_clock("2026-08-01T06:00:00Z")

    validate_success(
        api.create_telemetry_reading(
            {"installation_id": inst["id"], "measured_level_liters": 350,
             "measured_at": "2026-08-01T01:00:00Z", "source": "IOT_SENSOR"},
            LC,
        ),
        201,
    )
    data, meta = validate_paginated(
        api_client.list_replenishment_orders(LC, params={"installation_id": inst["id"]})
    )
    pending = [o for o in data if o["status"] == "PENDING"]
    assert len(pending) == 1, "exactly one auto-created order"
    assert pending[0]["requested_qty_liters"] == pytest.approx(3000.0, abs=0.01), (
        "min(5000 - 350, 20000, 3000)"
    )
    assert pending[0]["scheduled_delivery_at"] == "2026-08-02T06:00:00Z", (
        "clock + 24 hours"
    )

    # A second low reading while one is PENDING creates nothing.
    validate_success(
        api.create_telemetry_reading(
            {"installation_id": inst["id"], "measured_level_liters": 300,
             "measured_at": "2026-08-01T02:00:00Z", "source": "IOT_SENSOR"},
            LC,
        ),
        201,
    )
    data, meta = validate_paginated(
        api_client.list_replenishment_orders(LC, params={"installation_id": inst["id"]})
    )
    pending = [o for o in data if o["status"] == "PENDING"]
    assert len(pending) == 1, "no duplicate while a PENDING order exists"


# --- Corner: state_machines / replenish_on_proposed_installation_rejected ---

def test_replenish_on_proposed_installation_rejected(api):
    """PRD §3.8: "While an installation is `PAUSED`, creating a new replenishment
    order against it is rejected with `ERR_INSTALLATION_INVALID_STATE` — only
    `ACTIVE` installations accept orders."

    Design: Corner/state_machines/replenish_on_proposed_installation_rejected
    """
    customer = create_test_customer(account_name="C-SM5")
    inst = create_test_installation(customer["id"])
    assert inst["status"] == "PROPOSED"
    res = api.create_replenishment_order(
        {"installation_id": inst["id"],
         "scheduled_delivery_at": "2026-08-05T08:00:00Z",
         "expected_installation_version": inst["version"]},
        LC,
    )
    validate_error(res, ApiErrorId.ERR_INSTALLATION_INVALID_STATE.value)
