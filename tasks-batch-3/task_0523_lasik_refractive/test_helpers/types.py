"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    SURGEON = "Surgeon"
    OPTOMETRIST = "Optometrist"
    PATIENT = "Patient"
    ANONYMOUS = "Anonymous"


# --- Status enums ---
class PackageTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    LIFETIME = "LIFETIME"


class RefundMode(str, Enum):
    PRO_RATA = "PRO_RATA"
    DEPOSIT_FORFEIT = "DEPOSIT_FORFEIT"


class SuiteStatus(str, Enum):
    OPEN = "OPEN"
    MAINTENANCE = "MAINTENANCE"


class PatientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    CANDIDATE = "CANDIDATE"
    INELIGIBLE = "INELIGIBLE"
    OPERATED = "OPERATED"


class ScreeningStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    THIN_BED = "THIN_BED"
    HIGH_K = "HIGH_K"
    HIGH_ERROR = "HIGH_ERROR"
    UNDERAGE = "UNDERAGE"


class ClinicalStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    CONSENTED = "CONSENTED"
    OPERATED = "OPERATED"
    HEALED = "HEALED"
    CANCELLED = "CANCELLED"


class FinancialStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class FinancingStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ConsentStatus(str, Enum):
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class EnhancementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RE_SCREENING = "RE_SCREENING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FULFILLED = "FULFILLED"


class BookingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class RefundClaimStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REJECTED = "REJECTED"


# --- Entity TypedDicts ---

# TreatmentPackage: configuration record — carries ONLY id + created_at
# (no updated_at, no version).
class TreatmentPackage(TypedDict):
    id: str
    created_at: str
    tier: str
    base_price_cents: int
    deposit_cents: int
    enhancement_window_days: int
    outcome_guarantee_uncorrected_va: float
    refund_mode: str
    active: bool


# All entities below carry id + created_at + updated_at + version.
class LaserSuite(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    turnaround_buffer_minutes: int
    daily_case_cap: int
    status: str


class Surgeon(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    max_daily_cases: int
    accepting: bool


class Optometrist(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str


class Patient(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    date_of_birth: str
    co_managing_optometrist_id: Optional[str]
    status: str


class CandidacyScreening(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    performed_by_optometrist_id: str
    corneal_thickness_um: int
    topography_k_max: float
    refractive_error_diopters: float
    ablation_depth_um: Optional[int]
    residual_stromal_bed_um: Optional[int]
    status: str
    rejection_reason: Optional[str]


class SurgeryCase(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    screening_id: str
    package_id: str
    clinical_status: str
    financial_status: str
    surgery_completed_at: Optional[str]
    final_uncorrected_va: Optional[float]


class FinancingPlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    case_id: str
    down_payment_cents: int
    term_months: int
    apr_bps: int
    monthly_installment_cents: int
    amount_settled_cents: int
    status: str


class ConsentForm(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    case_id: str
    drops_regimen_started: bool
    signed_by_patient_id: str
    signed_at: str
    status: str


class EnhancementRequest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    origin_case_id: str
    patient_id: str
    reason: str
    re_screening_id: Optional[str]
    status: str
    within_window: bool


class SuiteBooking(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    case_id: str
    suite_id: str
    surgeon_id: str
    slot_start: str
    slot_end: str
    status: str


class RefundClaim(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    case_id: str
    measured_uncorrected_va: float
    refund_mode: str
    refund_amount_cents: int
    status: str
