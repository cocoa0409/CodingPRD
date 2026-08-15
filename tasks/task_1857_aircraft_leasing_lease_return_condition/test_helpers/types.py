"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class AircraftStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LEASE = "ON_LEASE"
    IN_TRANSITION = "IN_TRANSITION"
    REPOSSESSED = "REPOSSESSED"


class LesseeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CreditTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETURN_INITIATED = "RETURN_INITIATED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    DEFAULTED = "DEFAULTED"
    TERMINATED = "TERMINATED"


class AccrualBasis(str, Enum):
    ACTUAL = "ACTUAL"
    MINIMUM_GUARANTEE = "MINIMUM_GUARANTEE"


class UtilizationReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class ReserveClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class DocType(str, Enum):
    BIRTH_RECORD = "BIRTH_RECORD"
    AIRWORTHINESS_CERT = "AIRWORTHINESS_CERT"
    ENGINE_LOG = "ENGINE_LOG"
    LLP_STATUS = "LLP_STATUS"
    OTHER = "OTHER"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ReturnCaseStatus(str, Enum):
    OPEN = "OPEN"
    RECORDS_VERIFIED = "RECORDS_VERIFIED"
    INSPECTION = "INSPECTION"
    NEGOTIATION = "NEGOTIATION"
    AGREED = "AGREED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ItemCode(str, Enum):
    AIRFRAME = "AIRFRAME"
    ENGINE = "ENGINE"
    INTERIOR = "INTERIOR"
    PAINT = "PAINT"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class ChecklistItemStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    RECTIFIED = "RECTIFIED"
    WAIVED = "WAIVED"
    COMPENSATED = "COMPENSATED"


class ProposerSide(str, Enum):
    LESSOR = "LESSOR"
    LESSEE = "LESSEE"


class RequestType(str, Enum):
    NOVATION = "NOVATION"
    SUBLEASE = "SUBLEASE"


class NovationRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CREDIT_APPROVED = "CREDIT_APPROVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DefaultCaseStatus(str, Enum):
    DECLARED = "DECLARED"
    CURED = "CURED"
    REPOSSESSION_AUTHORIZED = "REPOSSESSION_AUTHORIZED"
    REPOSSESSED = "REPOSSESSED"


class TransitionSlotStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class UserRole(str, Enum):
    LESSOR_ADMIN = "LessorAdmin"
    LESSEE_REP = "LesseeRep"
    TECH_INSPECTOR = "TechInspector"
    CREDIT_OFFICER = "CreditOfficer"
    LEGAL_APPROVER = "LegalApprover"
    FINANCE_MANAGER = "FinanceManager"


class Aircraft(TypedDict, total=False):
    id: str
    msn: str
    model: str
    manufacture_date: str
    status: str
    total_flight_hours: float
    total_flight_cycles: int
    created_at: str
    updated_at: str
    version: int


class Lessee(TypedDict, total=False):
    id: str
    legal_name: str
    credit_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    aircraft_id: str
    lessee_id: str
    start_date: str
    end_date: str
    monthly_rent_cents: int
    reserve_rate_per_fh_cents: int
    reserve_rate_per_fc_cents: int
    monthly_hour_cap: int
    accrual_basis: str
    minimum_monthly_hours: float
    status: str
    reserve_accrued_cents: int
    reserve_reimbursed_cents: int
    reserve_forfeited_cents: int
    reserve_balance_cents: int
    approved_sublessee_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilizationReport(TypedDict, total=False):
    id: str
    lease_id: str
    period_month: str
    flight_hours: float
    flight_cycles: int
    status: str
    dispute_reason: Optional[str]
    posted_accrual_cents: int
    created_at: str
    updated_at: str
    version: int


class ReserveClaim(TypedDict, total=False):
    id: str
    lease_id: str
    maintenance_event_ref: str
    claimed_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AircraftDocument(TypedDict, total=False):
    id: str
    aircraft_id: str
    doc_type: str
    doc_reference: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnCase(TypedDict, total=False):
    id: str
    lease_id: str
    status: str
    round_count: int
    current_proposal_cents: Optional[int]
    current_proposer_side: Optional[str]
    reinspection_count: int
    provisional_estimate_cents: int
    agreed_total_cents: Optional[int]
    reserve_applied_cents: Optional[int]
    settlement_cash_due_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ChecklistItem(TypedDict, total=False):
    id: str
    return_case_id: str
    item_code: str
    severity: str
    status: str
    rectification_cost_estimate_cents: Optional[int]
    inspected_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionBooking(TypedDict, total=False):
    # Scheduling record: carries id and created_at only; no updated_at/version.
    id: str
    return_case_id: str
    inspector_id: str
    booking_date: str
    created_at: str


class NovationRequest(TypedDict, total=False):
    id: str
    lease_id: str
    request_type: str
    proposed_lessee_id: str
    status: str
    credit_reviewed_by: Optional[str]
    legal_reviewed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DefaultCase(TypedDict, total=False):
    id: str
    lease_id: str
    reason: str
    cure_period_days: int
    declared_at: str
    cure_deadline: str
    declared_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransitionSlot(TypedDict, total=False):
    id: str
    aircraft_id: str
    window_start: str
    window_end: str
    next_operator_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
