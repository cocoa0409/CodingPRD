"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this domain is mutable and carries the four common fields
id, created_at, updated_at, and version (PRD §2.4). There are no append-only
resources here, so every TypedDict lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ------------------------------------------------------------------
class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    OWNER = "Owner"
    TENANT = "Tenant"
    APPLICANT = "Applicant"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums -----------------------------------------------------------
class ApplicantStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENED = "SCREENED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    LEASED = "LEASED"
    WITHDRAWN = "WITHDRAWN"


class ScreeningDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_OFFERED = "RENEWAL_OFFERED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class TenantStatus(str, Enum):
    CURRENT = "CURRENT"
    FORMER = "FORMER"


class UnitOccupancyStatus(str, Enum):
    VACANT_READY = "VACANT_READY"
    OCCUPIED = "OCCUPIED"
    VACANT_TURN = "VACANT_TURN"


class RentChargeStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ChargeType(str, Enum):
    RENT = "RENT"
    LATE_FEE = "LATE_FEE"


class SecurityDepositStatus(str, Enum):
    HELD = "HELD"
    SETTLED = "SETTLED"
    FORFEITED = "FORFEITED"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EvictionStatus(str, Enum):
    NOTICE_SERVED = "NOTICE_SERVED"
    CURED = "CURED"
    FILED = "FILED"
    ENFORCED = "ENFORCED"
    DISMISSED = "DISMISSED"


class OwnerStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DISTRIBUTED = "DISTRIBUTED"


class TurnoverStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"


# --- Entity TypedDicts (all carry the four common fields) -------------------
class Owner(TypedDict):
    id: str
    legal_name: str
    email: str
    distribution_method: str
    management_fee_pct: float
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    owner_id: str
    name: str
    state_code: str
    address: str
    trust_balance_cents: int
    distributable_cents: int
    reserve_floor_cents: int
    unit_count: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    property_id: str
    label: str
    market_rent_cents: int
    occupancy_status: str
    active_lease_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    unit_id: str
    annual_income_cents: int
    credit_score: int
    monthly_debt_cents: int
    requested_rent_cents: int
    status: str
    screening_decision: Optional[str]
    rent_to_income_ratio: Optional[float]
    dti_ratio: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    unit_id: str
    applicant_id: Optional[str]
    tenant_id: Optional[str]
    renewed_from_lease_id: Optional[str]
    start_date: str
    end_date: str
    monthly_rent_cents: int
    rent_due_day: int
    grace_period_days: int
    late_fee_flat_cents: int
    late_fee_pct: float
    status: str
    balance_due_cents: int
    superseded_by_lease_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    applicant_id: str
    full_name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RentCharge(TypedDict):
    id: str
    lease_id: str
    charge_type: str
    period_label: Optional[str]
    due_date: str
    amount_cents: int
    amount_paid_cents: int
    amount_outstanding_cents: int
    late_fee_assessed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    lease_id: str
    amount_cents: int
    received_date: str
    applied_breakdown: List[dict]
    applied_to_rent_cents: int
    unapplied_cents: int
    created_at: str
    updated_at: str
    version: int


class SecurityDeposit(TypedDict):
    id: str
    lease_id: str
    collected_cents: int
    collected_date: str
    interest_accrued_cents: int
    deductions_cents: int
    refund_cents: int
    settlement_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    unit_id: str
    category: str
    priority: str
    description: str
    estimate_cents: int
    actual_cost_cents: Optional[int]
    charge_to_owner: bool
    completed_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EvictionCase(TypedDict):
    id: str
    lease_id: str
    reason: str
    notice_date: str
    cure_deadline_date: Optional[str]
    arrears_at_notice_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnerStatement(TypedDict):
    id: str
    property_id: str
    period_label: str
    basis: str
    gross_cents: int
    management_fee_cents: int
    maintenance_cents: int
    net_to_owner_cents: int
    distribution_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TurnoverProject(TypedDict):
    id: str
    unit_id: str
    opened_date: str
    target_ready_date: str
    make_ready_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
