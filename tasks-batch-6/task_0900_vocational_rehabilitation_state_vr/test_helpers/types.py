"""Domain types for the Vocational Rehabilitation (State VR) API.

Entity TypedDicts, status enums, and the role enum, all derived from the PRD.
Full-lifecycle resources (Provider, PriorityCategory, Case, IPE,
ServiceAuthorization, Payment, Placement) carry id/created_at/updated_at/version.
Lightweight records (Counselor, Supervisor, ProgressReview) carry only
id/created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    VR_ADMIN = "VRAdmin"
    COUNSELOR = "Counselor"
    SUPERVISOR = "Supervisor"
    FISCAL_OFFICER = "FiscalOfficer"
    PROVIDER = "Provider"


class CaseStatus(str, Enum):
    REFERRED = "REFERRED"
    APPLICATION = "APPLICATION"
    WAITLISTED = "WAITLISTED"
    PLAN_DEVELOPMENT = "PLAN_DEVELOPMENT"
    SERVICES_ACTIVE = "SERVICES_ACTIVE"
    EMPLOYED = "EMPLOYED"
    INELIGIBLE = "INELIGIBLE"
    CLOSED_REHABILITATED = "CLOSED_REHABILITATED"
    CLOSED_OTHER = "CLOSED_OTHER"


class IPEStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    AMENDING = "AMENDING"
    CLOSED = "CLOSED"


class ServiceAuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class PlacementStatus(str, Enum):
    PLACED = "PLACED"
    STABILIZING = "STABILIZING"
    DESTABILIZED = "DESTABILIZED"
    STABLE = "STABLE"
    CLOSED = "CLOSED"


class PriorityCategoryStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DisabilityType(str, Enum):
    PHYSICAL = "PHYSICAL"
    COGNITIVE = "COGNITIVE"
    PSYCHIATRIC = "PSYCHIATRIC"
    SENSORY = "SENSORY"


class DisabilitySignificance(str, Enum):
    MSD = "MSD"
    SD = "SD"
    NSD = "NSD"


class ServiceCategory(str, Enum):
    TRAINING = "TRAINING"
    ASSISTIVE_TECH = "ASSISTIVE_TECH"
    ASSESSMENT = "ASSESSMENT"
    SUPPORTED_EMPLOYMENT = "SUPPORTED_EMPLOYMENT"


class EmploymentType(str, Enum):
    COMPETITIVE_INTEGRATED = "COMPETITIVE_INTEGRATED"
    SUPPORTED = "SUPPORTED"
    SELF_EMPLOYMENT = "SELF_EMPLOYMENT"


# ---- Lightweight records: id + created_at only ----

class Counselor(TypedDict):
    id: str
    name: str
    email: str
    unit: str
    created_at: str


class Supervisor(TypedDict):
    id: str
    name: str
    email: str
    created_at: str


class ProgressReview(TypedDict):
    id: str
    placement_id: str
    review_date: str
    reported_weekly_wage_cents: int
    status_ok: bool
    created_at: str


# ---- Full-lifecycle records: id + created_at + updated_at + version ----

class Provider(TypedDict):
    id: str
    name: str
    service_categories: List[str]
    max_concurrent_authorizations: int
    status: str
    pending_disbursement_cents: int
    ledger_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class PriorityCategory(TypedDict):
    id: str
    rank: int
    label: str
    status: str
    slot_capacity: int
    slots_used: int
    available_slots: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    counselor_id: str
    priority_category_id: Optional[str]
    consumer_full_name: str
    consumer_dob: str
    disability_type: str
    disability_significance: Optional[str]
    referral_source: str
    monthly_income_cents: int
    budget_allocated_cents: int
    funds_committed_cents: int
    funds_paid_cents: int
    funds_available_cents: int
    status: str
    waitlisted_at: Optional[str]
    closure_type: Optional[str]
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IPE(TypedDict):
    id: str
    case_id: str
    employment_goal: str
    goal_wage_target_cents: int
    status: str
    approved_by_supervisor_id: Optional[str]
    approved_plan_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ServiceAuthorization(TypedDict):
    id: str
    case_id: str
    ipe_id: str
    provider_id: str
    service_category: str
    authorized_amount_cents: int
    comparable_benefit_cents: int
    consumer_share_cents: int
    agency_share_cents: int
    service_period_start: str
    service_period_end: str
    status: str
    requested_by_counselor_id: str
    approved_by_supervisor_id: Optional[str]
    amount_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    authorization_id: str
    provider_id: str
    amount_cents: int
    status: str
    federal_share_cents: Optional[int]
    state_share_cents: Optional[int]
    issued_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    case_id: str
    ipe_id: str
    employer_name: str
    placement_date: str
    weekly_wage_cents: int
    hours_per_week: int
    employment_type: str
    status: str
    stabilization_start_date: Optional[str]
    verified_avg_weekly_wage_cents: Optional[int]
    days_stable: int
    created_at: str
    updated_at: str
    version: int
