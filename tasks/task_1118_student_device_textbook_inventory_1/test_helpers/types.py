"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    DISTRICT_ADMIN = "DistrictAdmin"
    REGISTRAR = "Registrar"
    SITE_TECHNICIAN = "SiteTechnician"
    FAMILY = "Family"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUMMER_COLLECTION = "SUMMER_COLLECTION"
    CLOSED = "CLOSED"


class StudentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"


class FinancialPosture(str, Enum):
    CLEAR = "CLEAR"
    FEES_OUTSTANDING = "FEES_OUTSTANDING"
    SUSPENDED = "SUSPENDED"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class AssetClass(str, Enum):
    DEVICE = "DEVICE"
    TEXTBOOK = "TEXTBOOK"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class LifecycleStatus(str, Enum):
    READY = "READY"
    DEPLOYED = "DEPLOYED"
    IN_REPAIR = "IN_REPAIR"
    LOANER = "LOANER"
    SUMMER_INTAKE = "SUMMER_INTAKE"
    RE_IMAGING = "RE_IMAGING"
    END_OF_LIFE = "END_OF_LIFE"
    DISPOSED = "DISPOSED"
    DONATED = "DONATED"
    WRITTEN_OFF = "WRITTEN_OFF"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    LOST = "LOST"


class DamageCategory(str, Enum):
    COSMETIC = "COSMETIC"
    FUNCTIONAL = "FUNCTIONAL"
    LIQUID = "LIQUID"
    SCREEN = "SCREEN"
    LOSS = "LOSS"
    THEFT = "THEFT"


class ReportedByRole(str, Enum):
    FAMILY = "FAMILY"
    SITE_TECH = "SITE_TECH"
    SYSTEM = "SYSTEM"


class DamageReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class FeeType(str, Enum):
    DAMAGE = "DAMAGE"
    LATE_RETURN = "LATE_RETURN"
    NON_RETURN = "NON_RETURN"
    INSURANCE_DEDUCTIBLE = "INSURANCE_DEDUCTIBLE"


class FeeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    APPEALED = "APPEALED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class CheckoutReason(str, Enum):
    REPAIR = "REPAIR"
    LOSS_PENDING = "LOSS_PENDING"
    NEW_ENROLLMENT = "NEW_ENROLLMENT"


class LoanerCheckoutStatus(str, Enum):
    OPEN = "OPEN"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"


class LifecycleEventType(str, Enum):
    INTAKE = "INTAKE"
    DEPLOY = "DEPLOY"
    RETURN = "RETURN"
    REPAIR_START = "REPAIR_START"
    REPAIR_COMPLETE = "REPAIR_COMPLETE"
    RE_IMAGE = "RE_IMAGE"
    RETIRE = "RETIRE"
    DISPOSE = "DISPOSE"
    DONATE = "DONATE"
    WRITE_OFF = "WRITE_OFF"
    CORRECTION = "CORRECTION"


class SweepStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    RECONCILING = "RECONCILING"
    CLOSED = "CLOSED"


# --- Entity TypedDicts ---
# Entities carrying the full common field set (id, created_at, updated_at,
# version) per PRD §2.5.

class DistrictProgram(TypedDict, total=False):
    id: str
    program_name: str
    school_year: str
    loaner_pool_threshold_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StudentAccount(TypedDict, total=False):
    id: str
    program_id: str
    student_external_id: str
    full_name: str
    grade_level: int
    free_lunch_eligible: bool
    family_agreement_status: str
    insurance_enrolled: bool
    financial_posture: str
    outstanding_balance_cents: int
    lifetime_damage_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# FamilyAgreement is a write-once record: only id + created_at (PRD §2.5).
class FamilyAgreement(TypedDict, total=False):
    id: str
    student_account_id: str
    acceptable_use_version: str
    signed_by_guardian_name: str
    signed_at: Optional[str]
    signature_state: str
    created_at: str


class InsurancePolicy(TypedDict, total=False):
    id: str
    student_account_id: str
    premium_cents: int
    deductible_cents: int
    coverage_cap_cents: int
    academic_year: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AssetFleet(TypedDict, total=False):
    id: str
    program_id: str
    fleet_name: str
    asset_class: str
    unit_replacement_cost_cents: int
    salvage_value_cents: int
    useful_life_months: int
    in_service_date: str
    created_at: str
    updated_at: str
    version: int


class AssetUnit(TypedDict, total=False):
    id: str
    fleet_id: str
    asset_tag_barcode: str
    serial_number: str
    condition_grade: str
    lifecycle_status: str
    depreciated_value_cents: int
    months_in_service: int
    assigned_to_student_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    student_account_id: str
    asset_unit_id: str
    expected_return_date: str
    checked_out_at: str
    checked_in_at: Optional[str]
    checkout_condition_grade: str
    return_condition_grade: Optional[str]
    late_return_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageReport(TypedDict, total=False):
    id: str
    assignment_id: str
    reported_by_role: str
    damage_category: str
    observed_condition_grade: str
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    student_account_id: str
    source_damage_report_id: Optional[str]
    fee_type: str
    amount_cents: int
    waived_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanerCheckout(TypedDict, total=False):
    id: str
    student_account_id: str
    loaner_asset_unit_id: str
    checkout_reason: str
    max_loaner_days: int
    returned_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# AssetLifecycleEvent is a write-once record: only id + created_at (PRD §2.5).
class AssetLifecycleEvent(TypedDict, total=False):
    id: str
    asset_unit_id: str
    event_type: str
    supersedes_event_id: Optional[str]
    event_payload: dict
    occurred_at: str
    created_at: str


class AuditSweep(TypedDict, total=False):
    id: str
    program_id: str
    sweep_label: str
    started_at: Optional[str]
    closed_at: Optional[str]
    unaccounted_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
