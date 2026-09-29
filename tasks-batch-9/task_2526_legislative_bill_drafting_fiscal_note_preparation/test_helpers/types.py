"""Domain types for the legislative bill drafting and fiscal note API.

Status enums, role enum and entity TypedDicts. Field names are exactly the
names the PRD uses in its entity property tables.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLERK = "Clerk"
    FISCAL_OFFICER = "FiscalOfficer"
    MEMBER = "Member"
    DRAFTER = "Drafter"
    REVIEW_COUNSEL = "ReviewCounsel"
    AGENCY_ANALYST = "AgencyAnalyst"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class SessionStatus(str, Enum):
    PENDING = "PENDING"
    CONVENED = "CONVENED"
    ADJOURNED = "ADJOURNED"


class FiscalPosture(str, Enum):
    NORMAL = "NORMAL"
    CONSTRAINED = "CONSTRAINED"


class Chamber(str, Enum):
    HOUSE = "HOUSE"
    SENATE = "SENATE"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DraftingRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RESEARCH = "RESEARCH"
    DRAFTING = "DRAFTING"
    RETURNED_FOR_CLARIFICATION = "RETURNED_FOR_CLARIFICATION"
    DRAFT_READY = "DRAFT_READY"
    CONVERTED = "CONVERTED"
    WITHDRAWN = "WITHDRAWN"
    LAPSED = "LAPSED"


class Confidentiality(str, Enum):
    CONFIDENTIAL = "CONFIDENTIAL"
    PUBLIC = "PUBLIC"


class ConflictType(str, Enum):
    AMENDS_SAME_SECTION = "AMENDS_SAME_SECTION"
    REPEALS_ACTIVE = "REPEALS_ACTIVE"
    DUPLICATE_ENACTMENT = "DUPLICATE_ENACTMENT"
    STYLE_VIOLATION = "STYLE_VIOLATION"


class ConflictSeverity(str, Enum):
    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"


class ConflictResolutionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class BillLegislativeStatus(str, Enum):
    INTRODUCED = "INTRODUCED"
    REFERRED = "REFERRED"
    REPORTED = "REPORTED"
    PASSED_CHAMBER = "PASSED_CHAMBER"
    ENROLLED = "ENROLLED"
    TRANSMITTED = "TRANSMITTED"
    DEAD = "DEAD"


class BillFiscalStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    NOTE_PENDING = "NOTE_PENDING"
    NOTE_STALE = "NOTE_STALE"
    NOTE_COMPLETE = "NOTE_COMPLETE"


class CommitteeReferralStatus(str, Enum):
    IN_COMMITTEE = "IN_COMMITTEE"
    REPORTED_FAVORABLE = "REPORTED_FAVORABLE"
    REPORTED_UNFAVORABLE = "REPORTED_UNFAVORABLE"
    DIED_IN_COMMITTEE = "DIED_IN_COMMITTEE"


class ReportOutcome(str, Enum):
    FAVORABLE = "FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"


class FiscalNoteRequestStatus(str, Enum):
    ROUTED = "ROUTED"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"


class Methodology(str, Enum):
    INCREMENTAL_COST = "INCREMENTAL_COST"
    FULL_ABSORPTION = "FULL_ABSORPTION"


class Scenario(str, Enum):
    BASELINE = "BASELINE"
    HIGH = "HIGH"
    LOW = "LOW"


class AmendmentStage(str, Enum):
    COMMITTEE = "COMMITTEE"
    FLOOR = "FLOOR"


class AmendmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DRAFTED = "DRAFTED"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"
    LAPSED = "LAPSED"


class EnrolledBillStatus(str, Enum):
    PREPARED = "PREPARED"
    ORIGIN_SIGNED = "ORIGIN_SIGNED"
    SECOND_SIGNED = "SECOND_SIGNED"
    TRANSMITTED = "TRANSMITTED"


class SignatureRole(str, Enum):
    SPEAKER = "SPEAKER"
    SENATE_PRESIDENT = "SENATE_PRESIDENT"
    GOVERNOR_TRANSMITTAL = "GOVERNOR_TRANSMITTAL"
    NONE = "NONE"


class CorrectionType(str, Enum):
    TYPO = "TYPO"
    CITATION = "CITATION"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    NUMBERING = "NUMBERING"


class TechnicalCorrectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Every entity below except CostEstimate carries the four common properties
# id / created_at / updated_at / version. CostEstimate rows are append-only and
# carry only id and created_at.
# ---------------------------------------------------------------------------
class Session(TypedDict):
    id: str
    name: str
    introduction_deadline_utc: str
    committee_report_deadline_utc: str
    sine_die_utc: str
    fiscal_note_default_days: int
    constrained_threshold_cents: int
    fiscal_cap_cents: int
    required_fiscal_years: List[int]
    status: str
    convened_utc: Optional[str]
    adjourned_utc: Optional[str]
    next_house_bill_number: int
    next_senate_bill_number: int
    certified_fiscal_total_cents: int
    fiscal_posture: str
    bills_introduced_count: int
    bills_enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    chamber: str
    party: str
    priority_slots_total: int
    priority_slots_used: int
    clarification_pending_count: int
    intake_hold: bool
    created_at: str
    updated_at: str
    version: int


class Drafter(TypedDict):
    id: str
    full_name: str
    is_senior: bool
    max_concurrent_engagements: int
    active_engagement_count: int
    created_at: str
    updated_at: str
    version: int


class Agency(TypedDict):
    id: str
    name: str
    agency_code: str
    status: str
    max_open_requests: int
    open_request_count: int
    late_submission_count: int
    revision_count: int
    responsiveness_score: int
    created_at: str
    updated_at: str
    version: int


class Committee(TypedDict):
    id: str
    session_id: str
    chamber: str
    name: str
    is_fiscal_committee: bool
    max_concurrent_referrals: int
    active_referral_count: int
    created_at: str
    updated_at: str
    version: int


class DraftingRequest(TypedDict):
    id: str
    session_id: str
    member_id: str
    subject: str
    summary: str
    confidentiality: str
    priority_flag: bool
    requested_sections_count: int
    target_code_chapter: str
    appropriation_requested_cents: int
    status: str
    assigned_drafter_id: Optional[str]
    engagement_start_utc: Optional[str]
    engagement_end_utc: Optional[str]
    affected_sections_count: Optional[int]
    research_completed_utc: Optional[str]
    intake_complexity_estimate: Optional[int]
    actual_complexity_score: Optional[int]
    sla_due_utc: Optional[str]
    revision_round: int
    blocking_conflict_count: int
    open_blocking_conflict_count: int
    advisory_conflict_count: int
    style_findings_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StatutoryConflict(TypedDict):
    id: str
    drafting_request_id: str
    code_citation: str
    conflict_type: str
    severity: str
    resolution_status: str
    resolution_note: Optional[str]
    resolved_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict):
    id: str
    session_id: str
    drafting_request_id: str
    sponsor_member_id: str
    companion_bill_id: Optional[str]
    chamber: str
    bill_number: str
    legislative_status: str
    fiscal_status: str
    appropriation_requested_cents: int
    priority_bill: bool
    introduced_utc: str
    adopted_fiscal_delta_cents: int
    adopted_amendment_count: int
    referral_count: int
    created_at: str
    updated_at: str
    version: int


class CommitteeReferral(TypedDict):
    id: str
    bill_id: str
    committee_id: str
    referral_order: int
    hearing_window_start_utc: str
    hearing_window_end_utc: str
    report_deadline_utc: str
    status: str
    reported_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FiscalNoteRequest(TypedDict):
    id: str
    bill_id: str
    agency_id: str
    reopened_by_amendment_id: Optional[str]
    methodology: str
    routed_utc: str
    due_utc: str
    submitted_utc: Optional[str]
    certified_utc: Optional[str]
    status: str
    revision_round: int
    late_submission: bool
    direct_cost_cents: Optional[int]
    contingency_pct: Optional[float]
    contingency_cents: Optional[int]
    certified_total_cents: Optional[int]
    projected_revenue_total_cents: Optional[int]
    high_scenario_total_cents: Optional[int]
    low_scenario_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CostEstimate(TypedDict):
    """Append-only cost estimate line: carries only id and created_at."""

    id: str
    fiscal_note_request_id: str
    fiscal_year: int
    scenario: str
    revision_round: int
    personnel_cost_cents: int
    operating_cost_cents: int
    one_time_cost_cents: int
    fte_count: float
    revenue_impact_cents: int
    assumption_note: str
    included_in_certification: bool
    created_at: str


class Amendment(TypedDict):
    id: str
    bill_id: str
    committee_referral_id: Optional[str]
    requested_by_member_id: str
    drafted_by_drafter_id: Optional[str]
    supersedes_amendment_id: Optional[str]
    stage: str
    summary: str
    fiscal_impact_delta_cents: int
    drafting_start_utc: str
    drafting_due_utc: str
    requested_utc: str
    turnaround_deadline_utc: str
    status: str
    drafted_utc: Optional[str]
    adopted_utc: Optional[str]
    rescind_count: int
    created_at: str
    updated_at: str
    version: int


class EnrolledBill(TypedDict):
    id: str
    bill_id: str
    adopted_amendment_count: int
    net_fiscal_delta_cents: int
    enrollment_sequence: List[str]
    origin_signature_role: str
    expected_next_signature: str
    status: str
    corrections_applied_count: int
    open_corrections_count: int
    origin_signed_utc: Optional[str]
    second_signed_utc: Optional[str]
    transmitted_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TechnicalCorrection(TypedDict):
    id: str
    enrolled_bill_id: str
    proposed_by_drafter_id: str
    applied_by_drafter_id: Optional[str]
    correction_type: str
    description: str
    is_substantive: bool
    status: str
    applied_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int
