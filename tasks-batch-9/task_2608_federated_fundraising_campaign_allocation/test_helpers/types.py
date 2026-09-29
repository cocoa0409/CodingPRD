"""Domain types for the Federated Fundraising Campaign Allocation API.

Entity TypedDicts, status enums and the role enum, derived from the PRD.
Every resource in this system carries ``id``, ``created_at``, ``updated_at``
and ``version`` (PRD 2.4), so every TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    UNITED_FUND_ADMIN = "UnitedFundAdmin"
    CAMPAIGN_COORDINATOR = "CampaignCoordinator"
    FINANCE_REVIEWER = "FinanceReviewer"
    AGENCY_REPRESENTATIVE = "AgencyRepresentative"
    VOLUNTEER_PANELIST = "VolunteerPanelist"
    ALLOCATIONS_DIRECTOR = "AllocationsDirector"


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------
class EmployerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EmployerSuspendedReason(str, Enum):
    ESCROW_HOLD_SHRINKAGE = "ESCROW_HOLD_SHRINKAGE"


class CoordinatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CoordinatorRole(str, Enum):
    LEAD = "LEAD"
    DEPARTMENT = "DEPARTMENT"


class CampaignPosture(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    SOLICITATION_CLOSED = "SOLICITATION_CLOSED"
    RECONCILED = "RECONCILED"
    ESCROW_HOLD = "ESCROW_HOLD"


class GivingMethod(str, Enum):
    PAYROLL_DEDUCTION = "PAYROLL_DEDUCTION"
    ONE_TIME_CHECK = "ONE_TIME_CHECK"
    CREDIT_CARD = "CREDIT_CARD"
    STOCK_GIFT = "STOCK_GIFT"


class PledgeDesignationStatus(str, Enum):
    """The pledge's designation axis (PRD 3.3, 3.4)."""

    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    AMENDED = "AMENDED"
    LOCKED = "LOCKED"


class PledgeCollectionStatus(str, Enum):
    """The pledge's collection axis, independent of designation (PRD 3.5)."""

    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    COLLECTED = "COLLECTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class WriteOffReasonCode(str, Enum):
    TERMINATION = "TERMINATION"
    LEAVE_OF_ABSENCE = "LEAVE_OF_ABSENCE"
    DONOR_REVOKED = "DONOR_REVOKED"
    EMPLOYER_DEFAULT = "EMPLOYER_DEFAULT"


class DesignationLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    UNCOLLECTED = "UNCOLLECTED"


class PriorityArea(str, Enum):
    BASIC_NEEDS = "BASIC_NEEDS"
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"
    FINANCIAL_STABILITY = "FINANCIAL_STABILITY"


class ExpertiseArea(str, Enum):
    BASIC_NEEDS = "BASIC_NEEDS"
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"
    FINANCIAL_STABILITY = "FINANCIAL_STABILITY"
    FINANCE = "FINANCE"


class MembershipStatus(str, Enum):
    APPLICANT = "APPLICANT"
    UNDER_FINANCIAL_REVIEW = "UNDER_FINANCIAL_REVIEW"
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED_MEMBERSHIP = "SUSPENDED_MEMBERSHIP"


class AgencyReviewStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"


class ReviewBasis(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    AUDITED = "AUDITED"


class AuditOpinion(str, Enum):
    UNQUALIFIED = "UNQUALIFIED"
    QUALIFIED = "QUALIFIED"
    ADVERSE = "ADVERSE"
    NONE = "NONE"


class CyclePosture(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AssignmentRole(str, Enum):
    CHAIR = "CHAIR"
    SCORER = "SCORER"


class AllocationRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_PANEL_REVIEW = "UNDER_PANEL_REVIEW"
    SUSPENDED_REVIEW = "SUSPENDED_REVIEW"
    PANEL_APPROVED = "PANEL_APPROVED"
    PANEL_DECLINED = "PANEL_DECLINED"
    AWARDED = "AWARDED"
    REPORTING = "REPORTING"
    CLOSED_SATISFIED = "CLOSED_SATISFIED"


class OutcomeReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SITE_VISIT_SCHEDULED = "SITE_VISIT_SCHEDULED"
    SITE_VISIT_COMPLETED = "SITE_VISIT_COMPLETED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Employer(TypedDict):
    id: str
    legal_name: str
    employee_count: int
    payroll_periods_per_year: int
    historical_shrinkage_rate_bps: int
    partnership_signed: bool
    status: str
    suspended_reason: Optional[str]
    active_campaign_count: int
    created_at: str
    updated_at: str
    version: int


class CampaignCoordinator(TypedDict):
    id: str
    employer_id: str
    full_name: str
    email: str
    coordinator_role: str
    status: str
    recorded_pledge_count: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    employer_id: str
    campaign_year: int
    solicitation_start_date: str
    solicitation_end_date: str
    loss_reserve_amount: float
    posture: str
    confirmed_gross_total: float
    designated_gross_total: float
    undesignated_gross_total: float
    designation_fee_total: float
    projected_payroll_pledge_total: float
    provisional_estimated_loss: Optional[float]
    provisional_net_expected_revenue: Optional[float]
    reserve_absorbed_amount: Optional[float]
    final_actual_loss: Optional[float]
    final_net_expected_revenue: Optional[float]
    realized_shrinkage_rate_bps: Optional[int]
    solicitation_closed_at: Optional[str]
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict):
    id: str
    campaign_id: str
    recorded_by_coordinator_id: Optional[str]
    donor_reference: str
    giving_method: str
    gross_amount: float
    designation_status: str
    collection_status: str
    designated_amount_total: float
    undesignated_amount: float
    designation_fee_total: float
    net_designated_total: float
    collected_amount: float
    uncollected_amount: float
    amend_count: int
    write_off_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PledgeDesignation(TypedDict):
    id: str
    pledge_id: str
    agency_id: str
    designation_sequence: int
    designated_amount: float
    processing_fee: float
    net_designated_amount: float
    collected_designated_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Agency(TypedDict):
    id: str
    legal_name: str
    ein: str
    primary_priority_area: str
    membership_status: str
    latest_standing_score: Optional[float]
    designated_passthrough_ytd: float
    open_review_count: int
    probation_count: int
    outcome_report_delinquent: bool
    created_at: str
    updated_at: str
    version: int


class AgencyReview(TypedDict):
    id: str
    agency_id: str
    fiscal_year: int
    program_expense_ratio: float
    admin_expense_ratio: float
    months_operating_reserve: float
    governance_checklist_passed_count: int
    audit_opinion: str
    audited_program_expense_ratio: Optional[float]
    audited_admin_expense_ratio: Optional[float]
    audited_months_operating_reserve: Optional[float]
    preliminary_score: float
    certified_score: Optional[float]
    standards_met: Optional[bool]
    restatement_penalty_applied: bool
    review_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationCycle(TypedDict):
    id: str
    cycle_year: int
    focus_priority_area: str
    opening_undesignated_pool: float
    max_award_per_agency: float
    request_window_start: str
    request_window_end: str
    posture: str
    available_undesignated_pool: float
    awarded_total: float
    submitted_request_count: int
    suspended_request_count: int
    suspended_request_ratio: float
    awards_blocked: bool
    created_at: str
    updated_at: str
    version: int


class Panelist(TypedDict):
    id: str
    full_name: str
    email: str
    expertise_area: str
    submitted_score_count: int
    site_visit_count: int
    created_at: str
    updated_at: str
    version: int


class PanelAssignment(TypedDict):
    id: str
    cycle_id: str
    panelist_id: str
    conflict_declared: bool
    assignment_role: str
    submitted_score_count: int
    created_at: str
    updated_at: str
    version: int


class AllocationRequest(TypedDict):
    id: str
    cycle_id: str
    agency_id: str
    requested_amount: float
    priority_area: str
    narrative_summary: str
    status: str
    status_before_suspension: Optional[str]
    eligible_score_count: int
    composite_score: Optional[float]
    base_award: Optional[float]
    designation_offset: Optional[float]
    strategic_supplement: Optional[float]
    total_award: Optional[float]
    submitted_at: Optional[str]
    awarded_at: Optional[str]
    outcome_report_due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PanelScore(TypedDict):
    id: str
    request_id: str
    panelist_id: str
    priority_alignment_score: int
    outcome_evidence_score: int
    capacity_score: int
    weighted_score: float
    eligible: bool
    created_at: str
    updated_at: str
    version: int


class OutcomeReport(TypedDict):
    id: str
    request_id: str
    reporting_period_end: str
    persons_served: int
    outcome_metric_name: str
    outcome_metric_value: float
    funds_expended: float
    expenditure_variance_pct: float
    status: str
    revision_round_count: int
    submitted_at: str
    site_visit_panelist_id: Optional[str]
    site_visit_window_start: Optional[str]
    site_visit_window_end: Optional[str]
    site_visit_findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


ALL_ENTITY_TYPES: List[str] = [
    "Employer",
    "CampaignCoordinator",
    "Campaign",
    "Pledge",
    "PledgeDesignation",
    "Agency",
    "AgencyReview",
    "AllocationCycle",
    "Panelist",
    "PanelAssignment",
    "AllocationRequest",
    "PanelScore",
    "OutcomeReport",
]
