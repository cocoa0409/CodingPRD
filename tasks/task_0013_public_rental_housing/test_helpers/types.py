"""Domain types for the Public Rental Housing API.

Status enums and entity TypedDicts derived from PRD §3.

All entities except SyncEvent carry common fields (id, created_at, updated_at, version).
SyncEvent is an immutable append-only journal (PRD §2.4) and carries only id and created_at;
its TypedDict therefore omits updated_at and version on purpose.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ──────────────────────────────────────────────────────────
# Roles (PRD §2.1)
# ──────────────────────────────────────────────────────────


class UserRole(str, Enum):
    HOUSING_DIRECTOR = "HousingDirector"
    HOUSING_OFFICER = "HousingOfficer"
    APPLICANT = "Applicant"
    CITIZEN = "Citizen"
    INTEGRATION_GATEWAY = "IntegrationGateway"


# ──────────────────────────────────────────────────────────
# Application
# ──────────────────────────────────────────────────────────


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    SCORED = "SCORED"
    QUEUED = "QUEUED"
    ALLOCATED = "ALLOCATED"
    OCCUPIED = "OCCUPIED"
    EXIT_PENDING = "EXIT_PENDING"
    EXITED = "EXITED"
    REJECTED = "REJECTED"


class CrossCheckStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class HouseholdType(str, Enum):
    LOW_INCOME = "LOW_INCOME"
    NEW_CITIZEN = "NEW_CITIZEN"
    RELOCATION = "RELOCATION"
    TALENT = "TALENT"


class Relation(str, Enum):
    SELF = "SELF"
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    OTHER = "OTHER"


class SpecialCareCategory(str, Enum):
    NONE = "NONE"
    VETERAN = "VETERAN"
    MARTYR_FAMILY = "MARTYR_FAMILY"
    SINGLE_PARENT = "SINGLE_PARENT"
    ELDERLY_LIVE_ALONE = "ELDERLY_LIVE_ALONE"


# ──────────────────────────────────────────────────────────
# Allocation / Objection / Contract
# ──────────────────────────────────────────────────────────


class AllocationStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    UNDER_OBJECTION = "UNDER_OBJECTION"
    CONFIRMED = "CONFIRMED"
    REVERTED = "REVERTED"


class ObjectionStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    SUSTAINED = "SUSTAINED"
    DISMISSED = "DISMISSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


# ──────────────────────────────────────────────────────────
# Housing unit
# ──────────────────────────────────────────────────────────


class ApartmentType(str, Enum):
    STUDIO = "STUDIO"
    ONE_BEDROOM = "ONE_BEDROOM"
    TWO_BEDROOM = "TWO_BEDROOM"
    THREE_BEDROOM = "THREE_BEDROOM"


class HousingUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    RETIRED = "RETIRED"


# ──────────────────────────────────────────────────────────
# Rent reduction / Annual review
# ──────────────────────────────────────────────────────────


class RentReductionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PRIMARY_REVIEW = "PRIMARY_REVIEW"
    SECONDARY_REVIEW = "SECONDARY_REVIEW"
    FINAL_APPROVED = "FINAL_APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class HardshipCategory(str, Enum):
    MAJOR_ILLNESS = "MAJOR_ILLNESS"
    UNEMPLOYMENT = "UNEMPLOYMENT"
    DISABILITY = "DISABILITY"
    ELDER_CARE = "ELDER_CARE"


class AnnualReviewStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class ReEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


# ──────────────────────────────────────────────────────────
# Sync event
# ──────────────────────────────────────────────────────────


class SyncEventType(str, Enum):
    CIVIL_AFFAIRS_HOUSEHOLD = "CIVIL_AFFAIRS_HOUSEHOLD"
    PUBLIC_SECURITY_IDENTITY = "PUBLIC_SECURITY_IDENTITY"
    TAX_INCOME_ASSETS = "TAX_INCOME_ASSETS"
    SOCIAL_SECURITY_INCOME = "SOCIAL_SECURITY_INCOME"
    PAYMENT_DEPOSIT = "PAYMENT_DEPOSIT"
    PAYMENT_RENT = "PAYMENT_RENT"
    AUDIT_ELIGIBILITY_CHANGE = "AUDIT_ELIGIBILITY_CHANGE"
    AUDIT_ALLOCATION_DECISION = "AUDIT_ALLOCATION_DECISION"


class SubjectType(str, Enum):
    APPLICATION = "APPLICATION"
    ALLOCATION = "ALLOCATION"
    CONTRACT = "CONTRACT"
    RENT_REDUCTION = "RENT_REDUCTION"


# ──────────────────────────────────────────────────────────
# Entity TypedDicts
# ──────────────────────────────────────────────────────────


class HouseholdMember(TypedDict, total=False):
    citizen_id: str
    relation: str
    dob: str
    has_disability: bool
    special_care_category: str


class HousingProgram(TypedDict, total=False):
    id: str
    name: str
    description: Optional[str]
    current_period_index: int
    notice_period_length: int
    grace_period_length: int
    per_capita_income_threshold_cents: int
    per_capita_asset_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    housing_program_id: str
    applicant_user_id: str
    household_members: List[HouseholdMember]
    household_type: str
    declared_monthly_income_cents: int
    declared_total_assets_cents: int
    residence_start_period: int
    requires_accessibility: bool
    family_size: int
    verified_monthly_income_cents: Optional[int]
    verified_total_assets_cents: Optional[int]
    cross_check_status: str
    queue_score: Optional[int]
    tie_break_key: Optional[str]
    status: str
    rejection_reason: Optional[str]
    exit_trigger_period: Optional[int]
    created_at: str
    updated_at: str
    version: int


class HousingUnit(TypedDict, total=False):
    id: str
    housing_program_id: str
    unit_code: str
    apartment_type: str
    bedroom_count: int
    square_meters: int
    monthly_base_rent_cents: int
    location_priority_tier: int
    accessibility_compliant: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    housing_program_id: str
    application_id: str
    housing_unit_id: str
    notice_start_period: int
    notice_end_period: int
    confirmation_period: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Objection(TypedDict, total=False):
    id: str
    allocation_id: str
    submitter_user_id: str
    reason_text: str
    review_decision: Optional[str]
    review_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    allocation_id: str
    application_id: str
    housing_unit_id: str
    lease_start_period: Optional[int]
    lease_end_period: Optional[int]
    deposit_amount_cents: int
    deposit_paid: bool
    signature_blob: Optional[str]
    handover_recorded: bool
    monthly_effective_rent_cents: Optional[int]
    status: str
    termination_period: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RentReduction(TypedDict, total=False):
    id: str
    contract_id: str
    hardship_category: str
    declared_hardship_income_cents: int
    supporting_documents: list
    requested_discount_bps: Optional[int]
    provisional_discount_bps: int
    final_discount_bps: Optional[int]
    validity_start_period: Optional[int]
    validity_end_period: Optional[int]
    primary_review_user_id: Optional[str]
    secondary_review_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualReview(TypedDict, total=False):
    id: str
    application_id: str
    review_period_index: int
    updated_household_members: Optional[List[HouseholdMember]]
    updated_declared_monthly_income_cents: Optional[int]
    updated_declared_total_assets_cents: Optional[int]
    re_eligibility: Optional[str]
    recomputed_queue_score: Optional[int]
    rent_adjustment_cents: Optional[int]
    exit_triggered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# SyncEvent has common_fields = false: only id and created_at (PRD §2.4).
class SyncEvent(TypedDict, total=False):
    id: str
    housing_program_id: str
    event_type: str
    subject_type: str
    subject_id: str
    payload: dict
    emitted_period: int
    created_at: str
