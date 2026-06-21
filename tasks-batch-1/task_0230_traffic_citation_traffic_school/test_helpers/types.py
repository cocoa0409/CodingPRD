"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are taken verbatim from the Traffic Citation
Payment & Traffic School PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    DRIVER = "Driver"
    COURT_CLERK = "CourtClerk"
    HEARING_OFFICER = "HearingOfficer"
    DMV_ADMIN = "DmvAdmin"


# --- Status enums ---
class CitationFinancialStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSESSED = "ASSESSED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class CitationAdjudicationStatus(str, Enum):
    NONE = "NONE"
    CONTESTED = "CONTESTED"
    DISMISSED = "DISMISSED"
    UPHELD = "UPHELD"


class CitationDisposition(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DriverLicenseStatus(str, Enum):
    VALID = "VALID"
    HELD = "HELD"
    SUSPENDED = "SUSPENDED"


class InstallmentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    MISSED = "MISSED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    CHECK = "CHECK"


class ContestRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    HEARING_SET = "HEARING_SET"
    CONTINUANCE = "CONTINUANCE"
    DISMISSED = "DISMISSED"
    UPHELD = "UPHELD"
    FTA = "FTA"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LicenseHoldType(str, Enum):
    FTA_HOLD = "FTA_HOLD"
    NONPAYMENT_HOLD = "NONPAYMENT_HOLD"
    POINT_SUSPENSION = "POINT_SUSPENSION"


class LicenseHoldStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"


class CollectionsReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    RECALLED = "RECALLED"


class WarrantReason(str, Enum):
    FTA_HEARING = "FTA_HEARING"
    FTA_APPEAR = "FTA_APPEAR"


class WarrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUASHED = "QUASHED"


class PointLedgerEntryState(str, Enum):
    ACTIVE = "ACTIVE"
    MASKED = "MASKED"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ---
class Jurisdiction(TypedDict):
    id: str
    name: str
    state_code: str
    base_court_fee_cents: int
    surcharge_pct: float
    late_penalty_cents: int
    installment_setup_fee_cents: int
    min_installment_cents: int
    collections_age_days: int
    collections_fee_pct: float
    traffic_school_fee_cents: int
    school_eligible_max_points: int
    school_cooldown_months: int
    point_suspension_threshold: int
    point_window_months: int
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    jurisdiction_id: str
    license_number: str
    full_name: str
    license_status: str
    point_balance: int
    fta_warrant_active: bool
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    driver_id: str
    citation_number: str
    issued_at: str
    appear_by: str
    base_fine_cents: int
    assessed_total_cents: int
    penalty_cents: int
    amount_paid_cents: int
    balance_cents: int
    financial_status: str
    adjudication_status: str
    disposition: str
    late_penalty_applied: bool
    collections_referred: bool
    created_at: str
    updated_at: str
    version: int


class CitationCharge(TypedDict):
    id: str
    citation_id: str
    violation_code: str
    description: str
    base_fine_cents: int
    points: int
    created_at: str
    updated_at: str
    version: int


class InstallmentPlan(TypedDict):
    id: str
    citation_id: str
    term_count: int
    first_due_at: str
    principal_cents: int
    installment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    installment_plan_id: str
    sequence_no: int
    due_at: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    citation_id: str
    amount_cents: int
    method: str
    installment_id: Optional[str]
    status: str
    posted_at: str
    created_at: str
    updated_at: str
    version: int


class ContestRequest(TypedDict):
    id: str
    citation_id: str
    grounds: str
    hearing_at: Optional[str]
    continuance_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrafficSchoolEnrollment(TypedDict):
    id: str
    citation_id: str
    driver_id: str
    eligible_points: int
    completion_due_at: str
    points_reduced: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseHold(TypedDict):
    id: str
    driver_id: str
    citation_id: Optional[str]
    hold_type: str
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CollectionsReferral(TypedDict):
    id: str
    citation_id: str
    outstanding_at_referral_cents: int
    collections_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Warrant(TypedDict):
    id: str
    citation_id: str
    driver_id: str
    reason: str
    status: str
    quashed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-and-mask audit record: id + created_at only
class PointLedgerEntry(TypedDict):
    id: str
    driver_id: str
    citation_id: str
    points: int
    effective_at: str
    state: str
    created_at: str
