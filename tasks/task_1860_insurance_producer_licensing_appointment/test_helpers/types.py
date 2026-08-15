"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2.4, 3.x)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PRODUCER = "Producer"
    LICENSING_COORDINATOR = "LicensingCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_OPS = "FinanceOps"
    CARRIER_ADMIN = "CarrierAdmin"


class ProducerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class LicenseClass(str, Enum):
    RESIDENT = "RESIDENT"
    NON_RESIDENT = "NON_RESIDENT"


class LineOfAuthority(str, Enum):
    LIFE = "LIFE"
    ACCIDENT_HEALTH = "ACCIDENT_HEALTH"
    PROPERTY = "PROPERTY"
    CASUALTY = "CASUALTY"
    PERSONAL_LINES = "PERSONAL_LINES"


class CECreditStatus(str, Enum):
    REPORTED = "REPORTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CECategory(str, Enum):
    GENERAL = "GENERAL"
    ETHICS = "ETHICS"


class AppointmentOrigin(str, Enum):
    STANDARD = "STANDARD"
    JIT = "JIT"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    JIT_PENDING = "JIT_PENDING"
    ACTIVE = "ACTIVE"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"
    LAPSED = "LAPSED"


class TerminationReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    FOR_CAUSE = "FOR_CAUSE"
    LICENSE_INACTIVE = "LICENSE_INACTIVE"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ISSUED = "ISSUED"
    RESCINDED = "RESCINDED"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    LICENSE_GAP = "LICENSE_GAP"
    APPOINTMENT_GAP = "APPOINTMENT_GAP"
    PRODUCER_SUSPENDED = "PRODUCER_SUSPENDED"


class CommissionVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class CommissionStatus(str, Enum):
    HELD = "HELD"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    FORFEITED = "FORFEITED"


class HoldReason(str, Enum):
    APPOINTMENT_PENDING = "APPOINTMENT_PENDING"
    UNLICENSED_AT_SALE = "UNLICENSED_AT_SALE"
    REGULATORY_HOLD = "REGULATORY_HOLD"


class ActionType(str, Enum):
    FINE = "FINE"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"
    PROBATION = "PROBATION"


class RegulatoryActionStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class InquiryStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    CLOSED = "CLOSED"


# All resources carry the common properties of PRD section 2.4:
# id, created_at, updated_at, version.

class Agency(TypedDict):
    id: str
    name: str
    resident_state_code: str
    created_at: str
    updated_at: str
    version: int


class Producer(TypedDict):
    id: str
    npn: str
    full_name: str
    resident_state_code: str
    agency_id: Optional[str]
    status: str
    ytd_issued_premium_cents: int
    commission_held_cents: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    producer_id: Optional[str]
    agency_id: Optional[str]
    state_code: str
    license_class: str
    lines_of_authority: List[str]
    status: str
    issue_date: str
    expiration_date: str
    ce_period_start: str
    ce_period_end: str
    ce_required_hours: float
    ce_ethics_required_hours: float
    ce_completed_hours: float
    ce_ethics_completed_hours: float
    renewed_count: int
    created_at: str
    updated_at: str
    version: int


class CECredit(TypedDict):
    id: str
    license_id: str
    provider_name: str
    course_title: str
    category: str
    credit_hours: float
    completed_on: str
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    producer_id: Optional[str]
    agency_id: Optional[str]
    state_code: str
    lines_of_authority: List[str]
    origin: str
    status: str
    effective_date: Optional[str]
    termination_date: Optional[str]
    termination_reason: Optional[str]
    termination_initiated_at: Optional[str]
    jit_filing_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PolicyApplication(TypedDict):
    id: str
    producer_id: str
    state_code: str
    line_of_authority: str
    applicant_name: str
    premium_cents: int
    status: str
    submitted_at: str
    decided_at: Optional[str]
    issued_at: Optional[str]
    eligibility_snapshot: str
    jit_appointment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionEntry(TypedDict):
    id: str
    application_id: str
    producer_id: str
    amount_cents: int
    amount_variant: str
    status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FineAllocation(TypedDict):
    application_id: str
    allocated_cents: int


class RegulatoryAction(TypedDict):
    id: str
    producer_id: Optional[str]
    agency_id: Optional[str]
    state_code: str
    action_type: str
    fine_amount_cents: Optional[int]
    effective_date: str
    status: str
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    fine_allocations: List[FineAllocation]
    created_at: str
    updated_at: str
    version: int


class RegulatoryInquiry(TypedDict):
    id: str
    producer_id: Optional[str]
    agency_id: Optional[str]
    state_code: str
    reference_number: str
    received_at: str
    response_due_at: str
    status: str
    response_text: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityView(TypedDict):
    eligibility_status: str
    license_id: Optional[str]
    appointment_id: Optional[str]
    via_agency: bool
