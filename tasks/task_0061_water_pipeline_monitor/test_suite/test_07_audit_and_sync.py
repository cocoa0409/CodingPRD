"""AuditLog and SyncEvent emission semantics.

Covers PRD §2.9 (governed AuditLog actions, SyncEvent emission, monotonic
sequence_no per (network_id, target_system)) and the per-transition
side-effects pinned in §3.2 / §3.6 / §3.8 / §3.9.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    AUD, CO, SUP, SUP_ALT, TA, TE,
    assert_sequence_monotonic, find_audit_log_rows, find_sync_event_rows,
    iso_from_epoch_ms, get_network, post_reading,
    setup_published_network_with_one_segment,
    setup_under_review_version,
    setup_dma_with_inlet_flow_and_meter,
    setup_work_order_awaiting_verification,
    water_balance_report_payload,
    verify_work_order_payload,
    validate_success,
)


def _list_audit_logs(api, net_id):
    body = api.list_audit_logs(net_id, AUD).json()
    return body["data"]


def _list_sync_events(api, net_id):
    body = api.list_sync_events(net_id, AUD).json()
    return body["data"]


class TestTopologyAuditEvents:
    """PRD §2.9: TOPOLOGY_SUBMITTED, TOPOLOGY_PUBLISHED, TOPOLOGY_REJECTED."""

    def test_submit_writes_topology_submitted_audit_row(self, api):
        """PRD §2.9: "AuditLog rows are written for nine governed action
        values: TOPOLOGY_SUBMITTED ..."

        Claim: submitting a draft writes an AuditLog row with
        action=TOPOLOGY_SUBMITTED and resource_id == the version's id.
        """
        env = setup_under_review_version(api)
        rows = _list_audit_logs(api, env["network"]["id"])
        matched = find_audit_log_rows(rows, "TOPOLOGY_SUBMITTED",
                                       resource_id=env["version"]["id"])
        assert len(matched) >= 1, \
            f"Expected TOPOLOGY_SUBMITTED audit row for version {env['version']['id']}, " \
            f"got {[r.get('action') for r in rows]}"

    def test_approve_writes_topology_published_audit_and_three_sync_events(
        self, api,
    ):
        """PRD §3.2: "three SyncEvent rows are emitted with
        event_type=TOPOLOGY_PUBLISHED — one each to BILLING, GIS, and IM
        — and an AuditLog row is written with action=TOPOLOGY_PUBLISHED."
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]

        audit_rows = _list_audit_logs(api, net_id)
        published_audit = find_audit_log_rows(audit_rows,
                                              "TOPOLOGY_PUBLISHED",
                                              resource_id=base["version"]["id"])
        assert len(published_audit) >= 1

        sync_rows = _list_sync_events(api, net_id)
        published_sync = find_sync_event_rows(
            sync_rows,
            event_type="TOPOLOGY_PUBLISHED",
            resource_id=base["version"]["id"],
        )
        # PRD §3.2 / §2.9: "three SyncEvent rows ... one each to BILLING,
        # GIS, and IM."
        targets = sorted({r["target_system"] for r in published_sync})
        assert set(targets) >= {"BILLING", "GIS", "IM"}, \
            f"Expected BILLING/GIS/IM sync events on publish, got {targets}"


class TestSyncSequenceMonotonic:
    """PRD §2.9 sequence_no monotonicity per (network_id, target_system)."""

    def test_billing_sequence_no_strictly_increases(self, api):
        """PRD §2.9: "a sequence_no that is monotonic within a given
        (network_id, target_system) pair to support deterministic replay
        ordering."
        """
        # Build two published topology versions — each emits one BILLING
        # SyncEvent.
        from test_helpers import setup_two_published_versions
        env = setup_two_published_versions(api)
        sync_rows = _list_sync_events(api, env["network"]["id"])
        # Filter BILLING-targeted events.
        billing = [r for r in sync_rows
                   if r.get("target_system") == "BILLING"]
        assert len(billing) >= 2, \
            f"Expected at least 2 BILLING sync events from two publishes, got {len(billing)}"
        assert_sequence_monotonic(sync_rows, "BILLING")


class TestWorkOrderVerifiedAudit:
    """PRD §2.9 + §3.8 verify side-effects."""

    def test_verify_pass_emits_work_order_closed_sync_pair(self, api):
        """PRD §3.8: "a pair of SyncEvent rows with
        event_type=WORK_ORDER_CLOSED are emitted to BILLING and IM."
        PRD §2.9: "Verifying and closing a work order emits two sync
        events — one to BILLING and one to IM."
        """
        env = setup_work_order_awaiting_verification(api)
        validate_success(
            api.verify_work_order(
                env["network"]["id"], env["work_order"]["id"],
                verify_work_order_payload("PASS"), SUP_ALT,
            )
        )
        sync_rows = _list_sync_events(api, env["network"]["id"])
        closed = find_sync_event_rows(
            sync_rows,
            event_type="WORK_ORDER_CLOSED",
            resource_id=env["work_order"]["id"],
        )
        targets = sorted({r["target_system"] for r in closed})
        assert set(targets) >= {"BILLING", "IM"}, \
            f"Expected BILLING & IM WORK_ORDER_CLOSED sync events, got {targets}"

    def test_verify_pass_writes_work_order_verified_audit(self, api):
        """PRD §2.9: "AuditLog rows are written for nine governed action
        values: ... WORK_ORDER_VERIFIED."
        PRD §3.8: "an AuditLog row is written with
        action=WORK_ORDER_VERIFIED."
        """
        env = setup_work_order_awaiting_verification(api)
        validate_success(
            api.verify_work_order(
                env["network"]["id"], env["work_order"]["id"],
                verify_work_order_payload("PASS"), SUP_ALT,
            )
        )
        rows = _list_audit_logs(api, env["network"]["id"])
        matched = find_audit_log_rows(rows, "WORK_ORDER_VERIFIED",
                                       resource_id=env["work_order"]["id"])
        assert len(matched) >= 1


class TestWaterBalancePublishedSync:
    """PRD §2.9: water-balance publication emits one SyncEvent to BILLING."""

    def test_water_balance_publish_emits_billing_sync_event(self, api):
        """PRD §3.9: "a SyncEvent row with
        event_type=WATER_BALANCE_PUBLISHED is emitted to BILLING."
        PRD §2.9: "Publishing a water-balance report emits one sync
        event — to BILLING."
        """
        env = setup_dma_with_inlet_flow_and_meter(api)
        payload = water_balance_report_payload(env["window_start"],
                                               env["window_end"])
        report = validate_success(
            api.create_water_balance_report(
                env["network"]["id"], env["dma"]["id"], payload, CO,
            ),
            expected_status=201,
        )
        sync_rows = _list_sync_events(api, env["network"]["id"])
        wb_events = find_sync_event_rows(
            sync_rows,
            event_type="WATER_BALANCE_PUBLISHED",
            resource_id=report["id"],
        )
        targets = sorted({r["target_system"] for r in wb_events})
        assert "BILLING" in targets, \
            f"Expected BILLING WATER_BALANCE_PUBLISHED sync event, got {targets}"
