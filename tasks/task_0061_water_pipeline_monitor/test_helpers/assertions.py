"""Entity assertions and domain invariant checkers.

Each helper checks PRD-required field presence, type, and enum range for a
single entity. Domain invariant helpers (e.g.,
assert_dma_open_critical_count_invariant) cross-check derived fields per
PRD §2.8, §3.5, and §3.9.

All field names are PRD-exact. Per PRD §2.4 timestamps are ISO 8601 UTC
with three fractional digits.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Enum allow-lists (cross-referenced in tests, exported for parametrize use)
# ---------------------------------------------------------------------------
TOPOLOGY_VERSION_STATES = [
    "DRAFT", "UNDER_REVIEW", "PUBLISHED", "SUPERSEDED", "REJECTED",
]
DMA_STATES = ["OPEN", "RESTRICTED", "FROZEN"]
DEVICE_STATES = ["PROVISIONED", "ACTIVE", "OFFLINE", "DECOMMISSIONED"]
ALERT_STATES = [
    "OPEN", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "SUPPRESSED",
]
ALERT_SEVERITIES = ["INFO", "WARNING", "CRITICAL"]
ALERT_KINDS = [
    "PRESSURE_HIGH", "PRESSURE_LOW", "FLOW_SPIKE",
    "FLOW_NIGHT_HIGH", "CROSS_SENSOR_DISAGREEMENT",
]
INVESTIGATION_STATES = [
    "OPEN", "NARROWED", "DISPATCHED", "CONFIRMED_LEAK", "FALSE_POSITIVE",
]
WORK_ORDER_STATES = [
    "NEW", "ASSIGNED", "PARTS_PENDING", "IN_PROGRESS",
    "AWAITING_VERIFICATION", "CLOSED_VERIFIED", "CLOSED_REJECTED",
    "CANCELLED",
]
WORK_ORDER_PRIORITIES = ["P1", "P2", "P3"]
WORK_ORDER_ORIGINS = ["ALERT_AUTO", "INVESTIGATION", "INSPECTION_FINDING"]
NODE_KINDS = [
    "JUNCTION", "VALVE", "PUMP_STATION", "RESERVOIR", "CUSTOMER_TAP",
]
SEGMENT_MATERIALS = ["PVC", "DUCTILE_IRON", "STEEL", "HDPE"]
DEVICE_PROTOCOLS = ["NB_IOT", "LORA", "WIRED"]
SENSOR_KINDS = ["PRESSURE", "FLOW", "METER"]
READING_VALIDITIES = [
    "ACCEPTED", "ABNORMAL_OUT_OF_RANGE",
    "ABNORMAL_STALE", "ABNORMAL_DUPLICATE",
]
ARCHIVE_TIERS = ["HOT", "WARM", "COLD"]
LEAK_CLASSES = [
    "LEAK_CONFIRMED", "JOINT_FAILURE", "PIPE_BURST", "NO_LEAK_FOUND",
]
AUDIT_ACTIONS = [
    "TOPOLOGY_SUBMITTED", "TOPOLOGY_PUBLISHED", "TOPOLOGY_REJECTED",
    "TOPOLOGY_ROLLED_BACK", "ALERT_ACK", "ALERT_SUPPRESSED",
    "ALERT_RESOLVED", "DMA_POSTURE_CHANGED", "WORK_ORDER_VERIFIED",
]
SYNC_EVENT_TYPES = [
    "TOPOLOGY_PUBLISHED", "ALERT_OPENED", "ALERT_RESOLVED",
    "WORK_ORDER_CLOSED", "WATER_BALANCE_PUBLISHED",
]
SYNC_TARGET_SYSTEMS = ["BILLING", "GIS", "IM"]


# ---------------------------------------------------------------------------
# Shared common-field assertions
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: 'server-minted id rendered as a UUID with no type prefix,
    a created_at timestamp, an updated_at timestamp that refreshes on
    every mutation, and a monotonically increasing integer version'."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{entity}.id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"{entity}.version must be integer, got {type(data.get('version'))}"
    assert data["version"] >= 1, \
        f"{entity}.version must be >= 1, got {data['version']}"


def _assert_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: 'Four entities are append-only and therefore carry only id
    and created_at — both updated_at and version are absent on
    PipelineNode, PipelineSegment, Reading, WaterBalanceReport, SyncEvent,
    and AuditLog.'"""
    assert is_valid_uuid(data.get("id", "")), \
        f"{entity}.id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601: {data.get('created_at')!r}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_network(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Network")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("utility_code"), str) and data["utility_code"]
    # active_topology_version_id may be null prior to first publish.
    atv = data.get("active_topology_version_id")
    assert atv is None or is_valid_uuid(atv), \
        f"Network.active_topology_version_id must be UUID or null"
    # clock_epoch_ms is integer milliseconds.
    assert isinstance(data.get("clock_epoch_ms"), int), \
        f"Network.clock_epoch_ms must be integer, got " \
        f"{type(data.get('clock_epoch_ms'))}"
    assert data["clock_epoch_ms"] >= 0


def assert_topology_version(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "TopologyVersion")
    assert data.get("status") in TOPOLOGY_VERSION_STATES, \
        f"TopologyVersion.status must be one of {TOPOLOGY_VERSION_STATES}, " \
        f"got {data.get('status')!r}"
    assert isinstance(data.get("version_number"), int), \
        "TopologyVersion.version_number must be integer"
    assert data["version_number"] >= 1
    # change_summary is required input.
    assert isinstance(data.get("change_summary"), str)


def assert_dma(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "DMA")
    assert data.get("status") in DMA_STATES, \
        f"DMA.status must be one of {DMA_STATES}, got {data.get('status')!r}"
    assert isinstance(data.get("dma_code"), str) and data["dma_code"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("open_critical_alert_count"), int)
    assert data["open_critical_alert_count"] >= 0


def assert_device(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Device")
    assert data.get("status") in DEVICE_STATES, \
        f"Device.status must be one of {DEVICE_STATES}, got {data.get('status')!r}"
    assert data.get("protocol") in DEVICE_PROTOCOLS
    assert data.get("sensor_kind") in SENSOR_KINDS
    assert isinstance(data.get("polling_interval_s"), int)
    assert 30 <= data["polling_interval_s"] <= 3600, \
        f"Device.polling_interval_s must be in [30, 3600], got " \
        f"{data['polling_interval_s']}"
    assert isinstance(data.get("valid_range_min"), (int, float))
    assert isinstance(data.get("valid_range_max"), (int, float))
    assert data["valid_range_min"] < data["valid_range_max"]


def assert_alert(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Alert")
    assert data.get("alert_kind") in ALERT_KINDS, \
        f"Alert.alert_kind must be one of {ALERT_KINDS}, " \
        f"got {data.get('alert_kind')!r}"
    assert data.get("severity") in ALERT_SEVERITIES, \
        f"Alert.severity must be one of {ALERT_SEVERITIES}, " \
        f"got {data.get('severity')!r}"
    assert data.get("status") in ALERT_STATES, \
        f"Alert.status must be one of {ALERT_STATES}, got {data.get('status')!r}"
    assert isinstance(data.get("occurrence_count"), int)
    assert data["occurrence_count"] >= 1


def assert_leak_investigation(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "LeakInvestigation")
    assert data.get("status") in INVESTIGATION_STATES, \
        f"LeakInvestigation.status must be one of {INVESTIGATION_STATES}, " \
        f"got {data.get('status')!r}"
    assert is_valid_uuid(data.get("alert_id", "")), \
        "LeakInvestigation.alert_id must be UUID"


def assert_work_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "WorkOrder")
    assert data.get("status") in WORK_ORDER_STATES, \
        f"WorkOrder.status must be one of {WORK_ORDER_STATES}, " \
        f"got {data.get('status')!r}"
    assert data.get("priority") in WORK_ORDER_PRIORITIES, \
        f"WorkOrder.priority must be one of {WORK_ORDER_PRIORITIES}, " \
        f"got {data.get('priority')!r}"
    assert data.get("origin") in WORK_ORDER_ORIGINS
    assert isinstance(data.get("verification_failure_count"), int)
    assert data["verification_failure_count"] >= 0


def assert_pipeline_node(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "PipelineNode")
    assert data.get("kind") in NODE_KINDS, \
        f"PipelineNode.kind must be one of {NODE_KINDS}, " \
        f"got {data.get('kind')!r}"
    assert isinstance(data.get("node_code"), str)


def assert_pipeline_segment(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "PipelineSegment")
    assert data.get("material") in SEGMENT_MATERIALS
    assert isinstance(data.get("segment_code"), str)
    assert isinstance(data.get("length_m"), (int, float))
    assert data["length_m"] > 0
    assert isinstance(data.get("diameter_mm"), int)
    assert data["diameter_mm"] > 0


def assert_reading(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "Reading")
    assert data.get("validity") in READING_VALIDITIES
    assert data.get("archive_tier") in ARCHIVE_TIERS


def assert_water_balance_report(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "WaterBalanceReport")
    # All m^3 fields exist on a finalized report.
    for fld in (
        "input_volume_m3", "billed_consumption_m3",
        "unbilled_authorized_m3", "apparent_loss_m3", "real_loss_m3",
    ):
        assert isinstance(data.get(fld), (int, float)), \
            f"WaterBalanceReport.{fld} must be numeric"
        assert data[fld] >= 0, \
            f"WaterBalanceReport.{fld} must be >= 0"
    assert isinstance(data.get("nrw_pct"), (int, float))


def assert_sync_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "SyncEvent")
    assert data.get("target_system") in SYNC_TARGET_SYSTEMS
    assert data.get("event_type") in SYNC_EVENT_TYPES
    assert isinstance(data.get("resource_kind"), str)
    assert isinstance(data.get("resource_id"), str)
    assert isinstance(data.get("sequence_no"), int)


def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "AuditLog")
    assert data.get("action") in AUDIT_ACTIONS, \
        f"AuditLog.action must be one of {AUDIT_ACTIONS}, " \
        f"got {data.get('action')!r}"
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("resource_kind"), str)
    assert isinstance(data.get("resource_id"), str)


# ---------------------------------------------------------------------------
# Domain-specific cross-field invariants
# ---------------------------------------------------------------------------
def assert_dma_posture_matches_count(dma: Dict[str, Any]) -> None:
    """PRD §2.8: posture is driven by open_critical_alert_count.

    'When open_critical_alert_count crosses from zero to one or more, the
    DMA transitions from OPEN to RESTRICTED; when it reaches three or more,
    the DMA transitions from RESTRICTED to FROZEN; when it drops below
    three the DMA transitions back from FROZEN to RESTRICTED; and when it
    falls to zero the DMA transitions back from RESTRICTED to OPEN.'
    """
    count = dma["open_critical_alert_count"]
    status = dma["status"]
    if count == 0:
        assert status == "OPEN", \
            f"DMA.open_critical_alert_count={count} but status={status!r}; " \
            f"PRD §2.8 requires OPEN when count drops to zero"
    elif count >= 3:
        assert status == "FROZEN", \
            f"DMA.open_critical_alert_count={count} but status={status!r}; " \
            f"PRD §2.8 requires FROZEN when count reaches three or more"
    else:  # 1 or 2
        assert status == "RESTRICTED", \
            f"DMA.open_critical_alert_count={count} but status={status!r}; " \
            f"PRD §2.8 requires RESTRICTED in [1,3)"


def assert_water_balance_invariants(report: Dict[str, Any]) -> None:
    """PRD §3.9 — real_loss is floored at zero; nrw_pct uses input.

    'real_loss_m3 is the physical leakage, computed as input_volume_m3
    minus billed_consumption_m3 minus unbilled_authorized_m3 minus
    apparent_loss_m3, with a floor of 0.'
    """
    assert report["real_loss_m3"] >= 0
    # input must be > 0; PRD §3.9: zero input rejects with
    # ERR_INSUFFICIENT_DATA, so a returned report always has positive
    # input.
    assert report["input_volume_m3"] > 0


def find_audit_log_rows(rows: List[Dict[str, Any]], action: str,
                        resource_id: Optional[str] = None
                        ) -> List[Dict[str, Any]]:
    """Filter audit-log rows by action (and optionally resource_id)."""
    out: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("action") != action:
            continue
        if resource_id is not None and row.get("resource_id") != resource_id:
            continue
        out.append(row)
    return out


def find_sync_event_rows(rows: List[Dict[str, Any]],
                         event_type: Optional[str] = None,
                         target_system: Optional[str] = None,
                         resource_id: Optional[str] = None
                         ) -> List[Dict[str, Any]]:
    """Filter sync-event rows by event_type / target_system / resource_id."""
    out: List[Dict[str, Any]] = []
    for row in rows:
        if event_type is not None and row.get("event_type") != event_type:
            continue
        if (target_system is not None
                and row.get("target_system") != target_system):
            continue
        if resource_id is not None and row.get("resource_id") != resource_id:
            continue
        out.append(row)
    return out


def assert_sequence_monotonic(rows: List[Dict[str, Any]],
                              target_system: str) -> None:
    """PRD §2.9: 'a sequence_no that is monotonic within a given
    (network_id, target_system) pair to support deterministic replay
    ordering.'"""
    seqs = [r["sequence_no"] for r in rows
            if r.get("target_system") == target_system]
    for i in range(1, len(seqs)):
        assert seqs[i] > seqs[i - 1], \
            f"sequence_no not monotonic for {target_system}: {seqs}"


__all__ = [
    "TOPOLOGY_VERSION_STATES", "DMA_STATES", "DEVICE_STATES",
    "ALERT_STATES", "ALERT_SEVERITIES", "ALERT_KINDS",
    "INVESTIGATION_STATES", "WORK_ORDER_STATES", "WORK_ORDER_PRIORITIES",
    "WORK_ORDER_ORIGINS", "NODE_KINDS", "SEGMENT_MATERIALS",
    "DEVICE_PROTOCOLS", "SENSOR_KINDS", "READING_VALIDITIES",
    "ARCHIVE_TIERS", "LEAK_CLASSES", "AUDIT_ACTIONS",
    "SYNC_EVENT_TYPES", "SYNC_TARGET_SYSTEMS",
    "assert_network", "assert_topology_version", "assert_dma",
    "assert_device", "assert_alert", "assert_leak_investigation",
    "assert_work_order", "assert_pipeline_node", "assert_pipeline_segment",
    "assert_reading", "assert_water_balance_report",
    "assert_sync_event", "assert_audit_log",
    "assert_dma_posture_matches_count", "assert_water_balance_invariants",
    "find_audit_log_rows", "find_sync_event_rows",
    "assert_sequence_monotonic",
]
