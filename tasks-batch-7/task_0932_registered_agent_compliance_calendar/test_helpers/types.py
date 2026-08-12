"""Domain types for the Registered-Agent & Compliance-Calendar API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FILING_AGENT = "FilingAgent"
    SOP_HANDLER = "SopHandler"
    CLIENT_CONTACT = "ClientContact"


class DelinquencyStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE_SOON = "DUE_SOON"
    IN_GRACE = "IN_GRACE"
    DELINQUENT = "DELINQUENT"
    ADMIN_DISSOLVED = "ADMIN_DISSOLVED"


class EntityType(str, Enum):
    LLC = "LLC"
    CORP = "CORP"
    LP = "LP"
    LLP = "LLP"
    NONPROFIT = "NONPROFIT"


class BoiExemptClass(str, Enum):
    NONE = "NONE"
    LARGE_OPERATING = "LARGE_OPERATING"
    PUBLICLY_TRADED = "PUBLICLY_TRADED"
    BANK = "BANK"
    TAX_EXEMPT = "TAX_EXEMPT"


class LifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    WINDING_DOWN = "WINDING_DOWN"
    DISSOLVED = "DISSOLVED"


class BoiStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_INITIAL = "PENDING_INITIAL"
    FILED = "FILED"
    UPDATE_DUE = "UPDATE_DUE"
    DELINQUENT = "DELINQUENT"


class AnnualReportBasis(str, Enum):
    ANNIVERSARY_MONTH_DAY = "ANNIVERSARY_MONTH_DAY"
    FIXED_CALENDAR_DATE = "FIXED_CALENDAR_DATE"
    FISCAL_YEAR_END_OFFSET = "FISCAL_YEAR_END_OFFSET"


class FranchiseTaxBasis(str, Enum):
    FLAT = "FLAT"
    AUTHORIZED_SHARES_TIERS = "AUTHORIZED_SHARES_TIERS"
    ASSUMED_PAR_VALUE = "ASSUMED_PAR_VALUE"
    GROSS_RECEIPTS_BRACKETS = "GROSS_RECEIPTS_BRACKETS"


class GraceBasis(str, Enum):
    CALENDAR_DAYS = "CALENDAR_DAYS"
    BUSINESS_DAYS = "BUSINESS_DAYS"


class LateFeeStyle(str, Enum):
    FLAT = "FLAT"
    PER_MONTH = "PER_MONTH"
    PERCENT_CAPPED = "PERCENT_CAPPED"


class NameClearanceResult(str, Enum):
    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    CONFLICT = "CONFLICT"


class RegistrationKind(str, Enum):
    HOME = "HOME"
    FOREIGN = "FOREIGN"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    ADMIN_DISSOLVED = "ADMIN_DISSOLVED"
    WITHDRAWN = "WITHDRAWN"
    TERMINATED = "TERMINATED"
    CLOSED_PERMANENT = "CLOSED_PERMANENT"


class AppointmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPOINTED = "APPOINTED"
    RESIGNATION_NOTICED = "RESIGNATION_NOTICED"
    RESIGNED = "RESIGNED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"
    REJECTED = "REJECTED"


class ObligationType(str, Enum):
    ANNUAL_REPORT = "ANNUAL_REPORT"
    FRANCHISE_TAX = "FRANCHISE_TAX"
    BOI_INITIAL = "BOI_INITIAL"
    BOI_UPDATE = "BOI_UPDATE"
    FINAL_REPORT = "FINAL_REPORT"


class ObligationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE_SOON = "DUE_SOON"
    IN_GRACE = "IN_GRACE"
    DELINQUENT = "DELINQUENT"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"


class ReminderOffsetLabel(str, Enum):
    T_MINUS_90 = "T_MINUS_90"
    T_MINUS_60 = "T_MINUS_60"
    T_MINUS_30 = "T_MINUS_30"
    T_MINUS_7 = "T_MINUS_7"
    OVERDUE = "OVERDUE"


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    SUPPRESSED = "SUPPRESSED"
    REARMED = "REARMED"


class FilingKind(str, Enum):
    ANNUAL_REPORT = "ANNUAL_REPORT"
    FRANCHISE_TAX = "FRANCHISE_TAX"
    FOREIGN_QUALIFICATION = "FOREIGN_QUALIFICATION"
    WITHDRAWAL = "WITHDRAWAL"
    DISSOLUTION = "DISSOLUTION"
    REINSTATEMENT = "REINSTATEMENT"
    FINAL_REPORT = "FINAL_REPORT"


class ExpediteTier(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    RUSH = "RUSH"
    SAME_DAY = "SAME_DAY"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ABANDONED = "ABANDONED"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class SopClass(str, Enum):
    ORDINARY = "ORDINARY"
    LITIGATION = "LITIGATION"


class SopStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCANNED = "SCANNED"
    FORWARDED = "FORWARDED"
    ESCALATED = "ESCALATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED_NOT_OUR_ENTITY = "REJECTED_NOT_OUR_ENTITY"


class EscalationChannel(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ACCOUNT_MANAGER = "ACCOUNT_MANAGER"


class BoiReportKind(str, Enum):
    INITIAL = "INITIAL"
    UPDATED = "UPDATED"


class BoiReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReinstatementCaseStatus(str, Enum):
    OPEN = "OPEN"
    FEES_ASSESSED = "FEES_ASSESSED"
    PAID = "PAID"
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


# --- Entity shapes -----------------------------------------------------------
# Resources carrying id + created_at + updated_at + version.

class Client(TypedDict):
    id: str
    legal_name: str
    billing_email: str
    credit_balance_cents: int
    portfolio_entity_count: int
    portfolio_open_obligation_count: int
    portfolio_outstanding_cents: int
    portfolio_delinquency_status: str
    sop_open_escalation_count: int
    portfolio_risk_flag: bool
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    legal_entity_id: str
    name_clearance_id: Optional[str]
    state_code: str
    registration_kind: str
    qualified_on: Optional[str]
    closed_on: Optional[str]
    status: str
    agent_of_record_id: Optional[str]
    admin_dissolved_on: Optional[str]
    reinstatement_deadline: Optional[str]
    delinquency_rank: int
    sop_priority_hold: bool
    assumed_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceObligation(TypedDict):
    id: str
    registration_id: str
    governing_rule_id: str
    obligation_type: str
    period_year: int
    rule_determination_date: str
    due_date: str
    grace_end_date: str
    delinquency_date: str
    status: str
    state_fee_cents: int
    franchise_tax_cents: int
    late_fee_cents: int
    service_fee_cents: int
    total_due_cents: int
    satisfied_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Filing(TypedDict):
    id: str
    registration_id: str
    compliance_obligation_id: Optional[str]
    good_standing_certificate_id: Optional[str]
    filing_kind: str
    expedite_tier: str
    status: str
    attempt_number: int
    prepared_by_user_id: str
    submitted_by_user_id: Optional[str]
    submitted_on: Optional[str]
    outcome_recorded_on: Optional[str]
    rejection_reason: Optional[str]
    refile_window_end: Optional[str]
    state_fee_cents: int
    service_fee_cents: int
    expedite_fee_cents: int
    state_portion_cents: int
    service_portion_cents: int
    total_fee_cents: int
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int


# Resources carrying ONLY id + created_at (never mutated).

class GoodStandingCertificate(TypedDict):
    id: str
    registration_id: str
    state_code: str
    issued_on: str
    certificate_number: str
    created_at: str


class PaymentAllocation(TypedDict):
    id: str
    payment_id: str
    filing_id: str
    amount_cents: int
    state_portion_cents: int
    service_portion_cents: int
    sequence_index: int
    is_reversal: bool
    created_at: str


class SopEscalationEvent(TypedDict):
    id: str
    sop_document_id: str
    level: int
    raised_at: str
    channel: str
    created_at: str


#: Resource types that carry id + created_at only — no updated_at, no version.
LEAN_RESOURCE_TYPES: List[str] = [
    "GoodStandingCertificate",
    "PaymentAllocation",
    "SopEscalationEvent",
]
