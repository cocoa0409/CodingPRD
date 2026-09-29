"""TypedDict shapes and status enums for every entity in the API contract.

Field membership follows PRD 2.4: every entity carries the full quartet of
`id`, `created_at`, `updated_at` and `version` except the workload outing,
which carries only `id` and `created_at`.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class Role(str, Enum):
    FARM_DIRECTOR = "FarmDirector"
    MEDICAL_DIRECTOR = "MedicalDirector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AFFILIATE_OPERATOR = "AffiliateOperator"
    INTERNATIONAL_SCOUT = "InternationalScout"


ALL_ROLES = tuple(r.value for r in Role)


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class Posture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class SettlementStatus(str, Enum):
    NOT_SETTLED = "NOT_SETTLED"
    SETTLED = "SETTLED"


class FacilityStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    PROVISIONAL = "PROVISIONAL"
    DEFICIENT = "DEFICIENT"


class DeficiencyLevel(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    WAIVED = "WAIVED"


class AllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    RECALLED = "RECALLED"


class RosterStatus(str, Enum):
    RESERVE_LIST = "RESERVE_LIST"
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"


class MedicalStatus(str, Enum):
    PENDING_CLEARANCE = "PENDING_CLEARANCE"
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"


class ClearanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class AssignmentStatus(str, Enum):
    PENDING_CLEARANCE = "PENDING_CLEARANCE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACHIEVED = "ACHIEVED"
    LAPSED = "LAPSED"


class OptionYearStatus(str, Enum):
    CHARGED = "CHARGED"
    RESCINDED = "RESCINDED"


class ReportStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED_BY_LEAGUE = "REJECTED_BY_LEAGUE"
    VOIDED = "VOIDED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    HARD_CAPPED = "HARD_CAPPED"


class SigningStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
class Affiliate(TypedDict):
    id: str
    name: str
    level: str
    market_city: str
    meal_stipend_cents_per_day: int
    roster_limit: int
    reserve_slots: int
    housing_beds: int
    travel_standard_tier: str
    active_roster_count: int
    rehab_assignment_count: int
    reserve_list_count: int
    facility_score: str
    open_major_deficiency_count: int
    facility_status: str
    created_at: str
    updated_at: str
    version: int


class AffiliationAgreement(TypedDict):
    id: str
    affiliate_id: str
    term_start_date: str
    term_end_date: str
    facility_standard_tier: str
    club_reimbursement_cap_cents: int
    minimum_active_players: int
    required_staff_roles: List[str]
    housing_expense_cents: int
    meal_expense_cents: int
    travel_expense_cents: int
    upkeep_expense_cents: int
    audited_housing_expense_cents: Optional[int]
    audited_meal_expense_cents: Optional[int]
    audited_travel_expense_cents: Optional[int]
    audited_upkeep_expense_cents: Optional[int]
    provisional_club_obligation_cents: int
    final_club_obligation_cents: Optional[int]
    affiliate_overflow_cents: int
    settlement_status: str
    status: str
    posture: str
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FacilityStandardReview(TypedDict):
    id: str
    affiliate_id: str
    category: str
    review_date: str
    score: int
    deficiency_level: str
    status: str
    remediation_due_date: Optional[str]
    remediation_note: Optional[str]
    remediation_submitted_at: Optional[str]
    reopen_count: int
    is_overdue: bool
    waiver_granted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    discipline: str
    curriculum_version_certified: str
    certification_expires_on: str
    total_committed_fte_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffAllocation(TypedDict):
    id: str
    staff_member_id: str
    affiliate_id: str
    staff_role: str
    fte_pct: int
    effective_start: str
    effective_end: str
    curriculum_version: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    full_name: str
    origin: str
    signed_date: str
    service_days_accrued: int
    roster_status: str
    medical_status: str
    current_affiliate_id: Optional[str]
    is_on_domestic_reserve_list: bool
    option_years_used: int
    option_years_remaining: int
    workload_index: str
    workload_index_projected: str
    promotion_readiness: str
    created_at: str
    updated_at: str
    version: int


class MedicalClearance(TypedDict):
    id: str
    player_id: str
    clearance_type: str
    status: str
    requested_by_user_id: str
    issued_by_user_id: Optional[str]
    cleared_workload_ceiling_index: Optional[str]
    expires_on: Optional[str]
    restriction_note: Optional[str]
    is_expired: bool
    created_at: str
    updated_at: str
    version: int


class PlayerAssignment(TypedDict):
    id: str
    player_id: str
    affiliate_id: str
    assignment_type: str
    movement_reason: str
    effective_date: str
    end_date: str
    level_at_assignment: str
    workload_ceiling_index: str
    superseded_assignment_id: Optional[str]
    projected_optional_days: int
    option_year_charged: bool
    initiated_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DevelopmentPlan(TypedDict):
    id: str
    assignment_id: str
    target_level: str
    curriculum_version: str
    curriculum_modules: List[str]
    workload_limit_weekly_index: str
    completed_module_count: int
    completion_pct: str
    review_cycle_count: int
    revision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkloadLog(TypedDict):
    """PRD 2.4: a workload log carries only `id` and `created_at`."""

    id: str
    assignment_id: str
    log_date: str
    pitches_thrown: int
    innings_pitched: str
    high_intensity_minutes: int
    is_rehab_outing: bool
    created_at: str


class OptionYearRecord(TypedDict):
    id: str
    triggering_assignment_id: str
    season_year: int
    optional_days: int
    charged_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransactionReport(TypedDict):
    id: str
    assignment_id: str
    transaction_type: str
    status: str
    filing_deadline: str
    filed_at: Optional[str]
    certified_by_user_id: Optional[str]
    initiated_by_user_id: str
    league_note: Optional[str]
    refile_count: int
    is_late: bool
    late_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class SigningPool(TypedDict):
    id: str
    season_year: int
    base_pool_cents: int
    trade_adjustment_cents: int
    forfeited_cents: int
    allocated_cents: int
    overage_tax_accrued_cents: int
    effective_pool_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InternationalSigning(TypedDict):
    id: str
    pool_id: str
    player_id: str
    academy_affiliate_id: str
    bonus_cents: int
    pool_charge_cents: int
    overage_tax_cents: int
    tier3_breach: bool
    rejection_reason: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Entities that carry the full audit quartet (PRD 2.4).
FULL_QUARTET_ENTITIES = (
    "Affiliate",
    "AffiliationAgreement",
    "FacilityStandardReview",
    "StaffMember",
    "StaffAllocation",
    "Player",
    "PlayerAssignment",
    "DevelopmentPlan",
    "MedicalClearance",
    "OptionYearRecord",
    "SigningPool",
    "InternationalSigning",
    "TransactionReport",
)
