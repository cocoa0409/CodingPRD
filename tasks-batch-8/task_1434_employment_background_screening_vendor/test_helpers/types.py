"""Domain types: entity TypedDicts, status enums, role enum.

All fourteen entity types carry the full common-field set (id, created_at,
updated_at, version) per PRD section "Common Resource Properties".
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    HR_ADMIN = "HRAdmin"
    HIRING_MANAGER = "HiringManager"
    CANDIDATE = "Candidate"
    VENDOR_AGENT = "VendorAgent"
    ADJUDICATOR = "Adjudicator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AUDITOR = "Auditor"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PROBATION = "PROBATION"
    DECERTIFIED = "DECERTIFIED"


class AuditStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class MatrixStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CandidateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class OrderType(str, Enum):
    INITIAL = "INITIAL"
    RESCREEN = "RESCREEN"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONSENT_CAPTURED = "CONSENT_CAPTURED"
    DISPATCHED = "DISPATCHED"
    REPORT_RECEIVED = "REPORT_RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AdjudicationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    PRE_ADVERSE_PENDING = "PRE_ADVERSE_PENDING"
    FINAL_ADVERSE = "FINAL_ADVERSE"
    DISPUTE_HOLD = "DISPUTE_HOLD"
    VOIDED = "VOIDED"


class ConsentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ReportStatus(str, Enum):
    DELIVERED = "DELIVERED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    AMENDED = "AMENDED"


class CaseStatus(str, Enum):
    WAITING_PERIOD = "WAITING_PERIOD"
    ELIGIBLE_FOR_FINAL = "ELIGIBLE_FOR_FINAL"
    DISPUTE_HOLD = "DISPUTE_HOLD"
    FINAL_NOTICE_SENT = "FINAL_NOTICE_SENT"
    ABORTED = "ABORTED"


class DisputeStatus(str, Enum):
    UNDER_REINVESTIGATION = "UNDER_REINVESTIGATION"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_AMENDED = "RESOLVED_AMENDED"
    WITHDRAWN = "WITHDRAWN"


class IADecision(str, Enum):
    PROCEED_ADVERSE = "PROCEED_ADVERSE"
    CLEAR_CANDIDATE = "CLEAR_CANDIDATE"


class IAStatus(str, Enum):
    DECIDED = "DECIDED"
    VOID = "VOID"


class RecommendedOutcome(str, Enum):
    CLEAR = "CLEAR"
    IA_REQUIRED = "IA_REQUIRED"
    ADVERSE_ELIGIBLE = "ADVERSE_ELIGIBLE"


class RiskTier(str, Enum):
    TIER_1_STANDARD = "TIER_1_STANDARD"
    TIER_2_ELEVATED = "TIER_2_ELEVATED"
    TIER_3_HIGH_RISK = "TIER_3_HIGH_RISK"


class CheckType(str, Enum):
    CRIMINAL_COUNTY = "CRIMINAL_COUNTY"
    CRIMINAL_STATE = "CRIMINAL_STATE"
    CRIMINAL_FEDERAL = "CRIMINAL_FEDERAL"
    SSN_TRACE = "SSN_TRACE"
    EMPLOYMENT_VERIFY = "EMPLOYMENT_VERIFY"
    EDUCATION_VERIFY = "EDUCATION_VERIFY"
    MVR = "MVR"
    CREDIT_CHECK = "CREDIT_CHECK"
    GLOBAL_SANCTIONS = "GLOBAL_SANCTIONS"


class OffenseCategory(str, Enum):
    VIOLENT_FELONY = "VIOLENT_FELONY"
    NONVIOLENT_FELONY = "NONVIOLENT_FELONY"
    MISDEMEANOR = "MISDEMEANOR"
    INFRACTION = "INFRACTION"
    ARREST_NO_CONVICTION = "ARREST_NO_CONVICTION"
    EMPLOYMENT_DISCREPANCY = "EMPLOYMENT_DISCREPANCY"
    EDUCATION_DISCREPANCY = "EDUCATION_DISCREPANCY"
    SANCTIONS_HIT = "SANCTIONS_HIT"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Disposition(str, Enum):
    CONVICTION = "CONVICTION"
    DISMISSED = "DISMISSED"
    PENDING = "PENDING"
    ARREST_ONLY = "ARREST_ONLY"


class ScreeningVendor(TypedDict, total=False):
    id: str
    name: str
    base_tat_business_hours: int
    max_concurrent_orders: int
    surcharge_cents: int
    status: str
    active_order_count: int
    consecutive_sla_breaches: int
    accuracy_bps_finalized: int
    accuracy_bps_including_draft: int
    created_at: str
    updated_at: str
    version: int


class VendorAccuracyAudit(TypedDict, total=False):
    id: str
    vendor_id: str
    period_start: str
    period_end: str
    sample_size: int
    mismatches_found: int
    mismatch_rate_bps: int
    status: str
    rescreen_order_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningPackage(TypedDict, total=False):
    id: str
    name: str
    risk_tier: str
    check_types: List[str]
    tat_business_hours: int
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class JurisdictionRule(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    screening_gate_stage: str
    lookback_years_limit: int
    arrest_records_considerable: bool
    lookback_exemption_salary_cents: int
    pre_adverse_wait_business_days: int
    individualized_assessment_required: bool
    credit_check_allowed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AdjudicationMatrix(TypedDict, total=False):
    id: str
    risk_tier: str
    rules: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict, total=False):
    id: str
    title: str
    department: str
    risk_tier: str
    package_id: str
    jurisdiction_code: str
    annual_salary_cents: int
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    home_jurisdiction_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningOrder(TypedDict, total=False):
    id: str
    candidate_id: str
    position_id: str
    order_type: str
    rescreen_of_order_id: Optional[str]
    vendor_id: Optional[str]
    conditional_offer_extended_at: Optional[str]
    fulfillment_status: str
    adjudication_status: str
    dispatched_at: Optional[str]
    sla_due_at: Optional[str]
    escalation_level: int
    provisional_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    pinned_package_id: Optional[str]
    pinned_package_version: Optional[int]
    pinned_matrix_id: Optional[str]
    pinned_matrix_version: Optional[int]
    recommended_outcome: Optional[str]
    adverse_initiated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict, total=False):
    id: str
    order_id: str
    disclosure_form_id: str
    contains_extraneous_terms: bool
    authorization_signed_at: str
    captured_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningReport(TypedDict, total=False):
    id: str
    order_id: str
    vendor_id: str
    delivered_at: str
    turnaround_business_hours: float
    sla_breached: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportFinding(TypedDict, total=False):
    id: str
    report_id: str
    check_type: str
    offense_category: str
    severity: str
    offense_date: str
    disposition: str
    considerable: bool
    matched_action: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IndividualizedAssessment(TypedDict, total=False):
    id: str
    order_id: str
    adjudicator_user_id: str
    green_factor_nature_gravity: str
    green_factor_time_elapsed: str
    green_factor_job_relatedness: str
    evidence_considered: bool
    decision: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseActionCase(TypedDict, total=False):
    id: str
    order_id: str
    initiated_by_user_id: str
    pre_notice_sent_at: str
    wait_business_days_required: int
    total_hold_business_days: int
    earliest_final_notice_at: str
    hold_started_at: Optional[str]
    final_notice_sent_at: Optional[str]
    final_notice_issuer_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    order_id: str
    candidate_id: str
    reason: str
    finding_ids: Optional[List[str]]
    filed_at: str
    resolved_at: Optional[str]
    overdue: bool
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
