"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List


class UserRole(str, Enum):
    LANDLORD = "Landlord"
    LEASEHOLDER = "Leaseholder"
    APPLICANT = "Applicant"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class SignerRole(str, Enum):
    LANDLORD = "LANDLORD"
    LEASEHOLDER = "LEASEHOLDER"
    APPLICANT = "APPLICANT"


class LeaseStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ListingType(str, Enum):
    SUBLET = "SUBLET"
    TAKEOVER = "TAKEOVER"


class ScreeningPolicy(str, Enum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    INFO_REQUESTED = "INFO_REQUESTED"
    SCREENED = "SCREENED"
    MATCHED = "MATCHED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class ScreeningResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURES = "PENDING_SIGNATURES"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    VOID = "VOID"
    TERMINATED = "TERMINATED"


class AgreementType(str, Enum):
    SUBLET = "SUBLET"
    TAKEOVER = "TAKEOVER"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    FUNDED = "FUNDED"
    HANDED_OFF = "HANDED_OFF"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_LEASEHOLDER = "RESOLVED_LEASEHOLDER"
    RESOLVED_APPLICANT = "RESOLVED_APPLICANT"
    RESOLVED_SPLIT = "RESOLVED_SPLIT"
    DISMISSED = "DISMISSED"


class DisputeOutcome(str, Enum):
    RESOLVED_LEASEHOLDER = "RESOLVED_LEASEHOLDER"
    RESOLVED_APPLICANT = "RESOLVED_APPLICANT"
    RESOLVED_SPLIT = "RESOLVED_SPLIT"
    DISMISSED = "DISMISSED"


class FeeType(str, Enum):
    PLATFORM = "PLATFORM"
    SCREENING = "SCREENING"
    CANCELLATION = "CANCELLATION"
    LATE = "LATE"


class FeeStatus(str, Enum):
    PENDING = "PENDING"
    CHARGED = "CHARGED"
    WAIVED = "WAIVED"
    REFUNDED = "REFUNDED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Landlord(TypedDict):
    id: str
    name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Leaseholder(TypedDict):
    id: str
    name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    name: str
    email: str
    annual_income_cents: int
    monthly_debt_cents: int
    credit_score: int
    active_application_count: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    landlord_id: str
    leaseholder_id: str
    monthly_rent_cents: int
    security_deposit_cents: int
    term_start_date: str
    term_end_date: str
    allows_sublet: bool
    allows_assignment: bool
    status: str
    active_occupancy_count: int
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    lease_id: str
    listing_type: str
    asking_rent_cents: int
    available_from: str
    available_to: str
    min_term_months: int
    screening_policy: str
    landlord_approval_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    listing_id: str
    applicant_id: str
    proposed_move_in_date: str
    proposed_move_out_date: str
    status: str
    screening_result: str
    created_at: str
    updated_at: str
    version: int


class ScreeningReport(TypedDict):
    id: str
    application_id: str
    credit_score: int
    income_verified: bool
    applicant_annual_income_cents: int
    effective_monthly_rent_cents: int
    screening_policy: str
    affordability_ratio: float
    income_multiple: float
    qualification_result: str
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict):
    id: str
    application_id: str
    listing_id: str
    lease_id: str
    agreement_type: str
    occupancy_start_date: str
    occupancy_end_date: str
    required_signer_roles: List[str]
    collected_signer_roles: List[str]
    is_fully_signed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — Signature is immutable: only id + created_at
class Signature(TypedDict):
    id: str
    agreement_id: str
    signer_role: str
    signer_id: str
    signed_at: str
    created_at: str


class Settlement(TypedDict):
    id: str
    agreement_id: str
    agreement_type: str
    deposit_amount_cents: int
    base_monthly_rent_cents: int
    prorated_first_rent_cents: int
    final_prorated_first_rent_cents: int
    last_month_rent_cents: int
    platform_fee_cents: int
    total_move_in_cents: int
    funded_amount_cents: int
    deposit_held_cents: int
    handoff_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HandoffAppointment(TypedDict):
    id: str
    agreement_id: str
    landlord_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    agreement_id: str
    raised_by: str
    reason: str
    status: str
    outcome: str
    resolution_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Fee(TypedDict):
    id: str
    agreement_id: str
    fee_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
