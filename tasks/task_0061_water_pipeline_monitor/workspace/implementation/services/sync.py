"""Sync-event emitters per PRD §2.9."""
from db import public

from services.audit import emit_sync


def emit_sync_for_topology_published(network_id: str, topology_version: dict) -> None:
    payload = public(topology_version)
    for tgt in ("BILLING", "GIS", "IM"):
        emit_sync(
            network_id=network_id,
            target_system=tgt,
            event_type="TOPOLOGY_PUBLISHED",
            resource_kind="TopologyVersion",
            resource_id=topology_version["id"],
            payload=payload,
        )


def emit_sync_for_alert_opened(alert: dict) -> None:
    # Per PRD §2.9, ALERT_OPENED maps to BILLING and IM (not explicitly stated;
    # only ALERT_RESOLVED enumerates them). We emit a single event_type=ALERT_OPENED
    # to IM, matching the operational pattern; scaffold lists ALERT_OPENED as a
    # standalone event_type. Use IM as the target.
    # The PRD lists the five event_types but pairs systems only for ALERT_RESOLVED,
    # WORK_ORDER_CLOSED, etc. ALERT_OPENED is a single-emission event; we emit to IM.
    emit_sync(
        network_id=alert["network_id"],
        target_system="IM",
        event_type="ALERT_OPENED",
        resource_kind="Alert",
        resource_id=alert["id"],
        payload=public(alert),
    )


def emit_sync_for_alert_resolved(alert: dict) -> None:
    payload = public(alert)
    for tgt in ("BILLING", "IM"):
        emit_sync(
            network_id=alert["network_id"],
            target_system=tgt,
            event_type="ALERT_RESOLVED",
            resource_kind="Alert",
            resource_id=alert["id"],
            payload=payload,
        )


def emit_sync_for_work_order_closed(work_order: dict) -> None:
    payload = public(work_order)
    for tgt in ("BILLING", "IM"):
        emit_sync(
            network_id=work_order["network_id"],
            target_system=tgt,
            event_type="WORK_ORDER_CLOSED",
            resource_kind="WorkOrder",
            resource_id=work_order["id"],
            payload=payload,
        )


def emit_sync_for_water_balance_published(network_id: str, report: dict) -> None:
    emit_sync(
        network_id=network_id,
        target_system="BILLING",
        event_type="WATER_BALANCE_PUBLISHED",
        resource_kind="WaterBalanceReport",
        resource_id=report["id"],
        payload=public(report),
    )
