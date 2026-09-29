"""Domain types for the Union Grievance & Arbitration Tracking API.

Entity shapes, status enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles and parties (PRD §2.1)
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    UNION_STEWARD = "UnionSteward"
    GRIEVANT = "Grievant"
    LABOR_RELATIONS_ANALYST = "LaborRelationsAnalyst"
    LABOR_RELATIONS_DIRECTOR = "LaborRelationsDirector"
    CHIEF_NEGOTIATOR = "ChiefNegotiator"
    ARBITRATION_ADMINISTRATOR = "ArbitrationAdministrator"


class Party(str, Enum):
    UNION = "UNION"
    EMPLOYER = "EMPLOYER"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class BargainingUnitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ClauseCategory(str, Enum):
    DISCIPLINE = "DISCIPLINE"
    PAY = "PAY"
    SENIORITY = "SENIORITY"
    SAFETY = "SAFETY"
    LEAVE = "LEAVE"
    SUBCONTRACTING = "SUBCONTRACTING"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    REINSTATED = "REINSTATED"


class Classification(str, Enum):
    PRODUCTION = "PRODUCTION"
    MAINTENANCE = "MAINTENANCE"
    CLERICAL = "CLERICAL"
    SUPERVISOR = "SUPERVISOR"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    STEP_MEETING_SCHEDULED = "STEP_MEETING_SCHEDULED"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    ANSWERED = "ANSWERED"
    APPEALED = "APPEALED"
    ARBITRATION_DEMANDED = "ARBITRATION_DEMANDED"
    AWARDED = "AWARDED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"
    CONSOLIDATED = "CONSOLIDATED"
    CLOSED = "CLOSED"


class TimelinessState(str, Enum):
    TIMELY = "TIMELY"
    TOLLED = "TOLLED"
    EMPLOYER_DEFAULT = "EMPLOYER_DEFAULT"
    UNION_DEFAULT = "UNION_DEFAULT"
    BARRED = "BARRED"


class CostPosture(str, Enum):
    COST_OK = "COST_OK"
    COST_WATCH = "COST_WATCH"
    COST_BREACH = "COST_BREACH"


class StepStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    ANSWERED = "ANSWERED"
    DEEMED_DENIED = "DEEMED_DENIED"
    CANCELLED = "CANCELLED"


class StepDisposition(str, Enum):
    GRANTED = "GRANTED"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    LAPSED = "LAPSED"
    VOIDED = "VOIDED"


class RemedyTerms(str, Enum):
    NONE = "NONE"
    RECORD_EXPUNGEMENT = "RECORD_EXPUNGEMENT"
    SENIORITY_RESTORATION = "SENIORITY_RESTORATION"
    POLICY_CHANGE = "POLICY_CHANGE"
    REINSTATEMENT = "REINSTATEMENT"


class AuthorityTier(str, Enum):
    ANALYST = "ANALYST"
    DIRECTOR = "DIRECTOR"
    NEGOTIATOR = "NEGOTIATOR"
    BOARD = "BOARD"


class OfferDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    COUNTER = "COUNTER"


class PrecedentOutcome(str, Enum):
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"
    SPLIT = "SPLIT"


class BindingScope(str, Enum):
    UNIT_WIDE = "UNIT_WIDE"
    DEPARTMENT = "DEPARTMENT"
    INDIVIDUAL = "INDIVIDUAL"


class PanelSource(str, Enum):
    AAA = "AAA"
    FMCS = "FMCS"
    PERMANENT_UMPIRE = "PERMANENT_UMPIRE"


class ArbitratorStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FULL = "FULL"
    INACTIVE = "INACTIVE"


class DemandStatus(str, Enum):
    DEMANDED = "DEMANDED"
    PANEL_ISSUED = "PANEL_ISSUED"
    STRIKING = "STRIKING"
    ARBITRATOR_SELECTED = "ARBITRATOR_SELECTED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    HEARD = "HEARD"
    AWARDED = "AWARDED"
    WITHDRAWN = "WITHDRAWN"
    SETTLED_PRE_HEARING = "SETTLED_PRE_HEARING"


class PrepStatus(str, Enum):
    PREP_NOT_STARTED = "PREP_NOT_STARTED"
    PREP_DEFICIENT = "PREP_DEFICIENT"
    EXHIBITS_FILED = "EXHIBITS_FILED"
    BRIEFS_FILED = "BRIEFS_FILED"
    PREP_READY = "PREP_READY"


class FilingType(str, Enum):
    EXHIBIT_LIST = "EXHIBIT_LIST"
    BRIEF = "BRIEF"
    STIPULATION = "STIPULATION"


class WitnessType(str, Enum):
    FACT = "FACT"
    EXPERT = "EXPERT"
    CHARACTER = "CHARACTER"


class WitnessStatus(str, Enum):
    INVITED = "INVITED"
    CONFIRMED = "CONFIRMED"
    TESTIFIED = "TESTIFIED"
    EXCUSED = "EXCUSED"
    NO_SHOW = "NO_SHOW"


class AwardOutcome(str, Enum):
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"
    SPLIT = "SPLIT"


class AwardStatus(str, Enum):
    ISSUED = "ISSUED"
    IMPLEMENTATION_PENDING = "IMPLEMENTATION_PENDING"
    PARTIALLY_IMPLEMENTED = "PARTIALLY_IMPLEMENTED"
    IMPLEMENTED = "IMPLEMENTED"
    COMPLIANCE_DISPUTED = "COMPLIANCE_DISPUTED"


class CostCategory(str, Enum):
    ARBITRATOR_FEE = "ARBITRATOR_FEE"
    TRANSCRIPT = "TRANSCRIPT"
    COUNSEL = "COUNSEL"
    RELEASE_TIME = "RELEASE_TIME"
    TRAVEL = "TRAVEL"
    FILING = "FILING"


class CostOrigin(str, Enum):
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


class CostEntryStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


# --------------------------------------------------------------------------
# Entity shapes
#
# Resources carrying id + created_at + updated_at + version (PRD §2.5).
# PrecedentCase and PanelStrike are the two exceptions and carry only
# id + created_at.
# --------------------------------------------------------------------------

class BargainingUnit(TypedDict):
    id: str
    name: str
    local_number: str
    contract_effective_date: str
    contract_expiry_date: str
    step1_response_days: int
    step2_response_days: int
    step3_response_days: int
    appeal_window_days: int
    filing_window_days: int
    arbitration_demand_days: int
    tolling_enabled: bool
    director_authority_cents: int
    negotiator_authority_cents: int
    precedent_deviation_tolerance_bps: int
    status: str
    open_grievance_count: int
    created_at: str
    updated_at: str
    version: int


class ContractClause(TypedDict):
    id: str
    bargaining_unit_id: str
    clause_number: str
    title: str
    category: str
    is_arbitrable: bool
    monetary_cap_cents: Optional[int]
    expedited: bool
    filed_count: int
    sustained_count: int
    denied_count: int
    sustain_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    bargaining_unit_id: str
    supervisor_id: Optional[str]
    full_name: str
    employee_number: str
    hire_date: str
    seniority_date: str
    hourly_rate_cents: int
    classification: str
    employment_status: str
    open_grievance_count: int
    closed_grievance_count: int
    sustained_against_count: int
    adverse_rate_bps: int
    witness_release_hours_ytd: float
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict):
    id: str
    bargaining_unit_id: str
    grievant_id: str
    respondent_supervisor_id: str
    clause_id: str
    consolidated_into_id: Optional[str]
    case_number: str
    statement: str
    incident_date: str
    discovery_date: str
    filed_at: str
    filed_by_steward_employee_id: str
    current_step: int
    status: str
    timeliness_state: str
    remedy_requested_cents: int
    back_pay_hours_claimed: float
    settled_amount_cents: int
    appeal_deadline_at: Optional[str]
    arbitration_deadline_at: Optional[str]
    total_cost_cents: int
    union_cost_share_cents: int
    employer_cost_share_cents: int
    cost_posture: str
    created_at: str
    updated_at: str
    version: int


class GrievanceStep(TypedDict):
    id: str
    grievance_id: str
    step_number: int
    status: str
    meeting_scheduled_at: str
    extension_days: int
    meeting_held_at: Optional[str]
    response_due_at: Optional[str]
    responded_at: Optional[str]
    disposition: Optional[str]
    response_summary: Optional[str]
    granted_amount_cents: int
    responded_by_user_id: Optional[str]
    late_by_days: int
    created_at: str
    updated_at: str
    version: int


class SettlementOffer(TypedDict):
    id: str
    grievance_id: str
    precedent_case_id: Optional[str]
    offering_party: str
    monetary_cents: int
    back_pay_hours: float
    remedy_terms: str
    precedent_setting: bool
    round_number: int
    exposure_cents: int
    authority_tier: str
    precedent_deviation_bps: Optional[int]
    status: str
    prepared_by_user_id: str
    authorized_by_user_id: Optional[str]
    authorized_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common fields exception — id and created_at only (PRD §2.5)
class PrecedentCase(TypedDict):
    id: str
    clause_id: str
    citation: str
    decided_on: str
    outcome: str
    monetary_value_cents: int
    binding_scope: str
    arbitrator_name: str
    cited_count: int
    created_at: str


class Arbitrator(TypedDict):
    id: str
    full_name: str
    panel_memberships: List[str]
    per_diem_cents: int
    cancellation_fee_cents: int
    travel_buffer_hours: int
    earliest_available_at: str
    max_concurrent_cases: int
    is_active: bool
    active_case_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ArbitrationDemand(TypedDict):
    id: str
    grievance_id: str
    selected_arbitrator_id: Optional[str]
    demanded_at: str
    demand_deadline_at: Optional[str]
    panel_source: str
    panel_size: int
    panel_arbitrator_ids: List[str]
    strike_turn: Optional[str]
    strikes_taken: int
    status: str
    prep_status: str
    exhibit_count: int
    hearing_start_at: Optional[str]
    hearing_end_at: Optional[str]
    brief_due_at: Optional[str]
    readiness_score: int
    estimated_cost_cents: int
    actual_cost_cents: int
    created_at: str
    updated_at: str
    version: int


# common fields exception — id and created_at only (PRD §2.5)
class PanelStrike(TypedDict):
    id: str
    arbitration_demand_id: str
    arbitrator_id: str
    struck_by: str
    strike_order: int
    struck_by_user_id: str
    created_at: str


class WitnessAssignment(TypedDict):
    id: str
    arbitration_demand_id: str
    employee_id: str
    witness_type: str
    called_by: str
    slot_start_at: str
    slot_end_at: str
    release_hours: float
    release_cost_cents: int
    status: str
    confirmed_by_user_id: Optional[str]
    release_cost_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    arbitration_demand_id: str
    issued_at: str
    outcome: str
    sustained_fraction_bps: int
    back_pay_hours_ordered: float
    mitigation_offset_cents: int
    interest_rate_bps: int
    interest_accrual_start: Optional[str]
    reinstatement_ordered: bool
    remedy_deadline_days: int
    gross_remedy_cents: int
    net_remedy_cents: int
    implemented_cents: int
    implementation_deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CostEntry(TypedDict):
    id: str
    grievance_id: str
    category: str
    amount_cents: int
    bearing_party: str
    incurred_at: str
    origin: str
    status: str
    void_reason: Optional[str]
    voided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
