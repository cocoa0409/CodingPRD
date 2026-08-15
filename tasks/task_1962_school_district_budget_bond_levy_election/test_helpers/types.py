"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    BUDGET_ANALYST = "BudgetAnalyst"
    BUSINESS_MANAGER = "BusinessManager"
    BOARD_CLERK = "BoardClerk"
    SUPERINTENDENT = "Superintendent"
    DISTRICT_TREASURER = "DistrictTreasurer"
    AUDITOR = "Auditor"


class FiscalYearStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EnrollmentProjectionStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


class BudgetVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    HEARING_HELD = "HEARING_HELD"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class BudgetLineStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class StaffingAllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    SUPERSEDED = "SUPERSEDED"


class PositionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    OPEN = "OPEN"
    FILLED = "FILLED"
    ELIMINATED = "ELIMINATED"


class RevenueEstimateStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RECERTIFIED = "RECERTIFIED"


class EavBasis(str, Enum):
    PRIOR = "PRIOR"
    CURRENT = "CURRENT"


class PublicHearingStatus(str, Enum):
    NOTICE_PUBLISHED = "NOTICE_PUBLISHED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class ElectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANVASSED = "CANVASSED"


class ElectionType(str, Enum):
    REGULAR = "REGULAR"
    SPECIAL = "SPECIAL"


class BondProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    BOARD_APPROVED = "BOARD_APPROVED"
    REFERRED = "REFERRED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class BondProjectStatus(str, Enum):
    PLANNED = "PLANNED"
    AUTHORIZED = "AUTHORIZED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BallotMeasureStatus(str, Enum):
    LANGUAGE_DRAFT = "LANGUAGE_DRAFT"
    LANGUAGE_CERTIFIED = "LANGUAGE_CERTIFIED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class PublicationType(str, Enum):
    FACTUAL = "FACTUAL"
    PROMOTIONAL = "PROMOTIONAL"


class DistrictPublicationStatus(str, Enum):
    PUBLISHED = "PUBLISHED"


class BondSaleStatus(str, Enum):
    PLANNED = "PLANNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    REVIEWED = "REVIEWED"
    FLAGGED = "FLAGGED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DISBURSED = "DISBURSED"
    RETAINAGE_RELEASED = "RETAINAGE_RELEASED"
    VOIDED = "VOIDED"


class CapitalPlanAmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GradeBand(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class FundCode(str, Enum):
    EDUCATION = "EDUCATION"
    OPERATIONS = "OPERATIONS"
    TRANSPORTATION = "TRANSPORTATION"
    DEBT_SERVICE = "DEBT_SERVICE"
    CAPITAL_PROJECTS = "CAPITAL_PROJECTS"


# ─── Entity payloads ─────────────────────────────────────────────────────────
# All entities except DistrictPublication carry id + created_at + updated_at +
# version (PRD §2.4). DistrictPublication is append-only: id + created_at only.

class FiscalYear(TypedDict, total=False):
    id: str
    label: str
    start_date: str
    end_date: str
    eav_current: float
    eav_prior: float
    prior_year_extension: float
    outstanding_debt_principal: float
    fte_ceiling: float
    authorized_fte_total: float
    open_position_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EnrollmentProjection(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    grade_band: str
    projected_pupils: int
    actual_pupils: Optional[int]
    weighted_pupils_projected: int
    weighted_pupils_certified: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetVersion(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    version_label: str
    total_appropriations: float
    hearing_held_date: Optional[str]
    adopted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict, total=False):
    id: str
    budget_version_id: str
    fund_code: str
    function_code: str
    object_code: str
    cost_center: str
    appropriation_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffingAllocation(TypedDict, total=False):
    id: str
    budget_version_id: str
    enrollment_projection_id: str
    grade_band: str
    required_fte: float
    allocated_fte: float
    positions_fte_total: float
    cost_estimate_projected: float
    cost_estimate_actual: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict, total=False):
    id: str
    staffing_allocation_id: str
    title: str
    fte: float
    base_salary: float
    incumbent_salary: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueEstimate(TypedDict, total=False):
    id: str
    budget_version_id: str
    operating_levy_request: float
    debt_service_levy: float
    other_revenue: float
    cpi_rate: float
    capped_operating_levy: float
    total_levy: float
    eav_basis: str
    state_aid: float
    operating_rate: float
    debt_service_rate: float
    total_tax_rate: float
    total_revenue: float
    state_aid_provisional: Optional[float]
    total_revenue_provisional: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PublicHearing(TypedDict, total=False):
    id: str
    budget_version_id: str
    venue: str
    hearing_date: str
    notice_publication_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Election(TypedDict, total=False):
    id: str
    election_date: str
    election_type: str
    canvassed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BondProposal(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    question_title: str
    purpose: str
    total_amount: float
    remaining_authorization: float
    available_proceeds: float
    passed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BondProject(TypedDict, total=False):
    id: str
    bond_proposal_id: str
    name: str
    site_code: str
    estimated_cost: float
    construction_start: str
    construction_end: str
    priority_rank: int
    authorized_amount: float
    spent_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BallotMeasure(TypedDict, total=False):
    id: str
    election_id: str
    bond_proposal_id: str
    ballot_language: str
    word_count: int
    drafted_by_user_id: str
    certified_by_user_id: Optional[str]
    yes_votes: Optional[int]
    no_votes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistrictPublication(TypedDict, total=False):
    # Append-only record (PRD §2.4): id + created_at only — NO updated_at,
    # NO version.
    id: str
    ballot_measure_id: str
    publication_type: str
    content: str
    published_by_user_id: str
    status: str
    created_at: str


class BondSale(TypedDict, total=False):
    id: str
    bond_proposal_id: str
    series_label: str
    par_amount: float
    premium: float
    issuance_costs: float
    sale_date: str
    net_proceeds: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProjectExpenditure(TypedDict, total=False):
    id: str
    bond_project_id: str
    vendor_name: str
    amount: float
    description: str
    retainage_amount: float
    disbursed_amount: float
    review_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class CapitalPlanAmendment(TypedDict, total=False):
    id: str
    bond_proposal_id: str
    reason: str
    adjustments: list
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
