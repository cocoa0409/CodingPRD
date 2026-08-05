"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the uniform system-managed fields
(id, created_at, updated_at, version) described in PRD section 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --- Role enum ---------------------------------------------------------------

class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    FILER = "Filer"
    ETHICS_OFFICER = "EthicsOfficer"
    INVESTIGATOR = "Investigator"
    ADJUDICATOR = "Adjudicator"
    PUBLIC = "Public"


# --- Status / enum vocabularies ---------------------------------------------

class FilerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SEPARATED = "SEPARATED"


class FilerCategory(str, Enum):
    ELECTED = "ELECTED"
    APPOINTED = "APPOINTED"
    SENIOR_STAFF = "SENIOR_STAFF"
    CANDIDATE = "CANDIDATE"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DELINQUENT = "DELINQUENT"


class TrainingStatusValue(str, Enum):
    NONE = "NONE"
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"


class StatementType(str, Enum):
    ANNUAL = "ANNUAL"
    TRANSACTIONAL = "TRANSACTIONAL"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    FLAGGED = "FLAGGED"
    SUPERSEDED = "SUPERSEDED"


class PublicStatus(str, Enum):
    NOT_PUBLISHED = "NOT_PUBLISHED"
    PUBLISHED = "PUBLISHED"
    WITHHELD = "WITHHELD"


class RedactionLevel(str, Enum):
    FULL = "FULL"
    REDACTED = "REDACTED"


class FilingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class GiftKind(str, Enum):
    GIFT = "GIFT"
    TRAVEL = "TRAVEL"


class GiftReportStatus(str, Enum):
    REPORTED = "REPORTED"
    DISPOSED = "DISPOSED"


class RecusalStatus(str, Enum):
    DECLARED = "DECLARED"
    RESOLVED = "RESOLVED"


class PenaltyType(str, Enum):
    LATE_FILING = "LATE_FILING"
    SANCTION = "SANCTION"


class PenaltyStatus(str, Enum):
    ACCRUING = "ACCRUING"
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    SCREENED = "SCREENED"
    DISMISSED = "DISMISSED"
    SUBSTANTIATED = "SUBSTANTIATED"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    SUSTAINED = "SUSTAINED"
    NOT_SUSTAINED = "NOT_SUSTAINED"
    CLOSED = "CLOSED"


class TrainingRecordStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version) ----------

class Jurisdiction(TypedDict):
    id: str
    name: str
    gift_single_limit_cents: int
    gift_annual_source_limit_cents: int
    penalty_base_fee_cents: int
    penalty_daily_rate_cents: int
    penalty_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Filer(TypedDict):
    id: str
    jurisdiction_id: str
    full_name: str
    official_title: str
    filer_category: str
    email: Optional[str]
    status: str
    compliance_status: str
    outstanding_penalty_cents: int
    reportable_gift_total_cents: int
    open_recusal_count: int
    training_status: str
    created_at: str
    updated_at: str
    version: int


class FilingPeriod(TypedDict):
    id: str
    jurisdiction_id: str
    label: Optional[str]
    statement_type: str
    coverage_start: str
    coverage_end: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict):
    id: str
    filer_id: str
    filing_period_id: str
    supersedes_statement_id: Optional[str]
    statement_type: str
    content: Any
    status: str
    submitted_at: Optional[str]
    due_at_snapshot: Optional[str]
    is_late: bool
    days_late: int
    correction_round: int
    public_status: str
    published_at: Optional[str]
    redaction_level: str
    created_at: str
    updated_at: str
    version: int


class GiftReport(TypedDict):
    id: str
    filer_id: str
    source_name: str
    gift_kind: str
    fair_market_value_cents: int
    consideration_paid_cents: int
    travel_legs: List[dict]
    received_at: str
    reportable_value_cents: int
    disclosed_gross_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecusalEntry(TypedDict):
    id: str
    filer_id: str
    matter_id: str
    matter_description: Optional[str]
    effective_start: str
    effective_end: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Penalty(TypedDict):
    id: str
    filer_id: str
    statement_id: Optional[str]
    investigation_id: Optional[str]
    penalty_type: str
    provisional_amount_cents: int
    assessed_amount_cents: int
    days_late: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    filer_id: str
    statement_id: Optional[str]
    complainant_ref: Optional[str]
    allegation: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict):
    id: str
    complaint_id: str
    filer_id: str
    assigned_investigator_id: str
    adjudicator_id: Optional[str]
    findings: Optional[str]
    recommended_sanction_cents: int
    final_sanction_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict):
    id: str
    filer_id: str
    course_code: str
    enrolled_at: str
    completed_at: Optional[str]
    expires_at: Optional[str]
    certificate_no: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
