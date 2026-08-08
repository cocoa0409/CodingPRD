"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource definitions (§3) and lifecycle states (§2.4, §3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (§2.1) ──────────────────────────────────────────────────
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    DEVELOPER = "Developer"
    UTILITY_REVIEWER = "UtilityReviewer"
    FIELD_INSPECTOR = "FieldInspector"
    UTILITY_ADMIN = "UtilityAdmin"


# ─── Status enums ──────────────────────────────────────────────────────
class ConnectionApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    READY_FOR_ACTIVATION = "READY_FOR_ACTIVATION"
    ACTIVATED = "ACTIVATED"
    WITHDRAWN = "WITHDRAWN"


class MainExtensionProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED_TO_CONSTRUCT = "APPROVED_TO_CONSTRUCT"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    INSPECTED = "INSPECTED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class DeveloperAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ESCROW = "PENDING_ESCROW"
    EXECUTED = "EXECUTED"
    COMPLETION_PENDING = "COMPLETION_PENDING"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class InspectionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BackflowAssemblyStatus(str, Enum):
    REQUIRED = "REQUIRED"
    INSTALLED = "INSTALLED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class MeterSetStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    SET = "SET"
    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"


class ServiceAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class LatecomerReimbursementStatus(str, Enum):
    ASSESSED = "ASSESSED"
    COLLECTED = "COLLECTED"
    WAIVED = "WAIVED"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# Entities carrying id + created_at + updated_at + version (§2.4).

class MeterSizeSchedule(TypedDict):
    id: str
    meter_size: str
    eru_factor: float
    tap_install_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    is_active: bool
    water_capacity_fee_per_eru_cents: int
    sewer_capacity_fee_per_eru_cents: int
    use_multipliers: dict
    admin_fee_pct: float
    admin_fee_cap_cents: int
    volume_discount_threshold_cents: int
    volume_discount_pct: float
    pavement_cut_surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    name: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class MeterCrew(TypedDict):
    id: str
    name: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class ConnectionApplication(TypedDict):
    id: str
    applicant_user_id: str
    parcel_id: str
    service_type: str
    meter_size: str
    use_type: str
    requires_pavement_cut: bool
    prior_credit_eru: float
    assessment_basis: str
    availability_reviewer_id: Optional[str]
    backflow_required: Optional[bool]
    capacity_fee_cents: Optional[int]
    tap_fee_cents: Optional[int]
    total_fees_due_cents: Optional[int]
    fees_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityDetermination(TypedDict):
    id: str
    application_id: str
    distance_to_main_ft: float
    water_main_available: bool
    sewer_main_available: bool
    extension_required: bool
    created_at: str
    updated_at: str
    version: int


class MainExtensionProject(TypedDict):
    id: str
    application_id: str
    developer_user_id: str
    length_ft: float
    estimated_cost_cents: int
    total_assessable_front_ft: float
    total_assessable_area_sqft: float
    actual_construction_cost_cents: Optional[int]
    reimbursable_principal_cents: Optional[int]
    reimbursed_collected_cents: Optional[int]
    outstanding_recoverable_cents: Optional[int]
    reimbursement_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeveloperAgreement(TypedDict):
    id: str
    main_extension_project_id: str
    developer_user_id: str
    required_escrow_cents: Optional[int]
    escrow_deposited_cents: int
    escrow_drawn_cents: int
    escrow_refunded_cents: int
    escrow_held_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry (§2.4): carries ONLY id + created_at.
class EscrowTransaction(TypedDict):
    id: str
    developer_agreement_id: str
    txn_type: str
    amount_cents: int
    memo: str
    created_at: str


class Inspection(TypedDict):
    id: str
    application_id: str
    inspector_id: str
    inspection_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BackflowAssembly(TypedDict):
    id: str
    application_id: str
    serial_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MeterSet(TypedDict):
    id: str
    application_id: str
    crew_id: str
    appointment_start: str
    appointment_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAccount(TypedDict):
    id: str
    application_id: str
    account_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LatecomerReimbursement(TypedDict):
    id: str
    main_extension_project_id: str
    benefiting_application_id: str
    method: str
    parcel_front_ft: float
    parcel_area_sqft: float
    amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
