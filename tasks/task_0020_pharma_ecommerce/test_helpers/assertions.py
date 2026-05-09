"""Entity assertions and domain invariant checkers (PRD-exact field names)."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .constants import (
    COLD_CHAIN_DISPOSE_THRESHOLD,
    MAX_REVISIONS,
)

# Allowed enum values for PRD-exact assertions.
_DRUG_STATUSES = {"PENDING_REVIEW", "ON_SHELF", "OFF_SHELF"}
_CLASSIFICATIONS = {"OTC", "PRESCRIPTION"}
_CONTROL_CATEGORIES = {"NONE", "NARCOTIC", "PSYCHOTROPIC_I", "PSYCHOTROPIC_II", "TOXIC"}
_VENDOR_STATUSES = {"ACTIVE", "REVIEW_REQUIRED", "SUSPENDED"}
_PHARMACIST_STATUSES = {"ACTIVE", "EXPIRED", "SUSPENDED"}
_PRESCRIPTION_STATUSES = {"UPLOADED", "REVIEW_PENDING", "APPROVED", "REJECTED", "REVOKED", "ARCHIVED"}
_PAYMENT_STATUSES = {"UNPAID", "PAID", "REFUNDED"}
_DISPENSING_STATUSES = {
    "PENDING_REVIEW", "PHARMACIST_REVIEWING", "APPROVED", "REJECTED",
    "DISPENSED", "SHIPPED", "DELIVERED", "CANCELLED",
}
_REVIEW_STATUSES = {"PENDING", "IN_REVIEW", "APPROVED", "REJECTED", "REQUEST_CHANGE"}
_SHIPMENT_STATUSES = {"DISPATCHED", "IN_TRANSIT", "DELIVERED", "DISPOSED"}
_ADR_STATUSES = {"REPORTED", "SUBMITTED", "ACKNOWLEDGED", "FOLLOW_UP_PENDING", "ARCHIVED"}
_ADR_SEVERITIES = {"NON_SERIOUS", "SERIOUS"}
_REPORTER_KINDS = {"PATIENT", "PHARMACIST"}


def _assert_common_fields(data: Dict[str, Any], where: str) -> None:
    """PRD §2.4: id (UUID), created_at + updated_at (ISO 8601), version (int)."""
    assert is_valid_uuid(data.get("id", "")), f"{where}: id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{where}: created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{where}: updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"{where}: version must be an integer, got {type(data.get('version')).__name__}"
    assert data["version"] >= 0


def _assert_append_only_fields(data: Dict[str, Any], where: str) -> None:
    """PRD §2.4: append-only logs carry only id and created_at; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{where}: id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{where}: created_at must be ISO 8601"


# ---------------------------------------------------------------------------
# Per-entity assertions (PRD-exact field names)
# ---------------------------------------------------------------------------

def assert_platform(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "PharmaPlatform")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["jurisdiction"], str) and len(data["jurisdiction"]) > 0
    assert is_iso8601_timestamp(data["current_clock_iso"])
    assert isinstance(data["regulatory_endpoint"], str)


def assert_drug(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Drug")
    assert isinstance(data.get("ndc"), str) and len(data["ndc"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["classification"] in _CLASSIFICATIONS, f"classification {data['classification']!r}"
    assert data["control_category"] in _CONTROL_CATEGORIES
    assert isinstance(data["cold_chain_required"], bool)
    assert isinstance(data["indications"], list)
    assert isinstance(data["contraindications"], list)
    assert isinstance(data["per_order_qty_cap"], int) and data["per_order_qty_cap"] >= 1
    assert isinstance(data["per_period_qty_cap"], int)
    assert isinstance(data["vendor_id"], str) and len(data["vendor_id"]) > 0
    assert data["status"] in _DRUG_STATUSES
    # PRD §2.9: control_category != NONE → classification == PRESCRIPTION
    if data["control_category"] != "NONE":
        assert data["classification"] == "PRESCRIPTION", \
            f"control_category {data['control_category']!r} requires PRESCRIPTION"


def assert_vendor(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Vendor")
    assert isinstance(data["name"], str)
    assert isinstance(data["business_license_no"], str)
    assert is_iso8601_timestamp(data["business_license_expires_at"])
    assert isinstance(data["drug_operation_permit_no"], str)
    assert is_iso8601_timestamp(data["drug_operation_permit_expires_at"])
    assert data["qualification_status"] in _VENDOR_STATUSES


def assert_pharmacist(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Pharmacist")
    assert isinstance(data["full_name"], str)
    assert isinstance(data["certificate_no"], str)
    assert is_iso8601_timestamp(data["certificate_expires_at"])
    assert data["qualification_status"] in _PHARMACIST_STATUSES
    assert isinstance(data.get("courier_qualified", False), bool)


def assert_customer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Customer")
    assert isinstance(data["real_name"], str)
    assert isinstance(data["id_document_no"], str)
    assert isinstance(data["special_population_flags"], list)
    assert isinstance(data["real_name_verified"], bool)


def assert_prescription(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Prescription")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["prescriber_name"], str)
    assert isinstance(data["prescriber_license_no"], str)
    assert isinstance(data["image_url"], str)
    assert is_iso8601_timestamp(data["issued_at"])
    assert isinstance(data["validity_days"], int)
    assert isinstance(data["drug_items"], list) and len(data["drug_items"]) >= 1
    for it in data["drug_items"]:
        assert "drug_id" in it and isinstance(it["drug_id"], str)
        assert "qty" in it and isinstance(it["qty"], int) and it["qty"] >= 1
    assert data["status"] in _PRESCRIPTION_STATUSES


def assert_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Order")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["items"], list) and len(data["items"]) >= 1
    for it in data["items"]:
        assert isinstance(it["drug_id"], str)
        assert isinstance(it["qty"], int) and it["qty"] >= 1
        assert isinstance(it["unit_price_cents"], int) and it["unit_price_cents"] >= 0
    assert isinstance(data["total_amount_cents"], int)
    assert isinstance(data["cold_chain_required"], bool)
    assert data["payment_status"] in _PAYMENT_STATUSES
    assert data["dispensing_status"] in _DISPENSING_STATUSES


def assert_pharmacist_review(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "PharmacistReview")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["assigned_pharmacist_id"], str)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in _REVIEW_STATUSES


def assert_cold_chain_shipment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ColdChainShipment")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["courier_pharmacist_id"], str)
    assert isinstance(data["device_id"], str)
    assert is_iso8601_timestamp(data["dispatched_at"])
    assert isinstance(data["temperature_readings"], list)
    for r in data["temperature_readings"]:
        assert is_iso8601_timestamp(r["recorded_at"])
        assert isinstance(r["celsius_tenths"], int)
    assert isinstance(data["excursion_score"], int) and data["excursion_score"] >= 0
    assert data["status"] in _SHIPMENT_STATUSES


def assert_adr(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "AdverseReactionReport")
    assert isinstance(data["drug_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["reporter_kind"] in _REPORTER_KINDS
    assert data["severity"] in _ADR_SEVERITIES
    assert is_iso8601_timestamp(data["reported_at"])
    assert is_iso8601_timestamp(data["reporting_deadline_at"])
    assert data["status"] in _ADR_STATUSES


def assert_purchase_limit_rule(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "PurchaseLimitRule")
    assert data["control_category"] in _CONTROL_CATEGORIES
    assert isinstance(data["window_days"], int) and data["window_days"] >= 1
    assert isinstance(data["max_units_per_window"], int) and data["max_units_per_window"] >= 0
    assert isinstance(data["blocks_special_populations"], list)


# --- Append-only entities (PRD §2.4) ---

def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "AuditLog")
    # PRD §2.4: AuditLog has NO updated_at and NO version.
    assert "updated_at" not in data, "AuditLog must NOT carry updated_at (append-only)"
    assert "version" not in data, "AuditLog must NOT carry version (append-only)"
    assert isinstance(data["subject_type"], str)
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["action"], str)


def assert_external_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "ExternalEvent")
    assert "updated_at" not in data, "ExternalEvent must NOT carry updated_at (append-only)"
    assert "version" not in data, "ExternalEvent must NOT carry version (append-only)"
    assert isinstance(data["channel"], str)
    assert isinstance(data["event_type"], str)
    assert isinstance(data["idempotency_key"], str)


def assert_denylist_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "PrescriberDenylistEntry")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["prescriber_license_no"], str)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_order_total_correct(order: Dict[str, Any]) -> None:
    """PRD §2.12: total_amount_cents = sum(qty * unit_price_cents); integer cents."""
    expected = sum(it["qty"] * it["unit_price_cents"] for it in order["items"])
    assert order["total_amount_cents"] == expected, \
        f"total_amount_cents: expected {expected}, got {order['total_amount_cents']}"


def assert_excursion_score_le_threshold(shipment: Dict[str, Any]) -> None:
    """PRD §3.7: deliver requires excursion_score <= 30."""
    assert shipment["excursion_score"] <= COLD_CHAIN_DISPOSE_THRESHOLD


def assert_excursion_score_gt_threshold(shipment: Dict[str, Any]) -> None:
    """PRD §3.7: dispose requires excursion_score > 30 strictly."""
    assert shipment["excursion_score"] > COLD_CHAIN_DISPOSE_THRESHOLD


def assert_revision_count_within_cap(review: Dict[str, Any]) -> None:
    """PRD §3.6: revision_count must be strictly less than the maximum of 2."""
    assert review["revision_count"] <= MAX_REVISIONS, \
        f"revision_count {review['revision_count']} exceeds MAX_REVISIONS {MAX_REVISIONS}"


def find_audit_logs(audit_logs: List[Dict[str, Any]],
                     subject_id: Optional[str] = None,
                     subject_type: Optional[str] = None,
                     action: Optional[str] = None) -> List[Dict[str, Any]]:
    """Filter helper for audit log assertions."""
    out = audit_logs
    if subject_id is not None:
        out = [a for a in out if a.get("subject_id") == subject_id]
    if subject_type is not None:
        out = [a for a in out if a.get("subject_type") == subject_type]
    if action is not None:
        out = [a for a in out if a.get("action") == action]
    return out


def find_external_events(events: List[Dict[str, Any]],
                          channel: Optional[str] = None,
                          event_type: Optional[str] = None,
                          subject_id: Optional[str] = None) -> List[Dict[str, Any]]:
    out = events
    if channel is not None:
        out = [e for e in out if e.get("channel") == channel]
    if event_type is not None:
        out = [e for e in out if e.get("event_type") == event_type]
    if subject_id is not None:
        out = [e for e in out if e.get("subject_id") == subject_id]
    return out
