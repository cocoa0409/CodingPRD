"""Per-entity assertions for the Commercial Leasing API.

PRD §2.4 splits entities into two field-shapes:
- Versioned (id + created_at + updated_at + version):
  Building, Unit, Tenant, Lease, Deposit, FeeBill, MoveOutRequest.
- Append-only (id + created_at only; no updated_at, no version):
  RentScheduleItem, AuditEvent.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared shape checkers
# ---------------------------------------------------------------------------
def _check_versioned_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 versioned shape: id, created_at, updated_at, version."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" in data and is_iso8601_timestamp(
        data["updated_at"]
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert "version" in data, f"{entity} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 append-only shape: id + created_at ONLY."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"


# ---------------------------------------------------------------------------
# Constants / allowed enum sets
# ---------------------------------------------------------------------------
BUILDING_STATES = {"ACTIVE", "DECOMMISSIONED"}
UNIT_STATES = {"VACANT", "RESERVED", "LEASED", "UNDER_RENOVATION", "RETIRED"}
ORIENTATIONS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}
USAGE_TYPES = {"OFFICE", "RETAIL", "WAREHOUSE", "FB"}
TENANT_STATES = {"PENDING_REVIEW", "APPROVED", "REJECTED"}
LEASE_STATES = {
    "DRAFT", "SIGNED", "ACTIVE", "AMENDMENT_PENDING",
    "TERMINATING", "TERMINATED",
}
ESCALATION_MODES = {"NONE", "ANNUAL", "BIENNIAL", "STEPPED"}
RENT_ITEM_STATES = {"PENDING", "PAID", "WAIVED", "VOIDED"}
DEPOSIT_FROZEN_STATES = {"UNFROZEN", "FROZEN"}
DEPOSIT_ADJUSTMENT_STATES = {
    "AT_REST", "ADJUSTMENT_PENDING",
    "DEDUCTION_PENDING_APPROVAL", "SETTLED",
}
DEDUCTION_KINDS = {"OVERDUE_RENT", "DAMAGE", "CLEANING"}
FEE_BILL_KINDS = {"PROPERTY_FEE", "ENERGY_FEE"}
PROPERTY_FEE_MODES = {"BY_AREA", "FIXED_RATE"}
ENERGY_MODES = {"SUB_METER", "ALLOCATED"}
FEE_BILL_STATES = {"ISSUED", "DISPUTED", "PAID", "VOIDED"}
MOVE_OUT_STATES = {
    "SUBMITTED", "INSPECTION_DONE", "RESTORATION_CONFIRMED",
    "DEDUCTION_PROPOSED", "DEDUCTION_APPROVED", "SETTLED", "REJECTED",
}
INSPECTION_SEVERITIES = {"MINOR", "MAJOR"}
AUDIT_SUBJECT_KINDS = {"LEASE", "DEPOSIT", "FEE_BILL", "UNIT"}
AUDIT_ACTIONS = {
    "CONTRACT_SIGNED", "CONTRACT_AMENDED", "CONTRACT_RENEWED",
    "CONTRACT_TERMINATED", "FEE_ADJUSTED", "FEE_DISPUTED",
    "DEPOSIT_DEDUCTED", "DEPOSIT_REFUNDED", "UNIT_SPLIT", "UNIT_MERGED",
}


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------
def assert_building(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Building")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("address"), str) and data["address"]
    assert isinstance(data.get("floors_count"), int)
    assert data["floors_count"] >= 1, (
        f"Building.floors_count must be >= 1, got {data['floors_count']}"
    )
    assert data.get("status") in BUILDING_STATES


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------
def assert_unit(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Unit")
    assert is_valid_uuid(data.get("building_id", "")), (
        f"Unit.building_id must be UUID, got {data.get('building_id')!r}"
    )
    parent_unit_id = data.get("parent_unit_id")
    if parent_unit_id is not None:
        assert is_valid_uuid(parent_unit_id), (
            f"Unit.parent_unit_id must be UUID or null, got {parent_unit_id!r}"
        )
    assert isinstance(data.get("floor"), int) and data["floor"] >= 1
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("area_sqm"), (int, float))
    assert float(data["area_sqm"]) > 0, "Unit.area_sqm must be > 0"
    assert data.get("orientation") in ORIENTATIONS
    assert data.get("usage_type") in USAGE_TYPES
    assert isinstance(data.get("rent_reference_per_sqm"), (int, float))
    assert float(data["rent_reference_per_sqm"]) > 0
    assert data.get("status") in UNIT_STATES


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------
def assert_tenant(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Tenant")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("business_license_no"), str)
    assert is_iso8601_timestamp(data.get("license_expires_on", ""))
    assert data.get("qualification_status") in TENANT_STATES
    assert isinstance(data.get("contact_email"), str)
    # PRD §2.9: 'These aggregates are integer cents and never rounded'.
    for f in (
        "total_deposit_paid_cents",
        "total_deposit_refunded_cents",
        "total_deposit_retained_cents",
    ):
        v = data.get(f)
        assert isinstance(v, int) and v >= 0, (
            f"Tenant.{f} must be non-negative int, got {v!r}"
        )


def assert_tenant_ledger_invariant(tenant: Dict[str, Any]) -> None:
    """PRD §2.9 invariant: outstanding = paid − refunded − retained,
    and all components are non-negative integer cents."""
    paid = tenant["total_deposit_paid_cents"]
    refunded = tenant["total_deposit_refunded_cents"]
    retained = tenant["total_deposit_retained_cents"]
    outstanding = paid - refunded - retained
    assert outstanding >= 0, (
        f"Tenant ledger outstanding < 0: paid={paid}, refunded={refunded}, "
        f"retained={retained}, outstanding={outstanding}"
    )


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------
def assert_lease(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Lease")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("tenant_id", ""))
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert isinstance(data.get("base_monthly_rent_cents"), int)
    assert data["base_monthly_rent_cents"] >= 0
    assert data.get("escalation_mode") in ESCALATION_MODES
    assert isinstance(data.get("escalation_pct_bps", 0), int)
    assert isinstance(data.get("rent_free_days", 0), int)
    assert data.get("rent_free_days", 0) >= 0
    assert isinstance(data.get("deposit_months"), int)
    assert 1 <= data["deposit_months"] <= 6, (
        f"Lease.deposit_months must be in 1..6, got {data['deposit_months']}"
    )
    assert data.get("status") in LEASE_STATES
    if data.get("terminated_on") is not None:
        assert is_iso8601_timestamp(data["terminated_on"])
    assert isinstance(data.get("amendment_count", 0), int)
    assert data.get("amendment_count", 0) >= 0


# ---------------------------------------------------------------------------
# Deposit
# ---------------------------------------------------------------------------
def assert_deposit(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Deposit")
    assert is_valid_uuid(data.get("lease_id", ""))
    for f in ("required_cents", "collected_cents",
              "retained_cents", "refunded_cents"):
        v = data.get(f)
        assert isinstance(v, int) and v >= 0, (
            f"Deposit.{f} must be non-negative int, got {v!r}"
        )
    assert data.get("frozen_status") in DEPOSIT_FROZEN_STATES
    assert data.get("adjustment_status") in DEPOSIT_ADJUSTMENT_STATES
    pending = data.get("pending_deduction_items", [])
    assert isinstance(pending, list)
    for item in pending:
        assert item.get("kind") in DEDUCTION_KINDS, (
            f"deduction kind must be in {DEDUCTION_KINDS}, "
            f"got {item.get('kind')!r}"
        )
        assert isinstance(item.get("amount_cents"), int)
        assert item["amount_cents"] >= 0


# ---------------------------------------------------------------------------
# FeeBill
# ---------------------------------------------------------------------------
def assert_fee_bill(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "FeeBill")
    assert is_valid_uuid(data.get("lease_id", ""))
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("tenant_id", ""))
    assert data.get("bill_kind") in FEE_BILL_KINDS
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] >= 0
    assert data.get("status") in FEE_BILL_STATES
    if data["bill_kind"] == "PROPERTY_FEE":
        assert data.get("property_fee_mode") in PROPERTY_FEE_MODES
    elif data["bill_kind"] == "ENERGY_FEE":
        assert data.get("energy_mode") in ENERGY_MODES


# ---------------------------------------------------------------------------
# MoveOutRequest
# ---------------------------------------------------------------------------
def assert_move_out_request(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "MoveOutRequest")
    assert is_valid_uuid(data.get("lease_id", ""))
    assert is_iso8601_timestamp(data.get("requested_on", ""))
    assert is_iso8601_timestamp(data.get("target_move_out_date", ""))
    assert data.get("status") in MOVE_OUT_STATES
    findings = data.get("inspection_findings", [])
    assert isinstance(findings, list)
    for finding in findings:
        assert isinstance(finding.get("item"), str)
        assert finding.get("severity") in INSPECTION_SEVERITIES
        assert isinstance(finding.get("estimated_cost_cents"), int)
    assert isinstance(data.get("restoration_done", False), bool)


# ---------------------------------------------------------------------------
# RentScheduleItem  (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_rent_schedule_item(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "RentScheduleItem")
    # PRD §2.4: 'RentScheduleItem ... omit both updated_at and version'.
    assert "updated_at" not in data, (
        "RentScheduleItem must omit updated_at per PRD §2.4"
    )
    assert "version" not in data, (
        "RentScheduleItem must omit version per PRD §2.4"
    )
    assert is_valid_uuid(data.get("lease_id", ""))
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert isinstance(data.get("gross_rent_cents"), int)
    assert data["gross_rent_cents"] >= 0
    assert isinstance(data.get("rent_free_offset_cents"), int)
    assert data["rent_free_offset_cents"] >= 0
    assert isinstance(data.get("net_rent_cents"), int)
    assert data["net_rent_cents"] >= 0
    # PRD §3.4: 'The net_rent_cents of the row is the maximum of zero and
    # gross_rent_cents − rent_free_offset_cents.'
    assert data["net_rent_cents"] == max(
        0, data["gross_rent_cents"] - data["rent_free_offset_cents"]
    )
    assert data.get("status") in RENT_ITEM_STATES


# ---------------------------------------------------------------------------
# AuditEvent  (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_audit_event(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AuditEvent")
    assert "updated_at" not in data
    assert "version" not in data
    assert data.get("subject_kind") in AUDIT_SUBJECT_KINDS
    assert is_valid_uuid(data.get("subject_id", ""))
    assert data.get("action") in AUDIT_ACTIONS
    actor_role = data.get("actor_role")
    assert actor_role in {
        "PropertyManager", "LeasingAgent", "FinanceOfficer", "Tenant",
        "system",
    }, f"AuditEvent.actor_role unexpected: {actor_role!r}"
    assert isinstance(data.get("actor_id"), str)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert isinstance(data.get("payload"), dict)


def find_audit_events(
    rows: Iterable[Dict[str, Any]],
    *,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        if subject_kind is not None and r.get("subject_kind") != subject_kind:
            continue
        if subject_id is not None and r.get("subject_id") != subject_id:
            continue
        if action is not None and r.get("action") != action:
            continue
        out.append(r)
    return out


__all__ = [
    "BUILDING_STATES", "UNIT_STATES", "ORIENTATIONS", "USAGE_TYPES",
    "TENANT_STATES", "LEASE_STATES", "ESCALATION_MODES",
    "RENT_ITEM_STATES", "DEPOSIT_FROZEN_STATES",
    "DEPOSIT_ADJUSTMENT_STATES", "DEDUCTION_KINDS",
    "FEE_BILL_KINDS", "PROPERTY_FEE_MODES", "ENERGY_MODES",
    "FEE_BILL_STATES", "MOVE_OUT_STATES", "INSPECTION_SEVERITIES",
    "AUDIT_SUBJECT_KINDS", "AUDIT_ACTIONS",
    "assert_building", "assert_unit", "assert_tenant",
    "assert_tenant_ledger_invariant", "assert_lease",
    "assert_deposit", "assert_fee_bill", "assert_move_out_request",
    "assert_rent_schedule_item", "assert_audit_event",
    "find_audit_events",
]
