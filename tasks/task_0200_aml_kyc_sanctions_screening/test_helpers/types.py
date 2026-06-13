"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the AML / KYC & Sanctions Screening API contract (PRD §2.4, §3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ANALYST = "Analyst"
    QUALITY_REVIEWER = "QualityReviewer"
    SYSTEM_FEED = "SystemFeed"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Status enums (PRD §3)
# --------------------------------------------------------------------------
class CustomerCddStatus(str, Enum):
    NEW = "NEW"
    RISK_RATED = "RISK_RATED"
    SCREENING_CLEARED = "SCREENING_CLEARED"
    APPROVED = "APPROVED"
    EDD_REQUIRED = "EDD_REQUIRED"
    REJECTED = "REJECTED"
    OFFBOARDED = "OFFBOARDED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PROHIBITED = "PROHIBITED"


class CustomerType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    LEGAL_ENTITY = "LEGAL_ENTITY"


class UboScreeningStatus(str, Enum):
    UNSCREENED = "UNSCREENED"
    CLEARED = "CLEARED"
    HIT = "HIT"


class RiskAssessmentVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ScreeningHitListType(str, Enum):
    OFAC_SDN = "OFAC_SDN"
    EU_SANCTIONS = "EU_SANCTIONS"
    PEP = "PEP"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"


class ScreeningHitDisposition(str, Enum):
    PENDING = "PENDING"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    ESCALATED = "ESCALATED"
    CONFIRMED = "CONFIRMED"


class AccountKycStatus(str, Enum):
    PENDING_KYC = "PENDING_KYC"
    KYC_OK = "KYC_OK"
    KYC_BLOCKED = "KYC_BLOCKED"


class AccountMonitoringStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    FROZEN = "FROZEN"


class TransactionDirection(str, Enum):
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"
    WIRE_IN = "WIRE_IN"
    WIRE_OUT = "WIRE_OUT"


class MonitoringRule(str, Enum):
    STRUCTURING = "STRUCTURING"
    RAPID_MOVEMENT = "RAPID_MOVEMENT"
    HIGH_RISK_GEO = "HIGH_RISK_GEO"
    CTR_THRESHOLD = "CTR_THRESHOLD"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    LINKED = "LINKED"
    DISMISSED = "DISMISSED"


class CasePriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CaseDisposition(str, Enum):
    TRIAGE = "TRIAGE"
    INVESTIGATING = "INVESTIGATING"
    SAR_RECOMMENDED = "SAR_RECOMMENDED"
    CTR_REQUIRED = "CTR_REQUIRED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    FILED = "FILED"


class FilingType(str, Enum):
    SAR = "SAR"
    CTR = "CTR"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LookbackReviewStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LookbackItemStatus(str, Enum):
    QUEUED = "QUEUED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    customer_type: str
    country_code: str
    date_of_birth: Optional[str]
    incorporation_date: Optional[str]
    is_pep_self_declared: bool
    cdd_status: str
    risk_rating: Optional[str]
    risk_score: Optional[float]
    edd_required: bool
    periodic_review_due_at: Optional[str]
    open_hit_count: int
    created_at: str
    updated_at: str
    version: int


class BeneficialOwner(TypedDict, total=False):
    id: str
    customer_id: str
    full_name: str
    ownership_pct: float
    country_code: str
    is_control_person: bool
    screening_status: str
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict, total=False):
    id: str
    customer_id: str
    variant: str
    geography_factor: int
    product_factor: int
    pep_factor: int
    adverse_media_factor: int
    total_score: float
    risk_band: str
    applied: bool
    created_at: str
    updated_at: str
    version: int


class ScreeningHit(TypedDict, total=False):
    id: str
    customer_id: str
    beneficial_owner_id: Optional[str]
    list_type: str
    matched_name: str
    match_score: float
    is_derogatory: bool
    disposition: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    customer_id: str
    account_ref: str
    opening_balance_cents: int
    kyc_status: str
    monitoring_status: str
    aggregate_cash_in_cents: int
    cumulative_credited_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at ONLY (no updated_at, no version)
class Transaction(TypedDict, total=False):
    id: str
    account_id: str
    direction: str
    amount_cents: int
    posted_at: str
    counterparty_country: str
    triggered_rule: Optional[str]
    created_at: str


class Alert(TypedDict, total=False):
    id: str
    account_id: str
    customer_id: str
    rule_code: str
    severity_score: float
    status: str
    case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    customer_id: str
    opened_by_user_id: str
    priority: str
    disposition: str
    linked_alert_count: int
    created_at: str
    updated_at: str
    version: int


class Filing(TypedDict, total=False):
    id: str
    case_id: str
    filing_type: str
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    deadline_at: str
    status: str
    acknowledgement_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LookbackReview(TypedDict, total=False):
    id: str
    reason: str
    window_start: str
    window_end: str
    status: str
    total_items: int
    cleared_items: int
    escalated_items: int
    created_at: str
    updated_at: str
    version: int


class LookbackReviewItem(TypedDict, total=False):
    id: str
    lookback_review_id: str
    account_id: str
    item_status: str
    generated_alert_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at ONLY
class AuditEvent(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor_user_id: str
    actor_role: str
    created_at: str
