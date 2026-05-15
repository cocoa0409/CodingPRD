"""Entity assertions and domain invariant checkers.

Per PRD §2.4: Warehouse, Zone, Bin, Supplier, Product, InboundReceipt,
Lot, OutboundShipment, Deviation, CAPA, Recall carry
id/created_at/updated_at/version. Four append-only entities carry only
id and created_at: TemperatureEvent, RecallScopeEntry,
ExternalSyncEvent, AuditLogEntry. The append-only assertions MUST NOT
demand updated_at or version.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Lookup helpers (used by tests that fish a specific row out of a list).
# ---------------------------------------------------------------------------
def find_row(rows: List[Dict[str, Any]], **predicates: Any) -> Dict[str, Any]:
    """Return the first row whose fields match every predicate kwarg."""
    for row in rows:
        if all(row.get(k) == v for k, v in predicates.items()):
            return row
    raise AssertionError(
        f"No row matching {predicates}. Saw: "
        f"{[dict((k, r.get(k)) for k in predicates) for r in rows]}"
    )


def select_rows(rows: List[Dict[str, Any]],
                **predicates: Any) -> List[Dict[str, Any]]:
    return [
        r for r in rows
        if all(r.get(k) == v for k, v in predicates.items())
    ]


def count_rows(rows: List[Dict[str, Any]], **predicates: Any) -> int:
    return len(select_rows(rows, **predicates))


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any]) -> None:
    """For entities that carry id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, \
        f"version must be a positive integer, got {version!r}"


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """For append-only entities — id and created_at only.

    Per PRD §2.4, TemperatureEvent, RecallScopeEntry, ExternalSyncEvent,
    and AuditLogEntry MUST NOT expose updated_at or version.
    """
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ---------------------------------------------------------------------------
# Warehouse — PRD §3.1
# ---------------------------------------------------------------------------
_WAREHOUSE_STATUSES = {"ACTIVE", "SUSPENDED"}


def assert_warehouse(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["gsp_license_no"], str)
    assert isinstance(data["clock_minutes"], int)
    assert data["clock_minutes"] >= 0
    assert data["status"] in _WAREHOUSE_STATUSES


# ---------------------------------------------------------------------------
# Zone — PRD §3.1, §2.10
# ---------------------------------------------------------------------------
_ZONE_TYPES = {
    "FROZEN", "REFRIGERATED", "COOL", "ROOM_TEMP",
    "CONTROLLED_TEMP", "QUARANTINE",
}
_ZONE_POSTURES = {"OPEN", "RESTRICTED", "FROZEN"}


def assert_zone(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["zone_type"] in _ZONE_TYPES
    for k in ("target_temp_low_c", "target_temp_high_c",
              "alarm_low_c", "alarm_high_c"):
        assert isinstance(data[k], (int, float))
    assert data["current_posture"] in _ZONE_POSTURES
    assert isinstance(data["capacity_units"], int)
    assert data["capacity_units"] >= 0
    assert isinstance(data["utilization_units"], int)
    assert data["utilization_units"] >= 0


# ---------------------------------------------------------------------------
# Bin — PRD §3.1
# ---------------------------------------------------------------------------
_BIN_STATUSES = {"AVAILABLE", "OCCUPIED", "LOCKED"}
_SPECIAL_TAGS = {
    "NONE", "NARCOTIC", "PSYCHOTROPIC", "BIOLOGICAL", "VACCINE",
}


def assert_bin(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["volume_units"], int)
    assert data["volume_units"] >= 0
    assert isinstance(data["weight_limit_kg"], (int, float))
    assert data["special_storage_tag"] in _SPECIAL_TAGS
    assert data["status"] in _BIN_STATUSES
    assert isinstance(data["occupied_volume"], int)
    assert data["occupied_volume"] >= 0
    assert isinstance(data["occupied_weight_kg"], (int, float))
    assert data["occupied_weight_kg"] >= 0


# ---------------------------------------------------------------------------
# Supplier — PRD §3.1
# ---------------------------------------------------------------------------
def assert_supplier(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["qualified"], bool)
    assert isinstance(data["qualification_expiry_minutes"], int)


# ---------------------------------------------------------------------------
# Product — PRD §3.1
# ---------------------------------------------------------------------------
_PRODUCT_ZONE_TYPES = {
    "FROZEN", "REFRIGERATED", "COOL", "ROOM_TEMP", "CONTROLLED_TEMP",
}


def assert_product(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["sku"], str)
    assert isinstance(data["name"], str)
    assert data["required_zone_type"] in _PRODUCT_ZONE_TYPES
    assert data["special_storage_tag"] in _SPECIAL_TAGS
    assert isinstance(data["qualified"], bool)
    assert isinstance(data["unit_weight_kg"], (int, float))
    assert isinstance(data["stability_budget_minutes"], int)


# ---------------------------------------------------------------------------
# InboundReceipt — PRD §3.2
# ---------------------------------------------------------------------------
_RECEIPT_STATUSES = {
    "PENDING_INSPECTION", "INSPECTED", "QUARANTINED",
    "ACCEPTED", "REJECTED",
}
_NONCONFORMANCE_REASONS = {
    "NONE", "UNQUALIFIED_SUPPLIER", "UNQUALIFIED_PRODUCT",
    "VISUAL_FAIL", "TEMP_EXCURSION", "EXPIRED_ON_ARRIVAL",
}


def assert_receipt(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["warehouse_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["lot_number"], str)
    assert isinstance(data["expiry_minutes"], int)
    assert isinstance(data["quantity_units"], int)
    assert data["quantity_units"] > 0
    assert isinstance(data["carrier_logger_readings"], list)
    assert isinstance(data["visual_pass"], bool)
    assert data["status"] in _RECEIPT_STATUSES
    # nonconformance_reason may be null in PENDING_INSPECTION; once
    # computed it lies in the allowed set.
    nc = data.get("nonconformance_reason")
    if nc is not None:
        assert nc in _NONCONFORMANCE_REASONS


# ---------------------------------------------------------------------------
# Lot — PRD §3.2
# ---------------------------------------------------------------------------
_LOT_QUALITY_STATUSES = {
    "RELEASED", "QUARANTINED", "REJECTED", "RECALLED",
}


def assert_lot(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["warehouse_id"])
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert isinstance(data["lot_number"], str)
    assert isinstance(data["expiry_minutes"], int)
    assert is_valid_uuid(data["receipt_id"])
    assert isinstance(data["quantity_on_hand"], int)
    assert data["quantity_on_hand"] >= 0
    assert isinstance(data["quantity_picked"], int)
    assert data["quantity_picked"] >= 0
    assert isinstance(data["cumulative_excursion_minutes"], int)
    assert data["cumulative_excursion_minutes"] >= 0
    assert data["quality_status"] in _LOT_QUALITY_STATUSES


# ---------------------------------------------------------------------------
# OutboundShipment — PRD §3.5
# ---------------------------------------------------------------------------
_SHIPMENT_STATUSES = {
    "PLANNED", "PICKED", "PACKED", "DISPATCHED",
    "QUARANTINED", "CANCELLED",
}
_PACKAGING_KINDS = {"INSULATED_PCM", "INSULATED_DRY_ICE", "AMBIENT"}


def assert_shipment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["customer_id"], str)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["quantity_units"], int)
    assert data["packaging_kind"] in _PACKAGING_KINDS
    assert isinstance(data["pick_temp_c"], (int, float))
    assert isinstance(data["vehicle_precondition_temp_c"], (int, float))
    assert isinstance(data["logger_armed"], bool)
    assert data["status"] in _SHIPMENT_STATUSES


# ---------------------------------------------------------------------------
# TemperatureEvent — PRD §3.3 (append-only)
# ---------------------------------------------------------------------------
_TEMP_EVENT_KINDS = {
    "IN_RANGE", "WARNING_LOW", "WARNING_HIGH", "ALARM_LOW", "ALARM_HIGH",
}


def assert_temperature_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    # Append-only — MUST NOT expose updated_at or version.
    assert "updated_at" not in data, (
        "TemperatureEvent must not expose updated_at "
        "(append-only per PRD §2.4)"
    )
    assert "version" not in data, (
        "TemperatureEvent must not expose version "
        "(append-only per PRD §2.4)"
    )
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["at_minutes"], int)
    assert isinstance(data["temp_c"], (int, float))
    assert data["kind"] in _TEMP_EVENT_KINDS


# ---------------------------------------------------------------------------
# Deviation — PRD §3.3
# ---------------------------------------------------------------------------
_DEVIATION_STATUSES = {"OPEN", "CLOSED_PENDING_QA", "CLOSED_ASSESSED"}
_DEVIATION_CLASSIFICATIONS = {"MINOR", "MAJOR", "CRITICAL"}
_QA_DECISIONS = {"PENDING", "RELEASE", "QUARANTINE", "REJECT"}


def assert_deviation(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["started_at_minutes"], int)
    assert data["status"] in _DEVIATION_STATUSES
    if data.get("classification") is not None:
        assert data["classification"] in _DEVIATION_CLASSIFICATIONS
    assert data["qa_decision"] in _QA_DECISIONS


# ---------------------------------------------------------------------------
# CAPA — PRD §3.3
# ---------------------------------------------------------------------------
_CAPA_STATUSES = {"OPEN", "IN_PROGRESS", "COMPLETED", "OVERDUE"}


def assert_capa(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["due_minutes"], int)
    assert data["status"] in _CAPA_STATUSES
    # Per PRD §3.3: exactly one of deviation_id / recall_id is populated.
    dev = data.get("deviation_id")
    rec = data.get("recall_id")
    assert (dev is None) ^ (rec is None), (
        "CAPA must have exactly one of deviation_id / recall_id populated "
        f"(got deviation_id={dev!r}, recall_id={rec!r})"
    )


# ---------------------------------------------------------------------------
# Recall — PRD §3.7
# ---------------------------------------------------------------------------
_RECALL_STATUSES = {
    "DRAFT", "ANNOUNCED", "RETURNS_IN_PROGRESS",
    "EFFECTIVENESS_CHECK", "CLOSED",
}
_RECALL_CLASSIFICATIONS = {"CLASS_I", "CLASS_II", "CLASS_III"}


def assert_recall(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["warehouse_id"])
    assert data["classification"] in _RECALL_CLASSIFICATIONS
    assert isinstance(data["reason"], str)
    assert isinstance(data["notifications_sent"], int)
    assert data["notifications_sent"] >= 0
    assert isinstance(data["returns_received_units"], int)
    assert data["returns_received_units"] >= 0
    assert data["status"] in _RECALL_STATUSES


# ---------------------------------------------------------------------------
# RecallScopeEntry — PRD §3.7 (append-only)
# ---------------------------------------------------------------------------
_RECALL_SCOPE_KINDS = {"ON_HAND", "SHIPPED"}


def assert_recall_scope_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, (
        "RecallScopeEntry must not expose updated_at "
        "(append-only per PRD §2.4)"
    )
    assert "version" not in data, (
        "RecallScopeEntry must not expose version "
        "(append-only per PRD §2.4)"
    )
    assert is_valid_uuid(data["recall_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["units"], int)
    assert data["units"] > 0
    assert data["scope_kind"] in _RECALL_SCOPE_KINDS


# ---------------------------------------------------------------------------
# ExternalSyncEvent — PRD §3.8 (append-only)
# ---------------------------------------------------------------------------
_EXTERNAL_TARGETS = {
    "REGULATORY_AUTHORITY", "GSP_REPORT", "PHARMACOVIGILANCE", "TMS",
}
_EXTERNAL_EVENT_TYPES = {
    "INBOUND_ACCEPTED", "INBOUND_QUARANTINED",
    "DEVIATION_OPENED", "DEVIATION_CLOSED",
    "RECALL_ANNOUNCED", "RECALL_CLOSED",
    "SHIPMENT_DISPATCHED", "CAPA_OVERDUE",
}


def assert_external_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, (
        "ExternalSyncEvent must not expose updated_at "
        "(append-only per PRD §2.4)"
    )
    assert "version" not in data, (
        "ExternalSyncEvent must not expose version "
        "(append-only per PRD §2.4)"
    )
    assert is_valid_uuid(data["warehouse_id"])
    assert data["target_system"] in _EXTERNAL_TARGETS
    assert data["event_type"] in _EXTERNAL_EVENT_TYPES


# ---------------------------------------------------------------------------
# AuditLogEntry — PRD §3.8 (append-only)
# ---------------------------------------------------------------------------
def assert_audit_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, (
        "AuditLogEntry must not expose updated_at "
        "(append-only per PRD §2.4)"
    )
    assert "version" not in data, (
        "AuditLogEntry must not expose version "
        "(append-only per PRD §2.4)"
    )
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["action"], str)
    assert isinstance(data["target_id"], str)
    assert isinstance(data["at_minutes"], int)


# ---------------------------------------------------------------------------
# Domain invariants — PRD §3.5, §2.8
# ---------------------------------------------------------------------------
def assert_lot_unit_conservation(lot: Dict[str, Any],
                                 initial_quantity: int) -> None:
    """PRD §3.5: lot.quantity_on_hand + lot.quantity_picked equals the
    originating receipt.quantity_units at all times.
    """
    total = lot["quantity_on_hand"] + lot["quantity_picked"]
    assert total == initial_quantity, (
        f"Lot unit conservation broken: on_hand={lot['quantity_on_hand']} + "
        f"picked={lot['quantity_picked']} = {total}, "
        f"expected {initial_quantity}"
    )


def assert_zone_utilization_invariant(zone: Dict[str, Any],
                                      child_bins: Iterable[Dict[str, Any]]
                                      ) -> None:
    """PRD §2.8: Zone.utilization_units is always exactly the sum of
    occupied_volume across its child bins. No drift permitted.
    """
    expected = sum(b["occupied_volume"] for b in child_bins)
    assert zone["utilization_units"] == expected, (
        f"Zone utilization drift: utilization_units="
        f"{zone['utilization_units']}, sum of child bins.occupied_volume="
        f"{expected}"
    )


def assert_certificate_format(cert_no: str, warehouse_code: str) -> None:
    """PRD §3.2: acceptance_certificate_no format is
    CERT-{warehouse.code}-{seq:06d} where seq is a six-digit zero-padded
    monotonic per-warehouse counter.
    """
    assert isinstance(cert_no, str), \
        f"acceptance_certificate_no must be string, got {type(cert_no)}"
    expected_prefix = f"CERT-{warehouse_code}-"
    assert cert_no.startswith(expected_prefix), (
        f"acceptance_certificate_no must begin with 'CERT-"
        f"{warehouse_code}-', got {cert_no!r}"
    )
    suffix = cert_no[len(expected_prefix):]
    assert len(suffix) == 6 and suffix.isdigit(), (
        f"acceptance_certificate_no suffix must be 6 digits, got "
        f"{suffix!r}"
    )


__all__ = [
    "find_row",
    "select_rows",
    "count_rows",
    "assert_warehouse",
    "assert_zone",
    "assert_bin",
    "assert_supplier",
    "assert_product",
    "assert_receipt",
    "assert_lot",
    "assert_shipment",
    "assert_temperature_event",
    "assert_deviation",
    "assert_capa",
    "assert_recall",
    "assert_recall_scope_entry",
    "assert_external_event",
    "assert_audit_entry",
    "assert_lot_unit_conservation",
    "assert_zone_utilization_invariant",
    "assert_certificate_format",
]
