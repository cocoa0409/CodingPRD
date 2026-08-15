"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SERVICING_ADMIN = "ServicingAdmin"
    PROPERTY_SOLUTIONS_SPECIALIST = "PropertySolutionsSpecialist"
    WORKOUT_MANAGER = "WorkoutManager"
    TITLE_OFFICER = "TitleOfficer"
    BORROWER = "Borrower"
    INSPECTOR = "Inspector"
    DISBURSEMENT_OFFICER = "DisbursementOfficer"
    LEGAL_COUNSEL = "LegalCounsel"


class LoanStatus(str, Enum):
    ACTIVE_DELINQUENT = "ACTIVE_DELINQUENT"
    WORKOUT_IN_PROGRESS = "WORKOUT_IN_PROGRESS"
    DEED_IN_LIEU_COMPLETED = "DEED_IN_LIEU_COMPLETED"
    FORECLOSURE_PROCEEDING = "FORECLOSURE_PROCEEDING"


class ForeclosureReferralStatus(str, Enum):
    NONE = "NONE"
    REFERRED = "REFERRED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class HardshipType(str, Enum):
    INVOLUNTARY_UNEMPLOYMENT = "INVOLUNTARY_UNEMPLOYMENT"
    MEDICAL = "MEDICAL"
    DIVORCE = "DIVORCE"
    NONE = "NONE"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class OccupancyType(str, Enum):
    OWNER_OCCUPIED = "OWNER_OCCUPIED"
    TENANT_OCCUPIED = "TENANT_OCCUPIED"
    SECOND_HOME = "SECOND_HOME"


class ConditionStandard(str, Enum):
    BROOM_CLEAN = "BROOM_CLEAN"


class ProgramType(str, Enum):
    DEED_IN_LIEU = "DEED_IN_LIEU"
    CASH_FOR_KEYS = "CASH_FOR_KEYS"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    ELIGIBILITY_REVIEW = "ELIGIBILITY_REVIEW"
    MARKETING_PERIOD = "MARKETING_PERIOD"
    TITLE_REVIEW = "TITLE_REVIEW"
    TERMS_NEGOTIATION = "TERMS_NEGOTIATION"
    AGREEMENT_ACTIVE = "AGREEMENT_ACTIVE"
    VACATE_PENDING = "VACATE_PENDING"
    HANDOVER_INSPECTION = "HANDOVER_INSPECTION"
    DISBURSEMENT_PENDING = "DISBURSEMENT_PENDING"
    RECORDING_PENDING = "RECORDING_PENDING"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    HOLDOVER_ESCALATED = "HOLDOVER_ESCALATED"
    EVICTION_IN_PROGRESS = "EVICTION_IN_PROGRESS"
    CLOSED_EVICTED = "CLOSED_EVICTED"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class TitleCommitmentStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    CLEARED = "CLEARED"


class LienStatus(str, Enum):
    UNRELEASED = "UNRELEASED"
    RELEASED = "RELEASED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    SUPERSEDED = "SUPERSEDED"


class ConditionBasis(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    INSPECTED = "INSPECTED"


class AppointmentType(str, Enum):
    HANDOVER = "HANDOVER"
    RE_INSPECTION = "RE_INSPECTION"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_ACCESS = "NO_ACCESS"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class ReportResult(str, Enum):
    FAILED = "FAILED"
    PASSED_WITH_DEDUCTIONS = "PASSED_WITH_DEDUCTIONS"
    PASSED = "PASSED"


class ItemCode(str, Enum):
    CLEANLINESS_FAIL = "CLEANLINESS_FAIL"
    DEBRIS_REMOVAL = "DEBRIS_REMOVAL"
    APPLIANCE_REMOVED = "APPLIANCE_REMOVED"
    FIXTURE_DAMAGE = "FIXTURE_DAMAGE"
    STRUCTURAL_DAMAGE = "STRUCTURAL_DAMAGE"


class Severity(str, Enum):
    STANDARD = "STANDARD"
    MATERIAL = "MATERIAL"


class DisbursementStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"
    CLAWED_BACK = "CLAWED_BACK"


class DisbursementPurpose(str, Enum):
    RELOCATION_ASSISTANCE = "RELOCATION_ASSISTANCE"


class WaiverStatus(str, Enum):
    DRAFT = "DRAFT"
    DOCUMENTED = "DOCUMENTED"
    EXECUTED = "EXECUTED"
    RESCINDED = "RESCINDED"


class RecordingStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"


class EvictionStatus(str, Enum):
    ESCALATED = "ESCALATED"
    FILED = "FILED"
    WRIT_ISSUED = "WRIT_ISSUED"
    EVICTED = "EVICTED"
    DISMISSED = "DISMISSED"


class EvictionReason(str, Enum):
    HOLDOVER = "HOLDOVER"


class DismissalReason(str, Enum):
    OCCUPANT_VACATED = "OCCUPANT_VACATED"
    OTHER = "OTHER"


class Loan(TypedDict, total=False):
    id: str
    loan_number: str
    unpaid_principal_balance_cents: int
    accrued_interest_cents: int
    escrow_advances_cents: int
    foreclosure_fees_cents: int
    note_annual_rate: float
    per_diem_interest_cents: int
    fair_market_value_cents: int
    delinquency_days: int
    foreclosure_referral_status: str
    status: str
    deficiency_balance_cents: int
    servicing_system_synced: bool
    created_at: str
    updated_at: str
    version: int


class Borrower(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    hardship_type: str
    self_reported_condition_grade: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    loan_id: str
    address_line: str
    county: str
    state_code: str
    occupancy_type: str
    required_condition_standard: str
    created_at: str
    updated_at: str
    version: int


class WorkoutCase(TypedDict, total=False):
    id: str
    loan_id: str
    borrower_id: str
    program_type: str
    status: str
    assigned_specialist_id: str
    marketing_exception_granted: bool
    marketing_exception_reason: Optional[str]
    total_disbursed_cents: int
    remaining_assistance_cents: Optional[int]
    handover_date: Optional[str]
    keys_returned: bool
    created_at: str
    updated_at: str
    version: int


class MarketingListing(TypedDict, total=False):
    id: str
    case_id: str
    list_date: str
    list_price_cents: int
    status: str
    creditable_days: int
    created_at: str
    updated_at: str
    version: int


class ListingSuspension(TypedDict, total=False):
    id: str
    listing_id: str
    started_at: str
    ended_at: Optional[str]
    reason: str
    created_at: str
    updated_at: str
    version: int


class TitleCommitment(TypedDict, total=False):
    id: str
    case_id: str
    status: str
    vested_owner_name: Optional[str]
    unreleased_lien_count: int
    created_at: str
    updated_at: str
    version: int


class JuniorLien(TypedDict, total=False):
    id: str
    title_commitment_id: str
    lienholder_name: str
    amount_cents: int
    position: int
    status: str
    settlement_amount_cents: Optional[int]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementAgreement(TypedDict, total=False):
    id: str
    case_id: str
    vacate_date: str
    provisional_assistance_cents: int
    final_assistance_cents: Optional[int]
    condition_basis: str
    status: str
    offer_expires_at: Optional[str]
    round_number: int
    created_by_specialist_id: str
    created_at: str
    updated_at: str
    version: int


class InspectionAppointment(TypedDict, total=False):
    id: str
    case_id: str
    inspector_id: str
    appointment_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionReport(TypedDict, total=False):
    id: str
    appointment_id: str
    case_id: str
    status: str
    broom_clean_verified: bool
    keys_returned_count: int
    line_items: List[Dict[str, Any]]
    total_deduction_cents: int
    result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    case_id: str
    agreement_id: str
    amount_cents: int
    purpose: str
    status: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeficiencyWaiver(TypedDict, total=False):
    id: str
    case_id: str
    loan_id: str
    status: str
    projected_waiver_cents: int
    final_waiver_cents: Optional[int]
    pre_waiver_deficiency_cents: Optional[int]
    waived_amount_cents: int
    document_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeedRecording(TypedDict, total=False):
    id: str
    case_id: str
    county: str
    instrument_number: Optional[str]
    status: str
    recorded_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvictionCase(TypedDict, total=False):
    id: str
    case_id: str
    reason: str
    status: str
    court_reference: Optional[str]
    filed_at: Optional[str]
    dismissal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
