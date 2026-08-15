"""Execution-quality snapshots: benchmark variants, scope filtering, month
window, locking, and provisional-vs-locked reconciliation (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    make_order,
    make_snapshot,
    make_venue,
    set_clock,
    setup_venue_with_active_arrangement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]


def _setup_two_benchmark_orders():
    """Two EXECUTED MARKET orders on one venue (PRD §3.3 scope):
    O1 BUY 100 @10005 vs NBBO 10000/10010; O2 BUY 201 @20012 vs 20000/20020."""
    set_clock("2026-08-05T14:00:00Z")
    venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
    o1 = make_order(client_ref="Q1", symbol="ACME", side="BUY", quantity=100,
                    order_type="MARKET", arrival_nbbo_bid_cents=10000,
                    arrival_nbbo_ask_cents=10010, arrangement_id=arrangement["id"])
    o2 = make_order(client_ref="Q2", symbol="ACME", side="BUY", quantity=201,
                    order_type="MARKET", arrival_nbbo_bid_cents=20000,
                    arrival_nbbo_ask_cents=20020, arrangement_id=arrangement["id"])
    set_clock("2026-08-05T16:00:00Z")
    o1 = validate_success(api_client.order_transition(o1["id"], {
        "to_status": "EXECUTED", "executed_price_cents": 10005,
        "executed_at": "2026-08-05T15:00:00Z"}, OPS))
    o2 = validate_success(api_client.order_transition(o2["id"], {
        "to_status": "EXECUTED", "executed_price_cents": 20012,
        "executed_at": "2026-08-05T15:05:00Z"}, OPS))
    snap_ft = make_snapshot(venue["id"], variant="FAR_TOUCH")
    snap_mid = make_snapshot(venue["id"], variant="MIDPOINT")
    return venue, snap_ft, snap_mid


def _read_snapshot_row(venue_id, variant):
    data, meta = validate_paginated(api_client.list_venue_snapshots(
        venue_id, CA, params={"period_month": "2026-08", "variant": variant}))
    assert meta["total_count"] == 1
    return data[0]


class TestBenchmarkVariants:
    def test_quality_far_touch_benchmark_totals(self, api):
        """PRD §3.3: "Under `FAR_TOUCH`, a `BUY` order's per-share improvement
        is the arrival ask minus the executed price". PRD §3.3:
        "`avg_improvement_cents_per_share` is `total_improvement_cents`
        divided by `total_quantity`, rounded half up to four decimal places".

        Design: Difficulty/dual_variant_calc/quality_benchmark_variants_diverge
        """
        venue, _ft, _mid = _setup_two_benchmark_orders()
        row = _read_snapshot_row(venue["id"], "FAR_TOUCH")
        assert row["order_count"] == 2
        assert row["total_quantity"] == 301
        # (10010-10005)*100 + (20020-20012)*201 = 500 + 1608.
        assert row["total_improvement_cents"] == pytest.approx(2108.00, abs=0.001)
        assert row["avg_improvement_cents_per_share"] == pytest.approx(7.0033, abs=0.0001)

    def test_quality_midpoint_benchmark_diverges(self, api):
        """PRD §3.3: "Under `MIDPOINT`, a `BUY` order's improvement is the
        midpoint minus the executed price" and "the far-touch result is never
        lower than the midpoint result for the same order set."

        Design: Difficulty/dual_variant_calc/quality_benchmark_variants_diverge
        """
        venue, _ft, _mid = _setup_two_benchmark_orders()
        row_ft = _read_snapshot_row(venue["id"], "FAR_TOUCH")
        row_mid = _read_snapshot_row(venue["id"], "MIDPOINT")
        # midpoints 10005 and 20010: 0.00*100 + (20010-20012)*201 = -402.
        assert row_mid["total_improvement_cents"] == pytest.approx(-402.00, abs=0.001)
        assert row_mid["avg_improvement_cents_per_share"] == pytest.approx(-1.3355, abs=0.0001)
        assert row_ft["total_improvement_cents"] != row_mid["total_improvement_cents"], (
            "same orders, same bucket: the pinned variant decides the benchmark")


class TestSnapshotScope:
    def test_execution_quality_excludes_non_executed_orders(self, api):
        """PRD §3.3: "A snapshot's scope is exactly the set of orders whose
        routing arrangement belongs to the snapshot's venue, whose
        `order_type` equals the snapshot's, whose status is `EXECUTED`, and
        whose `executed_at` falls inside the half-open month window; received,
        routed, and cancelled orders never count."

        Design: Corner/calculations/execution_quality_excludes_non_executed_orders
        """
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        make_order(client_ref="F1", symbol="ACME", side="BUY", quantity=100,
                   order_type="MARKET", arrival_nbbo_bid_cents=10000,
                   arrival_nbbo_ask_cents=10010, arrangement_id=arrangement["id"],
                   execute={"price_cents": 10005, "executed_at": "2026-08-10T14:00:00Z"})
        # ROUTED but never executed.
        make_order(client_ref="F2", symbol="ACME", side="BUY", quantity=999,
                   order_type="MARKET", arrangement_id=arrangement["id"])
        # CANCELLED straight from RECEIVED.
        cancelled = make_order(client_ref="F3", symbol="ACME", side="SELL", quantity=777,
                               order_type="MARKET")
        validate_success(api.order_transition(cancelled["id"], {"to_status": "CANCELLED"}, OPS))
        make_snapshot(venue["id"], variant="FAR_TOUCH")

        data, meta = validate_paginated(
            api.list_venue_snapshots(venue["id"], CA, params={"period_month": "2026-08"}))
        assert meta["total_count"] == 1
        row = data[0]
        assert row["order_count"] == 1, "only the EXECUTED order counts"
        assert row["total_quantity"] == 100
        assert row["total_improvement_cents"] == pytest.approx(500.00, abs=0.001)

    def test_execution_quality_month_window_half_open(self, api):
        """PRD §3.3: "its scope is the half-open window from the first instant
        of that month up to — but not including — the first instant of the
        next month."

        Design: Corner/calculations/execution_quality_month_window_half_open
        """
        set_clock("2026-08-31T23:59:59Z")
        venue, arrangement = setup_venue_with_active_arrangement(
            venue_code="NYSE",
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-10-01T00:00:00Z",
        )
        make_order(client_ref="W1", symbol="ACME", side="BUY", quantity=100,
                   order_type="MARKET", arrival_nbbo_bid_cents=10000,
                   arrival_nbbo_ask_cents=10010, arrangement_id=arrangement["id"],
                   execute={"price_cents": 10005, "executed_at": "2026-08-31T23:59:59Z"})
        set_clock("2026-09-01T00:00:00Z")
        make_order(client_ref="W2", symbol="ACME", side="BUY", quantity=100,
                   order_type="MARKET", arrival_nbbo_bid_cents=10000,
                   arrival_nbbo_ask_cents=10010, arrangement_id=arrangement["id"],
                   execute={"price_cents": 10005, "executed_at": "2026-09-01T00:00:00Z"})
        make_snapshot(venue["id"], variant="FAR_TOUCH")

        data, meta = validate_paginated(
            api.list_venue_snapshots(venue["id"], CA, params={"period_month": "2026-08"}))
        assert meta["total_count"] == 1
        assert data[0]["order_count"] == 1, (
            "the 2026-09-01T00:00:00Z execution belongs to the next half-open month window")


class TestSnapshotLock:
    def test_snapshot_lock_rejected_with_routed_order(self, api):
        """PRD §3.3: "no in-scope order — venue and order type matching,
        created before the period's end — may still sit in `RECEIVED` or
        `ROUTED`, otherwise the lock is rejected with `ERR_UNRESOLVED_ORDERS`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/snapshot_lock_blocked_by_unresolved_orders
        """
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        make_order(client_ref="U1", symbol="ACME", side="BUY", quantity=10,
                   order_type="MARKET", arrangement_id=arrangement["id"])
        snapshot = make_snapshot(venue["id"], variant="FAR_TOUCH")

        resp = api.lock_snapshot(snapshot["id"], CA)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_ORDERS)

        row = _read_snapshot_row(venue["id"], "FAR_TOUCH")
        assert row["status"] == "PROVISIONAL", "rejected lock must leave the snapshot PROVISIONAL"

    def test_snapshot_lock_freezes_metrics_after_resolution(self, api):
        """PRD §3.3: "A successful lock computes the metrics one final time
        and freezes them; the snapshot becomes `LOCKED`, admits no further
        transitions, and later executions never change it."

        Design: Difficulty/cross_entity_state_dependency/snapshot_lock_blocked_by_unresolved_orders
        """
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        order = make_order(client_ref="U1", symbol="ACME", side="BUY", quantity=10,
                           order_type="MARKET", arrangement_id=arrangement["id"])
        snapshot = make_snapshot(venue["id"], variant="FAR_TOUCH")
        validate_error(api.lock_snapshot(snapshot["id"], CA),
                       ApiErrorId.ERR_UNRESOLVED_ORDERS)

        set_clock("2026-08-10T15:00:00Z")
        validate_success(api.order_transition(order["id"], {
            "to_status": "EXECUTED", "executed_price_cents": 10005,
            "executed_at": "2026-08-10T14:30:00Z"}, OPS))
        locked = validate_success(api.lock_snapshot(snapshot["id"], CA))
        assert locked["status"] == "LOCKED"
        # FAR_TOUCH BUY: (10010 - 10005) * 10 shares.
        assert locked["total_improvement_cents"] == pytest.approx(50.00, abs=0.001)

    def test_snapshot_locked_is_terminal(self, api):
        """PRD §3.3: "the snapshot becomes `LOCKED`, admits no further
        transitions". PRD §3.3: "or zero when `total_quantity` is zero."

        Design: Corner/state_machines/snapshot_locked_is_terminal
        """
        venue = make_venue(venue_code="NYSE")
        snapshot = make_snapshot(venue["id"], variant="FAR_TOUCH")
        locked = validate_success(api.lock_snapshot(snapshot["id"], CA))
        assert locked["status"] == "LOCKED"
        assert locked["order_count"] == 0, "empty scope locks cleanly"
        assert locked["avg_improvement_cents_per_share"] == 0, "zero-quantity guard"
        resp = api.lock_snapshot(snapshot["id"], CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_duplicate_snapshot_key_rejected(self, api):
        """PRD §3.3: "The combination of venue, order type, month, and variant
        is unique; a colliding creation is rejected with
        `ERR_DUPLICATE_SNAPSHOT` (HTTP 409)."

        Design: Corner/entities/duplicate_snapshot_key_rejected
        """
        venue = make_venue(venue_code="NYSE")
        make_snapshot(venue["id"], variant="FAR_TOUCH")
        resp = api.create_snapshot({
            "venue_id": venue["id"], "order_type": "MARKET",
            "period_month": "2026-08", "variant": "FAR_TOUCH",
        }, CA)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SNAPSHOT)


class TestProvisionalReconciliation:
    def test_provisional_snapshot_reconciles_locked_snapshot_frozen(self, api):
        """PRD §3.3: "While a snapshot is `PROVISIONAL`, every read recomputes
        these four metrics from current order data, so the snapshot is a
        living view of the month." PRD §2.8: "locking the snapshot computes
        the metrics one final time and freezes them, after which later order
        activity never changes the frozen values."

        Design: Corner/complexity_layers/provisional_snapshot_reconciles_locked_snapshot_frozen
        """
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        make_order(client_ref="DR1", symbol="ACME", side="BUY", quantity=100,
                   order_type="MARKET", arrival_nbbo_bid_cents=10000,
                   arrival_nbbo_ask_cents=10010, arrangement_id=arrangement["id"],
                   execute={"price_cents": 10005, "executed_at": "2026-08-10T14:00:00Z"})
        snapshot = make_snapshot(venue["id"], variant="FAR_TOUCH")

        row = _read_snapshot_row(venue["id"], "FAR_TOUCH")
        assert row["total_improvement_cents"] == pytest.approx(500.00, abs=0.001), (
            "PROVISIONAL read recomputes over the single executed order")

        make_order(client_ref="DR2", symbol="ACME", side="BUY", quantity=100,
                   order_type="MARKET", arrival_nbbo_bid_cents=10000,
                   arrival_nbbo_ask_cents=10010, arrangement_id=arrangement["id"],
                   execute={"price_cents": 10005, "executed_at": "2026-08-10T14:00:00Z"})
        row = _read_snapshot_row(venue["id"], "FAR_TOUCH")
        assert row["total_improvement_cents"] == pytest.approx(1000.00, abs=0.001), (
            "PROVISIONAL read reconciles the second execution")

        validate_success(api.lock_snapshot(snapshot["id"], CA))
        make_order(client_ref="DR3", symbol="ACME", side="BUY", quantity=100,
                   order_type="MARKET", arrival_nbbo_bid_cents=10000,
                   arrival_nbbo_ask_cents=10010, arrangement_id=arrangement["id"],
                   execute={"price_cents": 10005, "executed_at": "2026-08-10T14:00:00Z"})
        row = _read_snapshot_row(venue["id"], "FAR_TOUCH")
        assert row["status"] == "LOCKED"
        assert row["total_improvement_cents"] == pytest.approx(1000.00, abs=0.001), (
            "a LOCKED snapshot is frozen even though in-scope executions keep arriving")
