"""Domain types: entity TypedDicts, status enums, role enum (Dermatology Practice API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    FRONT_DESK = "FrontDesk"
    PROVIDER = "Provider"
    PATH_LAB = "PathLab"
    BILLING_SPECIALIST = "BillingSpecialist"


# --- Status enums ---
class EncounterClinicalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    CLINICALLY_CLOSED = "CLINICALLY_CLOSED"
    CANCELLED = "CANCELLED"


class EncounterBillingStatus(str, Enum):
    BILLING_OPEN = "BILLING_OPEN"
    BILLING_FINALIZED = "BILLING_FINALIZED"
    BILLING_VOID = "BILLING_VOID"


class VisitType(str, Enum):
    MEDICAL = "MEDICAL"
    SKIN_CHECK = "SKIN_CHECK"
    COSMETIC = "COSMETIC"


class PayPath(str, Enum):
    INSURANCE = "INSURANCE"
    CASH = "CASH"


class BiopsyStatus(str, Enum):
    COLLECTED = "COLLECTED"
    AT_LAB = "AT_LAB"
    RESULTED = "RESULTED"
    SIGNED_OUT = "SIGNED_OUT"
    CANCELLED = "CANCELLED"


class BiopsyResult(str, Enum):
    BENIGN = "BENIGN"
    MALIGNANT = "MALIGNANT"
    INDETERMINATE = "INDETERMINATE"


class RoomKind(str, Enum):
    STANDARD = "STANDARD"
    MOHS_SUITE = "MOHS_SUITE"


class ProcedureKind(str, Enum):
    EXCISION = "EXCISION"
    MOHS = "MOHS"


class ProcedureBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PriorAuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class StepTherapyOutcome(str, Enum):
    FAILED = "FAILED"
    EFFECTIVE = "EFFECTIVE"
    NOT_TRIED = "NOT_TRIED"


class MembershipTier(str, Enum):
    SILVER = "SILVER"
    GOLD = "GOLD"


class CosmeticMembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class SourceKind(str, Enum):
    ENCOUNTER = "ENCOUNTER"
    COSMETIC_TREATMENT = "COSMETIC_TREATMENT"
    PROCEDURE_BOOKING = "PROCEDURE_BOOKING"


class ChargeKind(str, Enum):
    OFFICE_VISIT = "OFFICE_VISIT"
    PROCEDURE = "PROCEDURE"
    BIOLOGIC = "BIOLOGIC"
    COSMETIC = "COSMETIC"


class ChargeStatus(str, Enum):
    POSTED = "POSTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class RecallReason(str, Enum):
    ROUTINE_SKIN_CHECK = "ROUTINE_SKIN_CHECK"
    BIOPSY_FOLLOWUP = "BIOPSY_FOLLOWUP"


class RecallStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    DISMISSED = "DISMISSED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Provider(TypedDict):
    id: str
    full_name: str
    npi: str
    can_perform_mohs: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    name: str
    room_kind: str
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    has_active_insurance: bool
    insurance_coinsurance_rate: float
    insurance_deductible_remaining_cents: int
    last_skin_check_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    visit_type: str
    scheduled_at: str
    clinical_status: str
    billing_status: str
    pay_path: str
    open_biopsy_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, only id + created_at
class SkinExamPhoto(TypedDict):
    id: str
    encounter_id: str
    body_site: str
    mole_map_x: float
    mole_map_y: float
    image_ref: str
    created_at: str


class Biopsy(TypedDict):
    id: str
    encounter_id: str
    patient_id: str
    body_site: str
    status: str
    result: Optional[str]
    recall_months: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProcedureBooking(TypedDict):
    id: str
    room_id: str
    provider_id: str
    encounter_id: str
    procedure_kind: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    patient_id: str
    drug_name: str
    required_step_count: int
    list_price_cents: int
    status: str
    satisfied_step_count: int
    submission_round: int
    created_at: str
    updated_at: str
    version: int


class StepTherapyTrial(TypedDict):
    id: str
    prior_auth_id: str
    drug_name: str
    outcome: str
    created_at: str
    updated_at: str
    version: int


class CosmeticMembership(TypedDict):
    id: str
    patient_id: str
    tier: str
    purchased_unit_cents: int
    unit_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CosmeticTreatment(TypedDict):
    id: str
    encounter_id: str
    membership_id: str
    service_name: str
    list_price_cents: int
    redeemed_cents: int
    out_of_pocket_cents: int
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    patient_id: str
    encounter_id: str
    prior_auth_id: Optional[str]
    cosmetic_treatment_id: Optional[str]
    source_kind: str
    charge_kind: str
    billed_amount_cents: int
    insurer_allowed_cents: Optional[int]
    pay_path: str
    patient_responsibility_cents: int
    insurer_responsibility_cents: int
    deductible_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallReminder(TypedDict):
    id: str
    patient_id: str
    biopsy_id: Optional[str]
    reason: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
