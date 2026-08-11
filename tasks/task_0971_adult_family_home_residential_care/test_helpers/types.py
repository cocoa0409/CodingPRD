"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class HomeStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    LICENSED = "LICENSED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ResidentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    APPLICANT = "APPLICANT"
    ADMITTED = "ADMITTED"
    DISCHARGED = "DISCHARGED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class AdmissionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MedicationOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class CaregiverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ComplianceCaseStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"
    CLOSED = "CLOSED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class PayerType(str, Enum):
    PRIVATE_PAY = "PRIVATE_PAY"
    MEDICAID = "MEDICAID"


class IncidentType(str, Enum):
    FALL = "FALL"
    MED_ERROR = "MED_ERROR"
    ELOPEMENT = "ELOPEMENT"
    ABUSE_ALLEGATION = "ABUSE_ALLEGATION"
    INJURY = "INJURY"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class MedOutcome(str, Enum):
    GIVEN = "GIVEN"
    REFUSED = "REFUSED"
    HELD = "HELD"
    SELF_ADMINISTERED = "SELF_ADMINISTERED"


class AdlType(str, Enum):
    BATHING = "BATHING"
    DRESSING = "DRESSING"
    GROOMING = "GROOMING"
    TOILETING = "TOILETING"
    TRANSFERRING = "TRANSFERRING"
    EATING = "EATING"


class AssistanceLevel(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    SUPERVISION = "SUPERVISION"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class OvernightMode(str, Enum):
    AWAKE = "AWAKE"
    ASLEEP = "ASLEEP"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CHECK = "CHECK"
    ACH = "ACH"
    CARD = "CARD"
    MEDICAID_REMIT = "MEDICAID_REMIT"


class DischargeReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    HOSPITALIZATION = "HOSPITALIZATION"
    LEVEL_OF_CARE_EXCEEDED = "LEVEL_OF_CARE_EXCEEDED"
    NONPAYMENT = "NONPAYMENT"
    DECEASED = "DECEASED"


class UserRole(str, Enum):
    PROVIDER = "Provider"
    NURSE = "Nurse"
    CAREGIVER = "CaregiverRole"


class Home(TypedDict, total=False):
    id: str
    license_number: str
    name: str
    licensed_bed_capacity: int
    timezone: str
    status: str
    open_case_count: int
    current_census: int
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict, total=False):
    id: str
    home_id: str
    label: str
    medicaid_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict, total=False):
    id: str
    home_id: str
    full_name: str
    date_of_birth: str
    payer_type: str
    status: str
    admitted_at: Optional[str]
    discharged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    resident_id: str
    assessed_at: str
    nursing_hours_per_week: float
    adl_dependency_score: int
    care_plan: Any
    status: str
    created_at: str
    updated_at: str
    version: int


class Admission(TypedDict, total=False):
    id: str
    resident_id: str
    bed_id: str
    assessment_id: str
    expected_admission_date: str
    status: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicationOrder(TypedDict, total=False):
    id: str
    resident_id: str
    drug_name: str
    dose: str
    schedule_times: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false): id + created_at only, no updated_at/version
class MedicationLog(TypedDict, total=False):
    id: str
    resident_id: str
    order_id: str
    administered_at: str
    outcome: str
    caregiver_id: str
    note: Optional[str]
    created_at: str


# Append-only (common_fields: false)
class ADLLog(TypedDict, total=False):
    id: str
    resident_id: str
    adl_type: str
    assistance_level: str
    performed_at: str
    caregiver_id: str
    created_at: str


class Caregiver(TypedDict, total=False):
    id: str
    home_id: str
    full_name: str
    credential_id: str
    awake_overnight_qualified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    home_id: str
    caregiver_id: str
    start_at: str
    end_at: str
    overnight_mode: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    resident_id: str
    incident_type: str
    severity: str
    occurred_at: str
    reported_at: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceCase(TypedDict, total=False):
    id: str
    home_id: str
    incident_id: str
    citation_code: Optional[str]
    correction_plan_due_at: Optional[str]
    correction_plan_submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    resident_id: str
    period_start: str
    period_end: str
    payer_type_snapshot: str
    line_items: List[Any]
    subtotal_cents: int
    late_fee_cents: int
    total_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false)
class Payment(TypedDict, total=False):
    id: str
    resident_id: str
    invoice_id: str
    amount_cents: int
    method: str
    received_at: str
    created_at: str


class RateSchedule(TypedDict, total=False):
    id: str
    home_id: str
    payer_type: str
    room_and_board_daily_cents: int
    care_low_daily_cents: int
    care_medium_daily_cents: int
    care_high_daily_cents: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false)
class DischargeRecord(TypedDict, total=False):
    id: str
    resident_id: str
    reason: str
    notice_days: int
    discharged_at: str
    refund_amount_cents: int
    created_at: str
