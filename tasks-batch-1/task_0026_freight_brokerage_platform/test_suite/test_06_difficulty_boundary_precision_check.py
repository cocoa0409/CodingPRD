"""Difficulty Rule 6 — boundary_precision_check.

Numeric / count edges where the formula's behavior pivots on one unit of the
input: SPOT detention at exactly the 120-minute free-window boundary, and a
SmartWay audit on a quarter with zero delivered loads.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_shipper,
    deliver_load,
    get_success_data,
    set_clock,
    setup_awarded_load,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_smartway_audit_payload


class TestDetentionZeroAtFreeWindowBoundary:
    def test_pickup_exactly_at_free_window_boundary_yields_zero_detention(self, api):
        """PRD §3.6: "From that raw minute count the platform subtracts a
        free-minute window: for `CONTRACT`-mode quotes, the window is the
        chosen `ContractRate.detention_free_minutes`; for `SPOT`-mode
        quotes, the window is 120 minutes. The result is clipped at zero,
        then converted to whole billable hours by **ceiling** the value
        divided by sixty up to the next whole hour."

        Design: Difficulty/boundary_precision_check/detention_zero_at_free_window_boundary
        """
        # SPOT (no contract) so free=120; pickup exactly 120 minutes after
        # pickup_window_start_utc → detention_minutes=120 → billable=0 → 0 cents.
        shipper, carrier, quote, load, _contract = setup_awarded_load(
            pickup_window_start_utc="2026-06-10T08:00:00Z",
            pickup_window_end_utc="2026-06-10T18:00:00Z",
            distance_miles=400, requested_equipment="DRY_VAN",
            use_contract=False,
        )
        delivered = deliver_load(
            load, carrier,
            actual_pickup_at_utc="2026-06-10T10:00:00Z",
            actual_delivery_at_utc="2026-06-11T10:00:00Z",
        )
        assert delivered["detention_charge_cents"] == 0
        assert delivered["status"] == "DELIVERED"

    def test_pickup_one_minute_past_free_window_charges_one_billable_hour(self, api):
        """PRD §3.6: "From that raw minute count the platform subtracts a
        free-minute window: for `CONTRACT`-mode quotes, the window is the
        chosen `ContractRate.detention_free_minutes`; for `SPOT`-mode
        quotes, the window is 120 minutes. The result is clipped at zero,
        then converted to whole billable hours by **ceiling** the value
        divided by sixty up to the next whole hour. The whole-hour count
        is then multiplied by the per-hour detention rate —
        `ContractRate.detention_rate_per_hour_cents` in CONTRACT mode, or
        a flat 7500 cents per hour in SPOT mode — to yield
        `Load.detention_charge_cents`."

        Crossing the boundary by one minute: 121 - 120 = 1 minute billable;
        ceil(1/60) = 1 hour × 7500 = 7500 cents. This anchors the boundary
        from the other side of the edge tested above.

        Design: Difficulty/boundary_precision_check/detention_zero_at_free_window_boundary
        """
        shipper, carrier, quote, load, _contract = setup_awarded_load(
            pickup_window_start_utc="2026-06-10T08:00:00Z",
            pickup_window_end_utc="2026-06-10T18:00:00Z",
            distance_miles=400, requested_equipment="DRY_VAN",
            use_contract=False,
        )
        delivered = deliver_load(
            load, carrier,
            actual_pickup_at_utc="2026-06-10T10:01:00Z",
            actual_delivery_at_utc="2026-06-11T10:01:00Z",
        )
        assert delivered["detention_charge_cents"] == 7500


class TestSmartwayAuditZeroLoadQuarterIsFailing:
    def test_zero_load_quarter_yields_zero_ratio_and_failing(self, api):
        """PRD §3.8: "when `total_loads` is zero, the ratio is fixed at zero.
        The audit's `compliance_status` is then derived from the ratio
        against two thresholds: a ratio at or above 0.60 is `PASSING`, a
        ratio at or above 0.40 but strictly below 0.60 is `AT_RISK`, and a
        ratio strictly below 0.40 is `FAILING`. A zero-load audit
        (total_loads is zero, ratio is zero) is `FAILING`."

        Design: Difficulty/boundary_precision_check/smartway_audit_zero_load_quarter_is_failing
        """
        set_clock("2026-08-01T00:00:00Z")  # 2026Q2 fully past.
        shipper = create_shipper(credit_limit_cents=1_000_000)
        res = api.create_smartway_audit(
            create_smartway_audit_payload(shipper["id"], "2026Q2"),
            TEST_USERS["broker_ops_headers"],
        )
        body = get_success_data(res)
        assert body["total_loads"] == 0
        assert body["smartway_ratio"] == 0 or body["smartway_ratio"] == 0.0
        assert body["compliance_status"] == "FAILING"

    def test_zero_load_audit_carries_smartway_loads_zero(self, api):
        """PRD §3.8: "The `total_loads` count enumerates `Load` rows whose
        owning `QuoteRequest.shipper_id` equals the audit's shipper, whose
        `status` is one of `DELIVERED`, `INVOICED`, or `CLOSED`, and whose
        `actual_delivery_at_utc` falls within the half-open quarter
        interval (inclusive on the quarter's start UTC, exclusive on the
        quarter's end UTC). The `smartway_loads` count is the subset of
        those whose awarded `Carrier.smartway_tier` at delivery time is
        one of `BRONZE`, `SILVER`, or `GOLD`."

        On a zero-total set the subset (smartway_loads) is also zero — the
        formula's smartway_loads ≤ total_loads invariant lands at the
        degenerate end of the range.

        Design: Difficulty/boundary_precision_check/smartway_audit_zero_load_quarter_is_failing
        """
        set_clock("2026-08-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=1_000_000)
        res = api.create_smartway_audit(
            create_smartway_audit_payload(shipper["id"], "2026Q2"),
            TEST_USERS["broker_ops_headers"],
        )
        body = get_success_data(res)
        assert body["total_loads"] == 0
        assert body["smartway_loads"] == 0
