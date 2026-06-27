"""Domain types: entity TypedDicts, status enums, role enum.

All fourteen resource types carry id, created_at, updated_at, and version
(common system fields per the PRD), so every entity TypedDict lists them.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PETITIONER = "Petitioner"
    COURT_EXAMINER = "CourtExaminer"
    JUDGE = "Judge"
    FIDUCIARY = "Fiduciary"
    COURT_CLERK = "CourtClerk"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------
class CapacityStatus(str, Enum):
    PRESUMED_COMPETENT = "PRESUMED_COMPETENT"
    ADJUDICATED_INCAPACITATED = "ADJUDICATED_INCAPACITATED"
    RESTORED = "RESTORED"


class FiduciaryKind(str, Enum):
    FAMILY = "FAMILY"
    PROFESSIONAL = "PROFESSIONAL"
    PUBLIC_AGENCY = "PUBLIC_AGENCY"


class CaseType(str, Enum):
    GUARDIANSHIP = "GUARDIANSHIP"
    CONSERVATORSHIP = "CONSERVATORSHIP"
    PLENARY = "PLENARY"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_EVALUATION = "PENDING_EVALUATION"
    AWAITING_APPOINTMENT = "AWAITING_APPOINTMENT"
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    TERMINATED = "TERMINATED"
    RESTORED = "RESTORED"


class ProtectionPosture(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class RequestedAuthority(str, Enum):
    PERSON = "PERSON"
    ESTATE = "ESTATE"
    BOTH = "BOTH"


class PetitionStatus(str, Enum):
    FILED = "FILED"
    PROBABLE_CAUSE = "PROBABLE_CAUSE"
    EVALUATION_ORDERED = "EVALUATION_ORDERED"
    READY_FOR_HEARING = "READY_FOR_HEARING"
    GRANTED = "GRANTED"
    DISMISSED = "DISMISSED"


class EvaluationFinding(str, Enum):
    INCAPACITATED = "INCAPACITATED"
    PARTIALLY_INCAPACITATED = "PARTIALLY_INCAPACITATED"
    COMPETENT = "COMPETENT"


class RecommendedScope(str, Enum):
    NONE = "NONE"
    PERSON = "PERSON"
    ESTATE = "ESTATE"
    BOTH = "BOTH"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"


class GrantedAuthority(str, Enum):
    PERSON = "PERSON"
    ESTATE = "ESTATE"
    BOTH = "BOTH"


class AppointmentStatus(str, Enum):
    PENDING_QUALIFICATION = "PENDING_QUALIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class BondStatus(str, Enum):
    REQUIRED = "REQUIRED"
    POSTED = "POSTED"
    APPROVED = "APPROVED"
    EXONERATED = "EXONERATED"


class RestrictedAccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class InventoryStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    APPROVED = "APPROVED"


class BudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ExpenditureCategory(str, Enum):
    CARE = "CARE"
    MEDICAL = "MEDICAL"
    ADMIN = "ADMIN"


class ExpenditureStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PENDING_COURT = "PENDING_COURT"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    DENIED = "DENIED"


class AccountingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    APPROVED = "APPROVED"


class ResidenceType(str, Enum):
    HOME = "HOME"
    ASSISTED_LIVING = "ASSISTED_LIVING"
    NURSING_FACILITY = "NURSING_FACILITY"
    HOSPITAL = "HOSPITAL"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REPLACED = "REPLACED"


class ReviewSubjectKind(str, Enum):
    ACCOUNTING = "ACCOUNTING"
    CARE_PLAN = "CARE_PLAN"


class ReviewOutcome(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    CONTINUED = "CONTINUED"
    SANCTIONED = "SANCTIONED"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class ProtectedPerson(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    annual_income_cents: int
    liquid_estate_cents: int
    capacity_status: str
    active_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Fiduciary(TypedDict):
    id: str
    full_name: str
    fiduciary_kind: str
    is_disqualified: bool
    open_appointment_count: int
    created_at: str
    updated_at: str
    version: int


class GuardianshipCase(TypedDict):
    id: str
    protected_person_id: str
    case_type: str
    status: str
    protection_posture: str
    requires_bond: bool
    next_accounting_due_iso: Optional[str]
    overdue_accounting_count: int
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict):
    id: str
    case_id: str
    petitioner_user_id: str
    nominated_fiduciary_id: str
    requested_authority: str
    alleged_grounds: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityEvaluation(TypedDict):
    id: str
    petition_id: str
    examiner_user_id: str
    finding: str
    recommended_scope: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    case_id: str
    fiduciary_id: str
    granted_authority: str
    letters_issued_iso: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict):
    id: str
    appointment_id: str
    required_amount_cents: int
    posted_amount_cents: int
    surety_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RestrictedAccount(TypedDict):
    id: str
    case_id: str
    institution_name: str
    principal_balance_cents: int
    encumbered_cents: int
    available_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inventory(TypedDict):
    id: str
    case_id: str
    real_property_cents: int
    liquid_assets_cents: int
    tangible_property_cents: int
    total_estate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Budget(TypedDict):
    id: str
    case_id: str
    period_year: int
    care_cap_cents: int
    medical_cap_cents: int
    admin_cap_cents: int
    care_spent_cents: int
    medical_spent_cents: int
    admin_spent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Expenditure(TypedDict):
    id: str
    case_id: str
    budget_id: str
    category: str
    amount_cents: int
    payee_name: str
    requires_court_approval: bool
    disbursed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountingReport(TypedDict):
    id: str
    case_id: str
    period_year: int
    opening_balance_cents: int
    reported_income_cents: int
    reported_disbursed_cents: int
    ledger_disbursed_cents: int
    projected_disbursed_cents: int
    variance_cents: int
    fiduciary_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    case_id: str
    residence_type: str
    visitation_min_per_month: int
    window_start_iso: str
    window_end_iso: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CourtReview(TypedDict):
    id: str
    case_id: str
    subject_kind: str
    subject_ref_id: str
    review_window_start_iso: str
    review_window_end_iso: str
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int
