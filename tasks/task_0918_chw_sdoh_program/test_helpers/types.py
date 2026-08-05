"""Domain types for the Community Health Worker & SDOH Program API.

Entity shapes, status enums and the role enum, all named exactly as the PRD
names them. Every one of the fifteen entity types carries `id`, `created_at`,
`updated_at` and `version`.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    CHW = "CHW"
    SUPERVISOR = "Supervisor"
    PROGRAM_ADMIN = "ProgramAdmin"
    BILLING_SPECIALIST = "BillingSpecialist"
    RESOURCE_PARTNER = "ResourcePartner"


ALL_ROLES = [r.value for r in UserRole]


# ─── Status enums ──────────────────────────────────────────────────────────

class CredentialLevel(str, Enum):
    CHW_BASIC = "CHW_BASIC"
    CHW_SENIOR = "CHW_SENIOR"
    CHW_SUPERVISOR = "CHW_SUPERVISOR"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"


class EnrollmentStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    ENROLLED = "ENROLLED"
    DISENROLLED = "DISENROLLED"


class GateStatus(str, Enum):
    OPEN = "OPEN"
    RECORDS_HOLD = "RECORDS_HOLD"


class RiskTier(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EnrollmentAction(str, Enum):
    ENROLL = "ENROLL"
    DISENROLL = "DISENROLL"
    REENROLL = "REENROLL"


class RecordsHoldAction(str, Enum):
    PLACE = "PLACE"
    RELEASE = "RELEASE"


class InstrumentStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ScreeningStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AMENDED = "AMENDED"
    SUPERSEDED = "SUPERSEDED"


class SdohDomain(str, Enum):
    FOOD = "FOOD"
    HOUSING = "HOUSING"
    TRANSPORT = "TRANSPORT"
    EMPLOYMENT = "EMPLOYMENT"
    HEALTH_LITERACY = "HEALTH_LITERACY"


class OrgType(str, Enum):
    FOOD = "FOOD"
    HOUSING = "HOUSING"
    TRANSPORT = "TRANSPORT"


class OrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OrgAction(str, Enum):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class UnitType(str, Enum):
    FOOD_BOX = "FOOD_BOX"
    HOUSING_VOUCHER = "HOUSING_VOUCHER"
    TRANSPORT_RIDE = "TRANSPORT_RIDE"


class AvailabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    EXHAUSTED = "EXHAUSTED"


class CriterionType(str, Enum):
    INCOME_BAND = "INCOME_BAND"
    GEOGRAPHY = "GEOGRAPHY"
    HOUSEHOLD_SIZE = "HOUSEHOLD_SIZE"
    PROGRAM_ENROLLMENT = "PROGRAM_ENROLLMENT"
    CATEGORICAL_EXCLUSION = "CATEGORICAL_EXCLUSION"


class Urgency(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENT = "EMERGENT"


class ReferralStatus(str, Enum):
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SERVICE_DELIVERED = "SERVICE_DELIVERED"
    CLOSED = "CLOSED"
    LAPSED = "LAPSED"


class ReferralDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class LapseReason(str, Enum):
    ACK_SLA_EXPIRED = "ACK_SLA_EXPIRED"
    HOLD_EXPIRED = "HOLD_EXPIRED"
    RECORDS_HOLD = "RECORDS_HOLD"


class SchedulingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class DocumentationStatus(str, Enum):
    DRAFT = "DRAFT"
    ATTESTED = "ATTESTED"
    AMENDED = "AMENDED"
    VOIDED = "VOIDED"


class DocumentationAction(str, Enum):
    AMEND = "AMEND"
    VOID = "VOID"


class GoalDirection(str, Enum):
    INCREASE_GOOD = "INCREASE_GOOD"
    DECREASE_GOOD = "DECREASE_GOOD"


class GoalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MET = "MET"
    NOT_MET = "NOT_MET"
    DEFERRED = "DEFERRED"


class EncounterStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    VOIDED = "VOIDED"


class FundingSource(str, Enum):
    UNFUNDED = "UNFUNDED"
    PAYER = "PAYER"
    GRANT = "GRANT"


class ClaimBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    OVERTURNED = "OVERTURNED"
    UPHELD = "UPHELD"


class AdjudicationOutcome(str, Enum):
    PAID = "PAID"
    DENIED = "DENIED"


class AppealDecision(str, Enum):
    OVERTURNED = "OVERTURNED"
    UPHELD = "UPHELD"


class AwardStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CostCategory(str, Enum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    DOCUMENTATION = "DOCUMENTATION"


class ChargeLineStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ReversalReason(str, Enum):
    MANUAL_REVERSAL = "MANUAL_REVERSAL"
    ENCOUNTER_VOIDED = "ENCOUNTER_VOIDED"


class SourceFlag(str, Enum):
    CRITICAL_SDOH_FINDING = "CRITICAL_SDOH_FINDING"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    REFERRAL_UNFULFILLED = "REFERRAL_UNFULFILLED"
    GOAL_NOT_MET = "GOAL_NOT_MET"
    MANUAL = "MANUAL"


class EscalationStatus(str, Enum):
    OPEN_TIER_1 = "OPEN_TIER_1"
    OPEN_TIER_2 = "OPEN_TIER_2"
    OPEN_TIER_3 = "OPEN_TIER_3"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class ResolutionReason(str, Enum):
    MANUAL_RESOLUTION = "MANUAL_RESOLUTION"
    RESOURCE_RESTORED = "RESOURCE_RESTORED"


class SweepType(str, Enum):
    REFERRAL_LAPSE = "REFERRAL_LAPSE"
    OFFERING_HOLD_EXPIRY = "OFFERING_HOLD_EXPIRY"
    ESCALATION_PROMOTION = "ESCALATION_PROMOTION"


class DenominatorBasis(str, Enum):
    ENROLLED_ONLY = "ENROLLED_ONLY"
    EVER_ENROLLED = "EVER_ENROLLED"


OPEN_ESCALATION_STATUSES = [
    EscalationStatus.OPEN_TIER_1.value,
    EscalationStatus.OPEN_TIER_2.value,
    EscalationStatus.OPEN_TIER_3.value,
]


# ─── Entity shapes ─────────────────────────────────────────────────────────

class CommunityHealthWorker(TypedDict):
    id: str
    full_name: str
    employee_code: str
    credential_level: str
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    household_size: int
    monthly_income_cents: int
    residence_zip: str
    program_enrollments: List[str]
    categorical_exclusions: List[str]
    child_in_household: bool
    address_safety_flag: bool
    enrollment_status: str
    gate_status: str
    gate_reason: Optional[str]
    risk_score: float
    risk_tier: str
    risk_tier_effective_at: Optional[str]
    unfulfilled_referral_count: int
    created_at: str
    updated_at: str
    version: int


class ScreeningInstrument(TypedDict):
    id: str
    name: str
    version_label: str
    domain_weights: dict
    rescreen_cadence_days: int
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Screening(TypedDict):
    id: str
    patient_id: str
    instrument_id: str
    domain_scores: dict
    anchor_screened_at: str
    latest_response_at: str
    weighted_score: float
    risk_tier: str
    amendment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ResourceOrg(TypedDict):
    id: str
    name: str
    org_type: str
    service_zips: List[str]
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ResourceOffering(TypedDict):
    id: str
    resource_org_id: str
    unit_type: str
    capacity_total: int
    available_units: int
    allocated_units: int
    delivered_units: int
    released_units: int
    expired_units: int
    lifetime_allocated_units: int
    availability_state: str
    exhausted_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityCriterion(TypedDict):
    id: str
    offering_id: str
    criterion_type: str
    evaluation_rank: int
    max_monthly_income_cents: Optional[int]
    allowed_zips: List[str]
    min_household_size: Optional[int]
    max_household_size: Optional[int]
    required_program_code: Optional[str]
    excluded_flag_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    offering_id: str
    opened_by_chw_id: str
    parent_referral_id: Optional[str]
    root_referral_id: str
    urgency: str
    units_requested: int
    status: str
    sent_at: str
    ack_deadline_at: str
    hold_expires_at: str
    reroute_count: int
    decline_reason: Optional[str]
    lapse_reason: Optional[str]
    delivered_at: Optional[str]
    closed_at: Optional[str]
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HomeVisit(TypedDict):
    id: str
    patient_id: str
    assigned_chw_id: str
    second_chw_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    two_person_required: bool
    scheduling_status: str
    documentation_status: str
    completed_at: Optional[str]
    attested_at: Optional[str]
    amendment_count: int
    visit_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CarePlanGoal(TypedDict):
    id: str
    patient_id: str
    domain: str
    direction: str
    baseline_value: float
    target_value: float
    current_value: float
    progress_pct: float
    status: str
    review_cycle_days: int
    review_due_at: str
    reopen_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    patient_id: str
    chw_id: str
    home_visit_id: Optional[str]
    funding_claim_id: Optional[str]
    encounter_date: str
    service_month: str
    direct_minutes: int
    indirect_minutes: int
    travel_minutes: int
    documentation_minutes: int
    travel_miles: float
    total_minutes: int
    raw_billable_minutes: int
    billable_minutes: int
    travel_reimbursement_cents: int
    funding_source: str
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayerClaim(TypedDict):
    id: str
    patient_id: str
    service_month: str
    basis: str
    claimed_minutes: int
    claimed_encounter_count: int
    billing_code: str
    units: int
    allowed_amount_cents: int
    status: str
    denial_reason: Optional[str]
    denied_at: Optional[str]
    appealed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantAward(TypedDict):
    id: str
    funder_name: str
    period_start: str
    period_end: str
    budget_cap_cents: int
    indirect_rate_pct: float
    allowable_cost_categories: List[str]
    committed_cents: int
    remaining_budget_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantChargeLine(TypedDict):
    id: str
    grant_award_id: str
    encounter_id: str
    charged_minutes: int
    hourly_rate_cents: int
    direct_amount_cents: int
    indirect_amount_cents: int
    total_amount_cents: int
    reversed_at: Optional[str]
    reversal_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Escalation(TypedDict):
    id: str
    patient_id: str
    source_flag: str
    source_referral_id: Optional[str]
    source_screening_id: Optional[str]
    blocking_offering_id: Optional[str]
    status: str
    current_tier: int
    opened_by_user_id: str
    acknowledged_by_user_id: Optional[str]
    tier_entered_at: str
    ack_deadline_at: str
    promotion_count: int
    resolution_reason: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int
