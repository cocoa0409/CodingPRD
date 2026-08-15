"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ProgramStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PoolType(str, Enum):
    GENERAL = "GENERAL"
    HU_BEGINNING_FARMER = "HU_BEGINNING_FARMER"
    HU_SOCIALLY_DISADVANTAGED = "HU_SOCIALLY_DISADVANTAGED"
    HU_LIMITED_RESOURCE = "HU_LIMITED_RESOURCE"
    HU_VETERAN = "HU_VETERAN"


class PracticeCode(str, Enum):
    COVER_CROP = "COVER_CROP"
    PRESCRIBED_GRAZING = "PRESCRIBED_GRAZING"
    WATERING_FACILITY = "WATERING_FACILITY"
    FENCE = "FENCE"
    NUTRIENT_MANAGEMENT = "NUTRIENT_MANAGEMENT"


class PracticeUnit(str, Enum):
    ACRE = "ACRE"
    FOOT = "FOOT"
    EACH = "EACH"


class HuCategory(str, Enum):
    NONE = "NONE"
    BEGINNING_FARMER = "BEGINNING_FARMER"
    SOCIALLY_DISADVANTAGED = "SOCIALLY_DISADVANTAGED"
    LIMITED_RESOURCE = "LIMITED_RESOURCE"
    VETERAN = "VETERAN"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCREENED_IN = "SCREENED_IN"
    SCREENED_OUT = "SCREENED_OUT"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    CONTRACTED = "CONTRACTED"
    OBLIGATED = "OBLIGATED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    OBLIGATED = "OBLIGATED"
    MODIFICATION_PENDING = "MODIFICATION_PENDING"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class CertificationStatus(str, Enum):
    PLANNED = "PLANNED"
    INSTALLED = "INSTALLED"
    CERTIFIED = "CERTIFIED"
    CERTIFICATION_FAILED = "CERTIFICATION_FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    CERTIFICATION_REVOKED = "CERTIFICATION_REVOKED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    ADVANCE_HELD = "ADVANCE_HELD"
    PAID = "PAID"
    RECOUPMENT_PENDING = "RECOUPMENT_PENDING"
    RECOUPED = "RECOUPED"


class PaymentRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class AdvanceStatus(str, Enum):
    ISSUED = "ISSUED"
    RETURN_DUE = "RETURN_DUE"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class ModificationKind(str, Enum):
    EXTEND_DEADLINE = "EXTEND_DEADLINE"
    ADD_PRACTICE = "ADD_PRACTICE"
    DROP_PRACTICE = "DROP_PRACTICE"


class ModificationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SpotCheckStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ObligationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VIOLATION_REVIEW = "VIOLATION_REVIEW"
    VIOLATION_CONFIRMED = "VIOLATION_CONFIRMED"
    SATISFIED = "SATISFIED"
    VOID = "VOID"


class DemandStatus(str, Enum):
    DEMANDED = "DEMANDED"
    ESCALATED = "ESCALATED"
    PAID = "PAID"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CONSERVATION_PLANNER = "ConservationPlanner"
    PAYMENT_OFFICER = "PaymentOfficer"
    QUALITY_ASSURANCE_OFFICER = "QualityAssuranceOfficer"
    APPLICANT = "Applicant"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# Payment schedule rates and ranking criteria are immutable configuration rows
# carrying only id and created_at (PRD §2.4).


class ConservationProgram(TypedDict, total=False):
    id: str
    program_name: str
    fiscal_year: int
    state_code: str
    window_start: str
    window_end: str
    spot_check_modulus: int
    advance_cap_pct: float
    status: str
    ranking_run_count: int
    created_at: str
    updated_at: str
    version: int


class FundingPool(TypedDict, total=False):
    id: str
    program_id: str
    pool_type: str
    allocated_cents: int
    obligated_cents: int
    paid_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class PaymentScheduleRate(TypedDict, total=False):
    # Immutable configuration row: id + created_at only (no updated_at / version).
    id: str
    program_id: str
    practice_code: str
    unit: str
    standard_rate_cents: int
    hu_rate_cents: int
    lifespan_years: int
    created_at: str


class RankingCriterion(TypedDict, total=False):
    # Immutable configuration row: id + created_at only (no updated_at / version).
    id: str
    program_id: str
    criterion_code: str
    weight: float
    max_points: int
    created_at: str


class Applicant(TypedDict, total=False):
    id: str
    legal_name: str
    hu_category: str
    historically_underserved: bool
    parcel_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    program_id: str
    applicant_id: str
    parcel_id: str
    planned_practices: List[Dict[str, Any]]
    self_reported_answers: Dict[str, Any]
    verified_answers: Optional[Dict[str, Any]]
    provisional_score: Optional[float]
    ranking_score: Optional[float]
    estimated_obligation_cents: Optional[int]
    funded_pool_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    program_id: str
    application_id: str
    applicant_id: str
    pool_id: str
    obligated_amount_cents: int
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractPracticeItem(TypedDict, total=False):
    id: str
    contract_id: str
    payment_schedule_rate_id: str
    practice_code: str
    planned_quantity: float
    unit: str
    applicable_rate_cents: int
    scheduled_amount_cents: int
    implementation_deadline: str
    certification_status: str
    certified_quantity: Optional[float]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    payment_status: str
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class PaymentRequest(TypedDict, total=False):
    id: str
    program_id: str
    contract_id: str
    practice_item_id: str
    documented_cost_cents: int
    documentation_refs: List[str]
    sequence_number: int
    sampled: bool
    computed_amount_cents: int
    advance_offset_cents: int
    disbursed_amount_cents: int
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvancePayment(TypedDict, total=False):
    id: str
    contract_id: str
    applicant_id: str
    practice_item_id: str
    issued_cents: int
    issued_at: str
    expenditure_due_date: str
    applied_cents: int
    returned_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractModification(TypedDict, total=False):
    id: str
    contract_id: str
    kind: str
    practice_item_id: Optional[str]
    new_deadline: Optional[str]
    new_practice_code: Optional[str]
    new_quantity: Optional[float]
    requested_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SpotCheck(TypedDict, total=False):
    id: str
    contract_id: str
    practice_item_id: str
    payment_request_id: Optional[str]
    inspector_user_id: str
    failure_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceObligation(TypedDict, total=False):
    id: str
    contract_id: str
    practice_item_id: str
    parcel_id: str
    practice_code: str
    start_date: str
    end_date: str
    reported_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoupmentDemand(TypedDict, total=False):
    id: str
    contract_id: str
    maintenance_obligation_id: Optional[str]
    advance_payment_id: Optional[str]
    payment_request_id: Optional[str]
    amount_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
