"""Domain types for the Continuing Disclosure & Investor Reporting API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1)
# --------------------------------------------------------------------------- #

class UserRole(str, Enum):
    FINANCE_DIRECTOR = "FinanceDirector"
    DISCLOSURE_OFFICER = "DisclosureOfficer"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    DISSEMINATION_AGENT = "DisseminationAgent"


# --------------------------------------------------------------------------- #
# BondIssue (PRD §3.1)
# --------------------------------------------------------------------------- #

class BondIssueStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    DEFEASED = "DEFEASED"
    MATURED = "MATURED"


class SecurityType(str, Enum):
    GENERAL_OBLIGATION = "GENERAL_OBLIGATION"
    REVENUE = "REVENUE"
    SPECIAL_ASSESSMENT = "SPECIAL_ASSESSMENT"


class RatingAgency(str, Enum):
    MOODYS = "MOODYS"
    SP = "SP"
    FITCH = "FITCH"
    KBRA = "KBRA"


class DefeasanceType(str, Enum):
    LEGAL = "LEGAL"
    ECONOMIC = "ECONOMIC"


# --------------------------------------------------------------------------- #
# Undertaking (PRD §3.2, §3.8)
# --------------------------------------------------------------------------- #

class UndertakingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class TerminationCause(str, Enum):
    DEFEASANCE = "DEFEASANCE"
    MATURITY = "MATURITY"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    IMPAIRED = "IMPAIRED"
    DELINQUENT = "DELINQUENT"


class RemediationTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class TimelinessBasis(str, Enum):
    SUBMISSION_BASIS = "SUBMISSION_BASIS"
    CONFIRMATION_BASIS = "CONFIRMATION_BASIS"


# --------------------------------------------------------------------------- #
# ContentRequirement / CycleContentItem (PRD §3.2, §3.3)
# --------------------------------------------------------------------------- #

class ContentKind(str, Enum):
    AUDITED_FINANCIALS = "AUDITED_FINANCIALS"
    OPERATING_DATA_TABLE = "OPERATING_DATA_TABLE"
    BUDGET_SUMMARY = "BUDGET_SUMMARY"
    DEBT_SERVICE_SCHEDULE = "DEBT_SERVICE_SCHEDULE"
    ENTERPRISE_STATISTICS = "ENTERPRISE_STATISTICS"


class AuditOpinionType(str, Enum):
    UNMODIFIED = "UNMODIFIED"
    QUALIFIED = "QUALIFIED"
    UNAUDITED_INTERIM = "UNAUDITED_INTERIM"


class ContentItemStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DRAFT = "DRAFT"
    READY = "READY"
    WAIVED = "WAIVED"
    VOID = "VOID"


# --------------------------------------------------------------------------- #
# AnnualReportCycle (PRD §3.3, §3.4)
# --------------------------------------------------------------------------- #

class CycleStatus(str, Enum):
    DRAFTING = "DRAFTING"
    READY_TO_FILE = "READY_TO_FILE"
    FILING_IN_PROGRESS = "FILING_IN_PROGRESS"
    FILED_TIMELY = "FILED_TIMELY"
    FILED_LATE = "FILED_LATE"
    DELINQUENT = "DELINQUENT"
    WITHDRAWN = "WITHDRAWN"
    CLOSED_NOT_REQUIRED = "CLOSED_NOT_REQUIRED"


# --------------------------------------------------------------------------- #
# MaterialEventNotice (PRD §3.5)
# --------------------------------------------------------------------------- #

class EventType(str, Enum):
    PRINCIPAL_PAYMENT_DELINQUENCY = "PRINCIPAL_PAYMENT_DELINQUENCY"
    RATING_CHANGE = "RATING_CHANGE"
    DEFEASANCE = "DEFEASANCE"
    BOND_CALL = "BOND_CALL"
    UNSCHEDULED_DRAW_ON_RESERVE = "UNSCHEDULED_DRAW_ON_RESERVE"
    TRUSTEE_SUBSTITUTION = "TRUSTEE_SUBSTITUTION"
    FINANCIAL_OBLIGATION_INCURRENCE = "FINANCIAL_OBLIGATION_INCURRENCE"
    MERGER_OR_SALE = "MERGER_OR_SALE"


class NoticeStatus(str, Enum):
    DETERMINATION_PENDING = "DETERMINATION_PENDING"
    MATERIAL = "MATERIAL"
    NOT_MATERIAL = "NOT_MATERIAL"
    FILING_IN_PROGRESS = "FILING_IN_PROGRESS"
    FILED_TIMELY = "FILED_TIMELY"
    FILED_LATE = "FILED_LATE"
    MISSED = "MISSED"
    VOID = "VOID"


class Determination(str, Enum):
    MATERIAL = "MATERIAL"
    NOT_MATERIAL = "NOT_MATERIAL"


# --------------------------------------------------------------------------- #
# Filing (PRD §3.7)
# --------------------------------------------------------------------------- #

class FilingType(str, Enum):
    ANNUAL_REPORT = "ANNUAL_REPORT"
    MATERIAL_EVENT_NOTICE = "MATERIAL_EVENT_NOTICE"
    FAILURE_TO_FILE_NOTICE = "FAILURE_TO_FILE_NOTICE"
    VOLUNTARY_FINANCIAL_OBLIGATION = "VOLUNTARY_FINANCIAL_OBLIGATION"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------- #
# FailureToFileEvent (PRD §3.8)
# --------------------------------------------------------------------------- #

class FailureKind(str, Enum):
    ANNUAL_REPORT_LATE = "ANNUAL_REPORT_LATE"
    ANNUAL_REPORT_MISSED = "ANNUAL_REPORT_MISSED"
    MATERIAL_EVENT_MISSED = "MATERIAL_EVENT_MISSED"


class FailureSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class FailureEventStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_PENDING = "REMEDIATION_PENDING"
    REMEDIATED = "REMEDIATED"


# --------------------------------------------------------------------------- #
# DirectPlacement (PRD §3.6)
# --------------------------------------------------------------------------- #

class DisclosurePractice(str, Enum):
    MANDATORY_MATERIAL_EVENT = "MANDATORY_MATERIAL_EVENT"
    VOLUNTARY = "VOLUNTARY"
    NOT_DISCLOSED = "NOT_DISCLOSED"


class PlacementStatus(str, Enum):
    RECEIVED = "RECEIVED"
    DISCLOSURE_REQUIRED = "DISCLOSURE_REQUIRED"
    DISCLOSED = "DISCLOSED"
    DISCLOSURE_WAIVED = "DISCLOSURE_WAIVED"


# --------------------------------------------------------------------------- #
# OfficialStatement (PRD §3.9)
# --------------------------------------------------------------------------- #

class LookbackPolicy(str, Enum):
    STRICT_FIVE_YEAR = "STRICT_FIVE_YEAR"
    REMEDIATED_EXCLUDED = "REMEDIATED_EXCLUDED"


class OfficialStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    POSTED = "POSTED"


class DisclosureAdequacy(str, Enum):
    UNKNOWN = "UNKNOWN"
    ADEQUATE = "ADEQUATE"
    INCOMPLETE = "INCOMPLETE"


# --------------------------------------------------------------------------- #
# DisseminationEngagement (PRD §3.10)
# --------------------------------------------------------------------------- #

class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class TerminationReason(str, Enum):
    SUPERSEDED = "SUPERSEDED"
    UNDERTAKING_TERMINATED = "UNDERTAKING_TERMINATED"
    ISSUER_TERMINATED = "ISSUER_TERMINATED"


# --------------------------------------------------------------------------- #
# Entity shapes.  Every entity below carries id / created_at / updated_at /
# version except ContentRequirement, which the PRD declares immutable and
# therefore carries only id and created_at (PRD §2.4).
# --------------------------------------------------------------------------- #

class BondIssue(TypedDict):
    id: str
    issuer_program_code: str
    series_designation: str
    security_type: str
    dated_date: str
    final_maturity_date: str
    original_par_amount_cents: int
    outstanding_par_amount_cents: int
    status: str
    current_rating: Optional[str]
    current_rating_agency: Optional[str]
    defeasance_type: Optional[str]
    escrow_deposit_cents: int
    defeased_at: Optional[str]
    open_material_event_count: int
    created_at: str
    updated_at: str
    version: int


class Undertaking(TypedDict):
    id: str
    issue_id: str
    fiscal_year_end_month_day: str
    filing_window_days: int
    timeliness_basis: str
    status: str
    suspended_reason: Optional[str]
    termination_cause: Optional[str]
    compliance_posture: str
    disclosure_risk_score: float
    remediation_tier: str
    late_filing_count: int
    missed_event_count: int
    delinquent_cycle_count: int
    open_obligation_count: int
    content_weight_bp_total: int
    created_at: str
    updated_at: str
    version: int


class ContentRequirement(TypedDict):
    # PRD §2.4: a ContentRequirement has no updated_at field and no version field.
    id: str
    undertaking_id: str
    kind: str
    label: str
    weight_bp: int
    waivable: bool
    requires_audit_opinion: bool
    created_at: str


class AnnualReportCycle(TypedDict):
    id: str
    undertaking_id: str
    fiscal_year_label: str
    period_start_date: str
    period_end_date: str
    due_date: str
    status: str
    completeness_score_pct: float
    assembled_by_user_id: Optional[str]
    assembled_at: Optional[str]
    filed_filing_id: Optional[str]
    timeliness_basis_applied: Optional[str]
    filed_at: Optional[str]
    days_late: int
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CycleContentItem(TypedDict):
    id: str
    cycle_id: str
    content_requirement_id: str
    status: str
    weight_bp_snapshot: int
    audit_opinion_type: Optional[str]
    data_as_of_date: Optional[str]
    source_document_ref: Optional[str]
    attested_by_user_id: Optional[str]
    attested_at: Optional[str]
    waiver_reason: Optional[str]
    readiness_factor: float
    created_at: str
    updated_at: str
    version: int


class MaterialEventNotice(TypedDict):
    id: str
    issue_id: str
    event_type: str
    per_se_material: bool
    occurrence_date: str
    filing_deadline_date: str
    status: str
    determination_note: Optional[str]
    determined_by_user_id: Optional[str]
    determined_at: Optional[str]
    created_by_user_id: str
    rating_agency: Optional[str]
    prior_rating: Optional[str]
    new_rating: Optional[str]
    financial_obligation_ref: Optional[str]
    filed_filing_id: Optional[str]
    days_late: int
    created_at: str
    updated_at: str
    version: int


class Filing(TypedDict):
    id: str
    issue_id: str
    filing_type: str
    cycle_id: Optional[str]
    material_event_id: Optional[str]
    direct_placement_id: Optional[str]
    supersedes_filing_id: Optional[str]
    superseded_by_filing_id: Optional[str]
    correction_reason: Optional[str]
    status: str
    submitted_at: Optional[str]
    submitted_by_user_id: Optional[str]
    submitting_engagement_id: Optional[str]
    repository_receipt_id: Optional[str]
    repository_confirmed_at: Optional[str]
    rejection_reason: Optional[str]
    submission_attempt_count: int
    created_at: str
    updated_at: str
    version: int


class FailureToFileEvent(TypedDict):
    id: str
    undertaking_id: str
    cycle_id: Optional[str]
    material_event_id: Optional[str]
    kind: str
    occurred_at: str
    days_late: int
    severity: str
    status: str
    remediation_filing_id: Optional[str]
    remediation_note: Optional[str]
    remediated_at: Optional[str]
    disclosed_in_official_statement_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class DirectPlacement(TypedDict):
    id: str
    issue_id: str
    lender_name: str
    principal_amount_cents: int
    execution_date: str
    review_window_start_date: str
    review_window_end_date: str
    disclosure_practice: str
    materiality_ratio_bp: int
    status: str
    linked_notice_id: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OfficialStatement(TypedDict):
    id: str
    issue_id: str
    dated_date: str
    lookback_policy: str
    status: str
    disclosed_event_ids: List[str]
    required_disclosure_event_ids: List[str]
    required_disclosure_event_count: int
    disclosure_adequacy: str
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]
    posted_by_user_id: Optional[str]
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisseminationEngagement(TypedDict):
    id: str
    undertaking_id: str
    agent_name: str
    effective_date: str
    expiration_date: str
    retainer_cents: int
    status: str
    last_calendar_ack_date: Optional[str]
    monitoring_lapse_days: int
    billable_filing_count: int
    invoice_total_cents: int
    superseded_by_engagement_id: Optional[str]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
