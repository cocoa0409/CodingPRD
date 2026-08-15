"""Work-order verify cascade (PRD §3.6): verification closes the defect chain
and refreshes the asset's maintenance baseline."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_timestamp_instant_equals,
    complete_work_order,
    setup_work_order_in_progress,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]


def _setup_completed_work_order() -> dict:
    """Work order completed during an in-window switching outage; the logical
    clock is at 2026-08-12T10:00:00Z."""
    ctx = setup_work_order_in_progress(
        "2026-08-12T08:00:00Z", "2026-08-12T16:00:00Z", "2026-08-12T10:00:00Z",
        estimated_hours=3,
        asset_overrides={
            "criticality": "MEDIUM",
            "nameplate_mva": 20,
            "install_date": "2019-01-01T00:00:00Z",
            "last_maintenance_completed_at": "2025-08-01T00:00:00Z",
        },
    )
    completed = complete_work_order(
        ctx["work_order"]["id"], ctx["tech_headers"],
        labor_lines=[{"hours": 3.0, "rate_per_hour": 100.00}],
        parts_lines=[{"quantity": 1, "unit_price": 250.00}],
    )
    return {**ctx, "work_order": completed}


class TestWorkOrderVerifyCascade:
    def test_verify_transitions_work_order_and_defect(self):
        """PRD §3.6: "Verification by an `OperationsManager` transitions the
        work order `COMPLETED → VERIFIED`, cascades the defect `RESOLVED →
        VERIFIED`, stamps the asset's `last_maintenance_completed_at` from the
        logical clock, and recomputes the asset's `next_due_date`."

        Design: Difficulty/transitive_cascade/workorder_verify_cascade_depth2
        """
        ctx = _setup_completed_work_order()
        verified = validate_success(
            api_client.verify_work_order(ctx["work_order"]["id"], OPS)
        )
        assert verified["status"] == "VERIFIED"
        defect = validate_success(api_client.get_defect(ctx["defect"]["id"], OPS))
        assert defect["status"] == "VERIFIED"

    def test_verify_refreshes_maintenance_baseline(self):
        """PRD §3.6: "Verification by an `OperationsManager` transitions the
        work order `COMPLETED → VERIFIED`, cascades the defect `RESOLVED →
        VERIFIED`, stamps the asset's `last_maintenance_completed_at` from the
        logical clock, and recomputes the asset's `next_due_date`."
        PRD §3.5: "Both share a baseline: the asset's
        `last_maintenance_completed_at` when set, else its `install_date`."

        Design: Difficulty/transitive_cascade/workorder_verify_cascade_depth2
        """
        ctx = _setup_completed_work_order()
        validate_success(api_client.verify_work_order(ctx["work_order"]["id"], OPS))
        asset = validate_success(api_client.get_asset(ctx["asset"]["id"], OPS))
        # Hop 2: the defect verification stamped the logical clock as the new
        # maintenance baseline.
        assert_timestamp_instant_equals(
            asset["last_maintenance_completed_at"], "2026-08-12T10:00:00Z"
        )
        # Defect is VERIFIED (no open-defect penalty) and no accepted tests
        # exist: score is back to 100, so the full 12-month interval applies
        # from the refreshed baseline.
        assert asset["condition_score"] == pytest.approx(100.00, abs=0.01)
        assert asset["next_due_date"] == "2027-08-12"
