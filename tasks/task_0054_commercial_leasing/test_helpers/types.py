"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4:

- Versioned entities (id + created_at + updated_at + version):
  Building, Unit, Tenant, Lease, Deposit, FeeBill, MoveOutRequest.

- Append-only entities (id + created_at ONLY; NO updated_at, NO version):
  RentScheduleItem, AuditEvent.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    LEASING_AGENT = "LeasingAgent"
    FINANCE_OFFICER = "FinanceOfficer"
    TENANT = "Tenant"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.x)
# ---------------------------------------------------------------------------
class BuildingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class UnitStatus(str, Enum):
    VACANT = "VACANT"
    RESERVED = "RESERVED"
    LEASED = "LEASED"
    UNDER_RENOVATION = "UNDER_RENOVATION"
    RETIRED = "RETIRED"


class UnitOrientation(str, Enum):
    N = "N"
    S = "S"
    E = "E"
    W = "W"
    NE = "NE"
    NW = "NW"
    SE = "SE"
    SW = "SW"


class UnitUsageType(str, Enum):
    OFFICE = "OFFICE"
    RETAIL = "RETAIL"
    WAREHOUSE = "WAREHOUSE"
    FB = "FB"


class TenantQualificationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"


class EscalationMode(str, Enum):
    NONE = "NONE"
    ANNUAL = "ANNUAL"
    BIENNIAL = "BIENNIAL"
    STEPPED = "STEPPED"


class RentScheduleItemStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"


class DepositFrozenStatus(str, Enum):
    UNFROZEN = "UNFROZEN"
    FROZEN = "FROZEN"


class DepositAdjustmentStatus(str, Enum):
    AT_REST = "AT_REST"
    ADJUSTMENT_PENDING = "ADJUSTMENT_PENDING"
    DEDUCTION_PENDING_APPROVAL = "DEDUCTION_PENDING_APPROVAL"
    SETTLED = "SETTLED"


class DeductionKind(str, Enum):
    OVERDUE_RENT = "OVERDUE_RENT"
    DAMAGE = "DAMAGE"
    CLEANING = "CLEANING"


class FeeBillKind(str, Enum):
    PROPERTY_FEE = "PROPERTY_FEE"
    ENERGY_FEE = "ENERGY_FEE"


class PropertyFeeMode(str, Enum):
    BY_AREA = "BY_AREA"
    FIXED_RATE = "FIXED_RATE"


class EnergyMode(str, Enum):
    SUB_METER = "SUB_METER"
    ALLOCATED = "ALLOCATED"


class FeeBillStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class MoveOutRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INSPECTION_DONE = "INSPECTION_DONE"
    RESTORATION_CONFIRMED = "RESTORATION_CONFIRMED"
    DEDUCTION_PROPOSED = "DEDUCTION_PROPOSED"
    DEDUCTION_APPROVED = "DEDUCTION_APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class InspectionSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class AuditSubjectKind(str, Enum):
    LEASE = "LEASE"
    DEPOSIT = "DEPOSIT"
    FEE_BILL = "FEE_BILL"
    UNIT = "UNIT"


class AuditAction(str, Enum):
    CONTRACT_SIGNED = "CONTRACT_SIGNED"
    CONTRACT_AMENDED = "CONTRACT_AMENDED"
    CONTRACT_RENEWED = "CONTRACT_RENEWED"
    CONTRACT_TERMINATED = "CONTRACT_TERMINATED"
    FEE_ADJUSTED = "FEE_ADJUSTED"
    FEE_DISPUTED = "FEE_DISPUTED"
    DEPOSIT_DEDUCTED = "DEPOSIT_DEDUCTED"
    DEPOSIT_REFUNDED = "DEPOSIT_REFUNDED"
    UNIT_SPLIT = "UNIT_SPLIT"
    UNIT_MERGED = "UNIT_MERGED"


# ---------------------------------------------------------------------------
# Versioned entity TypedDicts (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Building(TypedDict):
    id: str
    name: str
    address: str
    floors_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    building_id: str
    parent_unit_id: Optional[str]
    floor: int
    code: str
    area_sqm: float
    orientation: str
    usage_type: str
    rent_reference_per_sqm: float
    status: str
    renovation_start_date: Optional[str]
    renovation_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    legal_name: str
    business_license_no: str
    license_expires_on: str
    qualification_status: str
    contact_email: str
    total_deposit_paid_cents: int
    total_deposit_refunded_cents: int
    total_deposit_retained_cents: int
    created_at: str
    updated_at: str
    version: int


class SteppedScheduleEntry(TypedDict):
    effective_from: str
    monthly_rent_cents: int


class Lease(TypedDict):
    id: str
    unit_id: str
    tenant_id: str
    start_date: str
    end_date: str
    base_monthly_rent_cents: int
    escalation_mode: str
    escalation_pct_bps: int
    stepped_schedule: Optional[List[SteppedScheduleEntry]]
    rent_free_days: int
    deposit_months: int
    status: str
    terminated_on: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    lease_id: str
    required_cents: int
    collected_cents: int
    retained_cents: int
    refunded_cents: int
    frozen_status: str
    adjustment_status: str
    pending_deduction_items: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class FeeBill(TypedDict):
    id: str
    lease_id: str
    unit_id: str
    tenant_id: str
    bill_kind: str
    period_start: str
    period_end: str
    property_fee_mode: Optional[str]
    rate_per_sqm_per_month_cents: Optional[int]
    fixed_rate_cents_per_month: Optional[int]
    energy_mode: Optional[str]
    sub_meter_kwh: Optional[float]
    shared_total_kwh: Optional[float]
    shared_meter_group_unit_ids: Optional[List[str]]
    tariff_per_kwh_cents: Optional[int]
    amount_cents: int
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoveOutRequest(TypedDict):
    id: str
    lease_id: str
    requested_on: str
    target_move_out_date: str
    status: str
    inspection_findings: List[Dict[str, Any]]
    restoration_done: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (PRD §2.4: id + created_at ONLY)
# ---------------------------------------------------------------------------
class RentScheduleItem(TypedDict):
    id: str
    lease_id: str
    period_start: str
    period_end: str
    gross_rent_cents: int
    rent_free_offset_cents: int
    net_rent_cents: int
    status: str
    created_at: str


class AuditEvent(TypedDict):
    id: str
    subject_kind: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    payload: Dict[str, Any]
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "BuildingStatus", "UnitStatus", "UnitOrientation", "UnitUsageType",
    "TenantQualificationStatus",
    "LeaseStatus", "EscalationMode",
    "RentScheduleItemStatus",
    "DepositFrozenStatus", "DepositAdjustmentStatus", "DeductionKind",
    "FeeBillKind", "PropertyFeeMode", "EnergyMode", "FeeBillStatus",
    "MoveOutRequestStatus", "InspectionSeverity",
    "AuditSubjectKind", "AuditAction",
    "Building", "Unit", "Tenant", "Lease", "Deposit",
    "FeeBill", "MoveOutRequest",
    "RentScheduleItem", "AuditEvent",
    "SteppedScheduleEntry",
]
