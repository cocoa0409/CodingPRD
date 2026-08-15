"""Close cascade tests (Difficulty rule 4, instance 2)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_hr_analyst_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    set_clock,
    run_case_to_closed,
    validate_success,
    get_success_data,
)


def _setup_pending_closure_case_with_snapshot():
    """
    Snapshot computed BEFORE the case closes; case at PENDING_CLOSURE with
    subject+reporter notices SENT.
    Returns (case_id, snapshot_id, inv1).
    """
    channel = setup_intake_channel(
        channel_code="HOTLINE", display_name="Hotline D",
        default_category="POLICY_VIOLATION", default_severity="LOW",
        sla_business_days=10,
    )
    reporter = setup_employee(location_code="SF")
    subject = setup_employee(location_code="SF")
    _, inv1 = setup_investigator()
    _, inv2 = setup_investigator()
    _, inv3 = setup_investigator()
    # Snapshot at this point should show no closed cases
    set_clock("2026-08-10T00:00:00Z")
    snap_resp = api_client.create_trend_snapshot(
        {"scope_type": "LOCATION", "scope_key": "SF", "window_kind": "ROLLING_90D"},
        make_hr_analyst_headers(),
    )
    snapshot = get_success_data(snap_resp)
    assert snapshot["closed_case_count"] == 0
    # Drive a case through the pipeline to CLOSED
    case, finding, action, n_sub, n_rep = run_case_to_closed(
        channel["id"], subject["id"], inv1, inv2, inv3,
        reporter_employee_id=reporter["id"],
        category="POLICY_VIOLATION", severity="LOW",
        action_type="NO_ACTION", severity_points=0,
        substantiation_outcome="UNSUBSTANTIATED",
    )
    return case, snapshot, inv1


class TestCloseCascade:
    def test_close_decrements_investigator_active_case_count(self):
        """PRD §3.6: "A successful closure stamps `closed_at` from the logical
        clock and derives `days_to_close` as the calendar days between
        `intake_received_at` and `closed_at` for this most recent closure; it
        recomputes the assigned investigator's `active_case_count` downward by
        one."

        Design: Difficulty/transitive_cascade/close_cascades_investigator_count_then_trend_stale
        """
        case, snapshot, inv1 = _setup_pending_closure_case_with_snapshot()
        # The fixture already closed the case; just verify post-conditions
        assert case["status"] == "CLOSED"
        assert case["closed_at"] is not None
        assert case["days_to_close"] is not None
        inv_after = get_success_data(
            api_client.get_investigator(inv1["id"], TEST_USERS["er_manager_headers"])
        )
        assert inv_after["active_case_count"] == 0, (
            f"active_case_count expected 0 after close, got {inv_after['active_case_count']}"
        )

    def test_close_marks_matching_trend_snapshot_stale(self):
        """PRD §3.6: "it marks every trend snapshot whose scope matches the
        case's manager chain or `location_code` as stale (§3.7)."
        PRD §3.7: "A snapshot's `is_stale` flag starts false; it is set true
        whenever an underlying case closes or reopens after the snapshot's
        `as_of`."

        Design: Difficulty/transitive_cascade/close_cascades_investigator_count_then_trend_stale
        """
        case, snapshot, inv1 = _setup_pending_closure_case_with_snapshot()
        # The close already happened in the fixture; snapshot must now be stale
        snap_after = get_success_data(
            api_client.get_trend_snapshot(snapshot["id"], make_hr_analyst_headers())
        )
        assert snap_after["is_stale"] is True, (
            f"Snapshot is_stale expected True after the case closed, got {snap_after['is_stale']}"
        )
