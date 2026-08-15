"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class LandlordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CriteriaStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    SCORED = "SCORED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class IdentityStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    DELIVERED = "DELIVERED"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    AMENDED = "AMENDED"
    RE_DELIVERED = "RE_DELIVERED"
    VOIDED = "VOIDED"


class RecordStatus(str, Enum):
    INCLUDED = "INCLUDED"
    SUPPRESSED = "SUPPRESSED"
    DISPUTED = "DISPUTED"
    REMOVED = "REMOVED"


class SuppressionReason(str, Enum):
    LOOKBACK_EXPIRED = "LOOKBACK_EXPIRED"
    SEARCH_PROHIBITED = "SEARCH_PROHIBITED"


class RecordType(str, Enum):
    EVICTION = "EVICTION"
    CRIMINAL = "CRIMINAL"


class IncomeVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class GuarantorStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class GuarantorPolicy(str, Enum):
    INDEPENDENT_ONLY = "INDEPENDENT_ONLY"
    COMBINED_ALLOWED = "COMBINED_ALLOWED"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    RESCINDED = "RESCINDED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REINVESTIGATION = "UNDER_REINVESTIGATION"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_CORRECTED = "RESOLVED_CORRECTED"


class Recommendation(str, Enum):
    RECOMMEND_APPROVE = "RECOMMEND_APPROVE"
    RECOMMEND_CONDITIONAL = "RECOMMEND_CONDITIONAL"
    RECOMMEND_DENY = "RECOMMEND_DENY"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class AdverseReasonCode(str, Enum):
    CREDIT_SCORE_BELOW_MINIMUM = "CREDIT_SCORE_BELOW_MINIMUM"
    RENT_TO_INCOME_BELOW_REQUIRED = "RENT_TO_INCOME_BELOW_REQUIRED"
    INCOME_UNVERIFIABLE = "INCOME_UNVERIFIABLE"
    EVICTION_RECORD = "EVICTION_RECORD"
    CRIMINAL_RECORD = "CRIMINAL_RECORD"


class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    SCREENER = "Screener"
    LANDLORD = "Landlord"
    APPLICANT = "Applicant"


class Landlord(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    status: str
    fee_balance_cents: int
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JurisdictionRule(TypedDict, total=False):
    id: str
    state_code: str
    criminal_lookback_years: int
    eviction_lookback_years: int
    source_of_income_protected: bool
    portable_report_acceptance_required: bool
    max_screening_fee_cents: Optional[int]
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningCriteria(TypedDict, total=False):
    id: str
    landlord_id: str
    name: str
    disclosure_summary: str
    min_credit_score: int
    income_multiplier: float
    guarantor_policy: str
    guarantor_income_multiplier: float
    accepts_portable_reports: bool
    accepts_voucher_income: bool
    effective_from: str
    effective_to: Optional[str]
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    dob: str
    email: str
    ssn_last4: str
    residence_state: str
    created_at: str
    updated_at: str
    version: int


class ScreeningApplication(TypedDict, total=False):
    id: str
    applicant_id: str
    landlord_id: str
    criteria_id: Optional[str]
    portable_report_id: Optional[str]
    unit_state_code: str
    monthly_rent_cents: int
    stated_monthly_income_cents: int
    voucher_monthly_amount_cents: int
    consent_signed_at: Optional[str]
    identity_status: str
    identity_attempts: int
    status: str
    submitted_at: Optional[str]
    credit_score: Optional[int]
    verified_income_cents: Optional[int]
    affordability_passes: Optional[bool]
    eviction_included_count: Optional[int]
    criminal_included_count: Optional[int]
    recommendation: Optional[str]
    decision: Optional[str]
    decided_at: Optional[str]
    requires_reconsideration: bool
    fee_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class ScreeningReport(TypedDict, total=False):
    id: str
    application_id: str
    is_portable_copy: bool
    source_report_id: Optional[str]
    status: str
    originating_screener_id: Optional[str]
    credit_score: int
    included_record_count: int
    delivered_at: Optional[str]
    last_delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningRecord(TypedDict, total=False):
    id: str
    report_id: str
    record_type: str
    jurisdiction_state_code: str
    record_date: str
    description: str
    status: str
    suppression_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeVerification(TypedDict, total=False):
    id: str
    application_id: str
    employer_name: str
    verified_monthly_income_cents: Optional[int]
    status: str
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Guarantor(TypedDict, total=False):
    id: str
    application_id: str
    full_name: str
    stated_monthly_income_cents: int
    verified_monthly_income_cents: Optional[int]
    credit_score: Optional[int]
    qualification_policy_used: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseActionNotice(TypedDict, total=False):
    id: str
    application_id: str
    reason_codes: List[str]
    status: str
    issued_at: Optional[str]
    dispute_deadline: Optional[str]
    rescinded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    report_id: str
    applicant_id: str
    disputed_record_ids: List[str]
    reason_text: str
    status: str
    filed_at: str
    reinvestigation_deadline: str
    reinvestigator_screener_id: Optional[str]
    resolved_at: Optional[str]
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsistencyAuditRun(TypedDict, total=False):
    # Immutable event record: id + created_at only; NO updated_at, NO version.
    id: str
    created_at: str
    landlord_id: str
    run_at: str
    applications_examined: int
    inconsistencies_found: int
    inconsistent_application_ids: List[str]
    deviation_rate: float
