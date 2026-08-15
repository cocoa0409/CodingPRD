"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    SITE_COORDINATOR = "SiteCoordinator"
    PREPARER = "Preparer"
    QUALITY_REVIEWER = "QualityReviewer"
    SCREENER = "Screener"
    SPONSOR_ADMIN = "SponsorAdmin"


# ─── Status enums (PRD §3) ────────────────────────────

class SiteStatus(str, Enum):
    SETUP = "SETUP"
    CERTIFIED = "CERTIFIED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class VolunteerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TestType(str, Enum):
    ETHICS = "ETHICS"
    INTAKE_QR = "INTAKE_QR"
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"


class CertificationStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class IdentityStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class IdDocumentType(str, Enum):
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    PASSPORT = "PASSPORT"
    STATE_ID = "STATE_ID"
    MILITARY_ID = "MILITARY_ID"


class PreferredLanguage(str, Enum):
    EN = "EN"
    ES = "ES"
    OTHER = "OTHER"


class AppointmentPurpose(str, Enum):
    INTAKE = "INTAKE"
    PREPARATION = "PREPARATION"
    FOLLOW_UP = "FOLLOW_UP"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"
    MARRIED_SEPARATE = "MARRIED_SEPARATE"


class OutOfScopeFlag(str, Enum):
    RENTAL_INCOME = "RENTAL_INCOME"
    BUSINESS_WITH_LOSS = "BUSINESS_WITH_LOSS"
    FOREIGN_EARNED_INCOME = "FOREIGN_EARNED_INCOME"
    CASUALTY_LOSS = "CASUALTY_LOSS"


class IntakeDocument(str, Enum):
    PHOTO_ID = "PHOTO_ID"
    SSN_CARD = "SSN_CARD"
    W2 = "W2"
    FORM_1099 = "FORM_1099"
    PRIOR_YEAR_RETURN = "PRIOR_YEAR_RETURN"
    BANK_INFO = "BANK_INFO"


class RefundMethod(str, Enum):
    PAPER_CHECK = "PAPER_CHECK"
    DIRECT_DEPOSIT = "DIRECT_DEPOSIT"


class TaxReturnStatus(str, Enum):
    INTAKE_STARTED = "INTAKE_STARTED"
    IN_PREPARATION = "IN_PREPARATION"
    PENDING_QR = "PENDING_QR"
    QR_FAILED = "QR_FAILED"
    QR_PASSED = "QR_PASSED"
    TRANSMITTED = "TRANSMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    REFERRED = "REFERRED"
    WITHDRAWN = "WITHDRAWN"


class FirstAckOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AccountType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"


class FollowUpStatus(str, Enum):
    OPEN = "OPEN"
    CONTACTED = "CONTACTED"
    RESOLVED = "RESOLVED"


class FollowUpOutcome(str, Enum):
    CONTACTED = "CONTACTED"
    RESOLVED = "RESOLVED"


class SiteReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ServiceType(str, Enum):
    SAVINGS_ACCOUNT = "SAVINGS_ACCOUNT"
    CREDIT_COUNSELING = "CREDIT_COUNSELING"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    FINANCIAL_COACHING = "FINANCIAL_COACHING"


class ReferralStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ENROLLED = "ENROLLED"
    DECLINED = "DECLINED"
    VOID = "VOID"


class ReferralSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_ON_ACCEPT = "AUTO_ON_ACCEPT"


# ─── Entity TypedDicts ────────────────────────────────
# Every entity in this API carries the uniform system-managed properties
# id / created_at / updated_at / version (PRD §2.4).

class Site(TypedDict, total=False):
    id: str
    name: str
    sponsor_org: str
    station_capacity: int
    season_start: str
    season_end: str
    daily_open_hour: int
    daily_close_hour: int
    goal_returns: int
    status: str
    accepted_count: int
    goal_met: bool
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    site_id: str
    full_name: str
    email: str
    is_coordinator: bool
    status: str
    certified_test_types: List[str]
    active_case_count: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    volunteer_id: str
    test_type: str
    score: int
    tax_season: int
    passed: bool
    status: str
    attempt_number: int
    created_at: str
    updated_at: str
    version: int


class Taxpayer(TypedDict, total=False):
    id: str
    full_name: str
    ssn_token: str
    phone: str
    email: Optional[str]
    preferred_language: str
    identity_status: str
    id_document_type: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    site_id: str
    taxpayer_id: str
    volunteer_id: str
    purpose: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict, total=False):
    id: str
    appointment_id: str
    taxpayer_id: str
    site_id: str
    preparer_id: str
    reviewer_id: Optional[str]
    tax_year: int
    filing_status: str
    has_advanced_scope_items: bool
    out_of_scope_flags: List[str]
    status: str
    documents_received: List[str]
    interview_confirmed: bool
    wages_cents: int
    other_income_cents: int
    earned_income_cents: int
    withholding_reported_cents: int
    withholding_verified_cents: Optional[int]
    qualifying_children: int
    refund_method: str
    documents_complete: bool
    out_of_scope: bool
    out_of_scope_reasons: List[str]
    estimated_refund_cents: int
    final_refund_cents: Optional[int]
    savings_match_cents: int
    submission_count: int
    first_ack_outcome: Optional[str]
    qr_failure_count: int
    reached_preparation: bool
    transmitted_at: Optional[str]
    referral_reason: Optional[str]
    referral_destination: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundAllocation(TypedDict, total=False):
    id: str
    tax_return_id: str
    account_type: str
    routing_number: str
    account_number_mask: str
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class EfileRejection(TypedDict, total=False):
    id: str
    tax_return_id: str
    rejection_code: str
    rejection_text: str
    submission_number: int
    follow_up_status: str
    follow_up_due_at: str
    follow_up_overdue: bool
    contacted_at: Optional[str]
    resolved_at: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiteReport(TypedDict, total=False):
    id: str
    site_id: str
    period_start: str
    period_end: str
    status: str
    generated_at: str
    returns_prepared_count: int
    returns_transmitted_count: int
    returns_accepted_count: int
    returns_rejected_open_count: int
    returns_referred_count: int
    returns_withdrawn_count: int
    qr_rework_total: int
    first_pass_accepted_count: int
    first_pass_acceptance_rate_bp: Optional[int]
    final_resolution_rate_bp: Optional[int]
    financial_referrals_accepted_count: int
    savings_match_total_cents: int
    created_at: str
    updated_at: str
    version: int


class FinancialServiceReferral(TypedDict, total=False):
    id: str
    tax_return_id: str
    service_type: str
    status: str
    offered_by: Optional[str]
    source: str
    created_at: str
    updated_at: str
    version: int
