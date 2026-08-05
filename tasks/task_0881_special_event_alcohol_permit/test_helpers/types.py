"""Domain types: entity TypedDicts, status enums, role enum.

All names use the terminology of the Special-Event Alcohol Permit PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PERMIT_CLERK = "PermitClerk"
    AGENCY_REVIEWER = "AgencyReviewer"
    INSPECTOR = "Inspector"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISIONS_REQUESTED = "REVISIONS_REQUESTED"
    APPROVED = "APPROVED"
    PERMIT_ISSUED = "PERMIT_ISSUED"
    EVENT_COMPLETE = "EVENT_COMPLETE"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class FeeBasis(str, Enum):
    ESTIMATED = "ESTIMATED"
    RECONCILED = "RECONCILED"


class DepositStatus(str, Enum):
    NONE = "NONE"
    HELD = "HELD"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class ServerStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"


class TrainingProvider(str, Enum):
    TIPS = "TIPS"
    SERVSAFE_ALCOHOL = "SERVSAFE_ALCOHOL"
    STATE_APPROVED = "STATE_APPROVED"


class InsuranceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class SecurityPlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class InspectorAgency(str, Enum):
    POLICE = "POLICE"
    FIRE = "FIRE"
    ALCOHOL_BOARD = "ALCOHOL_BOARD"
    HEALTH = "HEALTH"


class ReviewAgency(str, Enum):
    POLICE = "POLICE"
    FIRE = "FIRE"
    ALCOHOL_BOARD = "ALCOHOL_BOARD"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"


class InspectionResult(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ViolationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class PenaltyVariant(str, Enum):
    STANDARD = "STANDARD"
    REPEAT = "REPEAT"


class ViolationStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class LedgerEntryType(str, Enum):
    FEE = "FEE"
    FEE_ADJUSTMENT = "FEE_ADJUSTMENT"
    DEPOSIT = "DEPOSIT"
    FINE = "FINE"
    FINE_REVERSAL = "FINE_REVERSAL"
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    DEPOSIT_REFUND = "DEPOSIT_REFUND"
    DEPOSIT_FORFEIT = "DEPOSIT_FORFEIT"


class ReportStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true carries id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Venue(TypedDict):
    id: str
    name: str
    address: str
    occupancy_limit: int
    indoor: bool
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    name: str
    badge_number: str
    agency: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    venue_id: str
    organizer_name: str
    event_name: str
    event_start: str
    event_end: str
    alcohol_service_hours: float
    expected_attendance: int
    requested_sales_limit_cents: int
    status: str
    permit_fee_cents: int
    fee_basis: str
    deposit_cents: int
    balance_due_cents: int
    deposit_status: str
    pending_review_count: int
    approved_review_count: int
    rejected_review_count: int
    total_review_count: int
    has_conditions: bool
    permit_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EventServer(TypedDict):
    id: str
    application_id: str
    full_name: str
    cert_number: str
    training_provider: str
    cert_issued_date: str
    cert_expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    application_id: str
    insurer_name: str
    coverage_cents: int
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SecurityPlan(TypedDict):
    id: str
    application_id: str
    planned_guard_count: int
    has_medical_staff: bool
    plan_summary: str
    required_guard_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgencyReview(TypedDict):
    id: str
    application_id: str
    agency: str
    status: str
    conditions: Optional[str]
    recorded_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    application_id: str
    inspector_id: str
    scheduled_start: str
    scheduled_end: str
    result: str
    recorded_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    inspection_id: str
    application_id: str
    severity: str
    description: str
    fine_cents: int
    penalty_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PostEventReport(TypedDict):
    id: str
    application_id: str
    actual_attendance: int
    gross_sales_cents: int
    incident_count: int
    reconciled_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# LedgerEntry is append-only (common_fields: false) — ONLY id + created_at.
class LedgerEntry(TypedDict):
    id: str
    application_id: str
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str
