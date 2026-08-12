"""Domain types: entity TypedDicts, status enums, role enum.

Field inventories follow the PRD's per-resource narratives in section 3.
All resources carry the common system fields id / created_at / updated_at /
version (PRD section on common resource properties).
"""
from enum import Enum
from typing import Optional, List, TypedDict


class UserRole(str, Enum):
    DECLARANT_EXECUTIVE = "DeclarantExecutive"
    DECLARANT_CONTROLLER = "DeclarantController"
    BUILDER_REP = "BuilderRep"
    ASSOCIATION_DIRECTOR = "AssociationDirector"
    OWNER_DIRECTOR = "OwnerDirector"
    DESIGN_REVIEWER = "DesignReviewer"
    LIFESTYLE_COORDINATOR = "LifestyleCoordinator"
    HOMEOWNER_RESIDENT = "HomeownerResident"
    PLATFORM_ADMIN = "PlatformAdmin"


class CommunityStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    TURNOVER_RECORDED = "TURNOVER_RECORDED"


class TransitionStage(str, Enum):
    DECLARANT_CONTROL = "DECLARANT_CONTROL"
    OWNER_REPRESENTATION = "OWNER_REPRESENTATION"
    PARITY = "PARITY"
    OWNER_MAJORITY = "OWNER_MAJORITY"
    TURNOVER_COMPLETE = "TURNOVER_COMPLETE"


class PhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    SALES_OPEN = "SALES_OPEN"
    DELIVERING = "DELIVERING"
    CLOSED_OUT = "CLOSED_OUT"
    CANCELLED = "CANCELLED"


class AmenityType(str, Enum):
    CLUBHOUSE = "CLUBHOUSE"
    POOL = "POOL"
    PARK = "PARK"
    TRAIL_NETWORK = "TRAIL_NETWORK"
    FITNESS_CENTER = "FITNESS_CENTER"
    EVENT_LAWN = "EVENT_LAWN"


class AmenityStatus(str, Enum):
    COMMITTED = "COMMITTED"
    IN_DESIGN = "IN_DESIGN"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    OPEN = "OPEN"
    DELINQUENT = "DELINQUENT"


class BuilderStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class CreditTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    TERMINATED = "TERMINATED"


class TrancheStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    MISSED = "MISSED"
    CURED = "CURED"
    WAIVED = "WAIVED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    PLATTED = "PLATTED"
    OFFERED = "OFFERED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class ClosingStatus(str, Enum):
    PENDING = "PENDING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    RESCINDED = "RESCINDED"


class BudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    PENDING_RATIFICATION = "PENDING_RATIFICATION"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LineItemCategory(str, Enum):
    LANDSCAPE_MAINTENANCE = "LANDSCAPE_MAINTENANCE"
    AMENITY_OPERATIONS = "AMENITY_OPERATIONS"
    UTILITIES = "UTILITIES"
    MANAGEMENT = "MANAGEMENT"
    INSURANCE = "INSURANCE"
    RESERVE_CONTRIBUTION = "RESERVE_CONTRIBUTION"
    EVENTS_PROGRAMMING = "EVENTS_PROGRAMMING"
    CONTINGENCY = "CONTINGENCY"


class RateStatus(str, Enum):
    CALCULATED = "CALCULATED"
    ARMED = "ARMED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class AdvanceStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    PARTIALLY_REIMBURSED = "PARTIALLY_REIMBURSED"
    REIMBURSED = "REIMBURSED"


class LevyStatus(str, Enum):
    PLANNED = "PLANNED"
    COLLECTED = "COLLECTED"


class PaymentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CERTIFIED = "CERTIFIED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class ProjectType(str, Enum):
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"
    EXTERIOR_MODIFICATION = "EXTERIOR_MODIFICATION"
    LANDSCAPE = "LANDSCAPE"
    ADDITION = "ADDITION"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    DENIED = "DENIED"
    RESUBMITTED = "RESUBMITTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class ViolationType(str, Enum):
    UNAPPROVED_MODIFICATION = "UNAPPROVED_MODIFICATION"
    NONCONFORMING_MATERIALS = "NONCONFORMING_MATERIALS"
    SETBACK = "SETBACK"
    LANDSCAPE_DEADLINE = "LANDSCAPE_DEADLINE"


class ViolationStatus(str, Enum):
    REPORTED = "REPORTED"
    NOTICE_SENT = "NOTICE_SENT"
    CURED = "CURED"
    ESCALATED = "ESCALATED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    FINED = "FINED"
    PAID = "PAID"
    APPEALED = "APPEALED"
    DISMISSED = "DISMISSED"


class Venue(str, Enum):
    CLUBHOUSE = "CLUBHOUSE"
    POOL_DECK = "POOL_DECK"
    EVENT_LAWN = "EVENT_LAWN"
    SALES_CENTER = "SALES_CENTER"


class EventStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RsvpStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ResidentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    PURCHASER = "PURCHASER"
    OWNER = "OWNER"
    FORMER = "FORMER"


class NoticeType(str, Enum):
    ASSESSMENT_CHANGE = "ASSESSMENT_CHANGE"
    TRANSITION_UPDATE = "TRANSITION_UPDATE"
    AMENITY_DELINQUENCY = "AMENITY_DELINQUENCY"
    GENERAL_MEETING = "GENERAL_MEETING"
    BUDGET_ADOPTION = "BUDGET_ADOPTION"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class SeatClass(str, Enum):
    DECLARANT_APPOINTED = "DECLARANT_APPOINTED"
    OWNER_ELECTED = "OWNER_ELECTED"


class SeatStatus(str, Enum):
    FILLED = "FILLED"
    VACANT = "VACANT"
    ELECTION_CALLED = "ELECTION_CALLED"
    LAPSED = "LAPSED"


class AppealOutcome(str, Enum):
    APPEAL_UPHELD = "APPEAL_UPHELD"
    APPEAL_DENIED = "APPEAL_DENIED"


class Community(TypedDict, total=False):
    id: str
    community_name: str
    total_planned_units: int
    status: str
    closed_unit_count: int
    closed_unit_pct: float
    transition_stage: str
    created_at: str
    updated_at: str
    version: int


class DevelopmentPhase(TypedDict, total=False):
    id: str
    community_id: str
    phase_name: str
    sequence_no: int
    planned_lot_count: int
    closed_lot_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Amenity(TypedDict, total=False):
    id: str
    community_id: str
    amenity_type: str
    trigger_phase_id: Optional[str]
    trigger_unit_count: Optional[int]
    hard_deadline_date: str
    budgeted_cost_cents: int
    delinquency_recorded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Builder(TypedDict, total=False):
    id: str
    community_id: str
    legal_name: str
    credit_tier: str
    standing: str
    total_lots_purchased: int
    created_at: str
    updated_at: str
    version: int


class LotPurchaseAgreement(TypedDict, total=False):
    id: str
    community_id: str
    builder_id: str
    phase_id: str
    base_price_per_lot_cents: int
    annual_escalation_pct: float
    penalty_per_lot_per_day_cents: int
    earnest_money_cents: int
    total_lots_committed: int
    execution_date: Optional[str]
    lots_closed_count: int
    forfeited_earnest_money_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TakedownTranche(TypedDict, total=False):
    id: str
    agreement_id: str
    tranche_no: int
    due_date: str
    lot_count_due: int
    lots_credited: int
    cure_deadline: str
    accrued_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    community_id: str
    phase_id: str
    parcel_number: str
    lot_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LotClosing(TypedDict, total=False):
    id: str
    community_id: str
    agreement_id: str
    lot_id: str
    owner_resident_id: Optional[str]
    closing_date: Optional[str]
    escalated_base_cents: int
    premium_cents: int
    price_cents: int
    credited_tranche_id: Optional[str]
    is_surplus: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AssociationBudget(TypedDict, total=False):
    id: str
    community_id: str
    fiscal_year: int
    amendment_of_id: Optional[str]
    non_assessment_income_cents: int
    total_expense_cents: int
    reserve_cents: int
    adopted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetLineItem(TypedDict, total=False):
    id: str
    budget_id: str
    category: str
    amount_cents: int
    is_reserve: bool
    created_at: str
    updated_at: str
    version: int


class AssessmentRate(TypedDict, total=False):
    id: str
    community_id: str
    budget_id: str
    fiscal_year: int
    subsidy_elected: bool
    per_unit_annual_cents: int
    quarterly_installments_cents: List[int]
    prior_rate_id: Optional[str]
    prior_per_unit_cents: Optional[int]
    increase_pct: Optional[float]
    declarant_subsidy_cents: int
    cap_override_approved_by: Optional[str]
    cap_override_ratified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementDistrict(TypedDict, total=False):
    id: str
    community_id: str
    district_name: str
    interest_rate_annual_pct: float
    advance_principal_cents: int
    outstanding_principal_cents: int
    provisional_interest_cents: int
    certified_interest_to_date_cents: int
    available_funds_cents: int
    created_at: str
    updated_at: str
    version: int


class InfrastructureAdvance(TypedDict, total=False):
    id: str
    district_id: str
    amount_cents: int
    advance_date: str
    description: Optional[str]
    reimbursed_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistrictLevy(TypedDict, total=False):
    id: str
    district_id: str
    levy_year: int
    amount_cents: int
    collected_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementPayment(TypedDict, total=False):
    id: str
    district_id: str
    requested_by_user_id: str
    amount_cents: int
    certified_interest_cents: int
    certified_principal_cents: int
    certified_at: Optional[str]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DesignReviewApplication(TypedDict, total=False):
    id: str
    community_id: str
    lot_id: str
    applicant_builder_id: Optional[str]
    applicant_resident_id: Optional[str]
    project_type: str
    submission_round: int
    review_fee_cents: int
    reviewer_user_id: Optional[str]
    denied_by_user_id: Optional[str]
    conditions_text: Optional[str]
    construction_start_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DesignViolation(TypedDict, total=False):
    id: str
    community_id: str
    lot_id: str
    respondent_resident_id: Optional[str]
    respondent_builder_id: Optional[str]
    violation_type: str
    cure_deadline: Optional[str]
    days_late: int
    fine_cents: int
    cured_at: Optional[str]
    fined_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommunityEvent(TypedDict, total=False):
    id: str
    community_id: str
    title: str
    venue: str
    start_at: str
    end_at: str
    capacity: int
    cost_cents: int
    charged_budget_id: Optional[str]
    confirmed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventRsvp(TypedDict, total=False):
    id: str
    event_id: str
    resident_id: str
    party_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesCenterAppointment(TypedDict, total=False):
    id: str
    community_id: str
    agent_name: str
    visitor_name: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict, total=False):
    id: str
    community_id: str
    lot_id: Optional[str]
    full_name: str
    email: str
    owner_since: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ResidentNotice(TypedDict, total=False):
    id: str
    community_id: str
    notice_type: str
    subject: str
    body: str
    send_at: str
    sent_at: Optional[str]
    effective_date: Optional[str]
    budget_id: Optional[str]
    assessment_rate_id: Optional[str]
    supersedes_notice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardSeat(TypedDict, total=False):
    id: str
    community_id: str
    seat_no: int
    seat_class: str
    holder_name: Optional[str]
    holder_resident_id: Optional[str]
    eligible_voter_count: Optional[int]
    election_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
