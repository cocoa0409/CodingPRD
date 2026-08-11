"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    RECRUITER = "Recruiter"
    CONTRACT_ADMINISTRATOR = "ContractAdministrator"
    CREDENTIALING_SPECIALIST = "CredentialingSpecialist"
    PRACTICE_MANAGER = "PracticeManager"
    FINANCE_ANALYST = "FinanceAnalyst"
    ONBOARDING_DIRECTOR = "OnboardingDirector"
    PHYSICIAN = "Physician"
    MENTOR_PHYSICIAN = "MentorPhysician"
    SYSTEM_OPERATOR = "SystemOperator"


class Specialty(str, Enum):
    FAMILY_MEDICINE = "FAMILY_MEDICINE"
    INTERNAL_MEDICINE = "INTERNAL_MEDICINE"
    CARDIOLOGY = "CARDIOLOGY"
    ORTHOPEDICS = "ORTHOPEDICS"
    PEDIATRICS = "PEDIATRICS"


class HireType(str, Enum):
    NEW_GRAD = "NEW_GRAD"
    EXPERIENCED = "EXPERIENCED"
    LEADERSHIP = "LEADERSHIP"


class PhysicianStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SEPARATED = "SEPARATED"


class CaseStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    HIRED = "HIRED"
    SEPARATED = "SEPARATED"


class CredentialStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class TrainingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class PracticeStatus(str, Enum):
    PLANNING = "PLANNING"
    BUILDING = "BUILDING"
    READY = "READY"


class Posture(str, Enum):
    PRE_CONTRACT = "PRE_CONTRACT"
    CREDENTIALING = "CREDENTIALING"
    RAMP_PREP = "RAMP_PREP"
    GO_LIVE_READY = "GO_LIVE_READY"
    LIVE = "LIVE"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    EXTENDED = "EXTENDED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class CredentialItemStatus(str, Enum):
    PENDING = "PENDING"
    DOCS_SUBMITTED = "DOCS_SUBMITTED"
    VERIFIED = "VERIFIED"
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    LAPSED = "LAPSED"


class CredentialItemType(str, Enum):
    STATE_LICENSE = "STATE_LICENSE"
    DEA_REGISTRATION = "DEA_REGISTRATION"
    BOARD_CERTIFICATION = "BOARD_CERTIFICATION"
    PAYER_ENROLLMENT_MEDICARE = "PAYER_ENROLLMENT_MEDICARE"
    PAYER_ENROLLMENT_COMMERCIAL = "PAYER_ENROLLMENT_COMMERCIAL"
    HOSPITAL_PRIVILEGES = "HOSPITAL_PRIVILEGES"


class TrainingPlanStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_SIGNOFF = "AWAITING_SIGNOFF"
    COMPLETE = "COMPLETE"


class ModuleCode(str, Enum):
    EHR_FUNDAMENTALS = "EHR_FUNDAMENTALS"
    ORDER_ENTRY = "ORDER_ENTRY"
    NOTE_TEMPLATES = "NOTE_TEMPLATES"
    BILLING = "BILLING"


class TrainingModuleStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BlockType(str, Enum):
    CLINIC = "CLINIC"
    PROCEDURE = "PROCEDURE"
    OR = "OR"
    ADMIN = "ADMIN"


class ScheduleTemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PanelStatus(str, Enum):
    NOT_OPEN = "NOT_OPEN"
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class EventType(str, Enum):
    COMMUNITY_TALK = "COMMUNITY_TALK"
    REFERRAL_DINNER = "REFERRAL_DINNER"
    MEDIA = "MEDIA"
    OPEN_HOUSE = "OPEN_HOUSE"


class CampaignEventStatus(str, Enum):
    PLANNED = "PLANNED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class GuaranteeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    REPORTED = "REPORTED"
    ATTESTED = "ATTESTED"
    LAPSED = "LAPSED"


class MentorshipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"


class DayMarker(str, Enum):
    D30 = "D30"
    D90 = "D90"
    D180 = "D180"
    D270 = "D270"
    D365 = "D365"


class Sentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    CONCERN = "CONCERN"
    CRISIS = "CRISIS"


class SnapshotVariant(str, Enum):
    TRAILING = "TRAILING"
    LEADING = "LEADING"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# --- Entity TypedDicts -------------------------------------------------------
# Common fields (PRD §2.5): id, created_at, updated_at, version on every
# primary resource; CheckIn and RetentionRiskSnapshot carry only id + created_at.


class Physician(TypedDict, total=False):
    id: str
    full_name: str
    specialty: str
    email: str
    hire_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OnboardingCase(TypedDict, total=False):
    id: str
    physician_id: str
    target_start_date: str
    actual_start_date: Optional[str]
    case_status: str
    credential_status: str
    training_status: str
    practice_status: str
    posture: str
    weekly_active_minutes: int
    attained_milestone_count: int
    missed_milestone_count: int
    latest_risk_score: Optional[float]
    latest_risk_band: Optional[str]
    at_risk: bool
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    base_salary_cents: int
    signing_bonus_cents: int
    guarantee_monthly_cents: int
    guarantee_term_months: int
    panel_capacity: int
    proposed_start_date: str
    expires_at: str
    negotiation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CredentialItem(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    item_type: str
    payer_code: Optional[str]
    depends_on_item_ids: List[str]
    document_ref: str
    expires_on: Optional[str]
    submitted_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    blocked_from_status: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingPlan(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    required_module_count: int
    templates_required: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingModule(TypedDict, total=False):
    id: str
    training_plan_id: str
    module_code: str
    required: bool
    scheduled_on: Optional[str]
    score: Optional[int]
    templates_built_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduleTemplate(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    weekday: int
    start_minute: int
    end_minute: int
    block_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Panel(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    capacity: int
    current_size: int
    opened_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReferralCampaign(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    name: str
    budget_cents: int
    spent_cents: int
    referrals_attributed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CampaignEvent(TypedDict, total=False):
    id: str
    campaign_id: str
    event_type: str
    start_date: str
    end_date: str
    cost_cents: int
    venue: str
    referrals_generated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncomeGuarantee(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    monthly_guarantee_cents: int
    term_months: int
    start_month: str
    months_reconciled: int
    total_advanced_cents: int
    projected_total_draw_cents: int
    forgiveness_accrued_cents: int
    total_repaid_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RampMilestone(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    month_offset: int
    target_wrvu: int
    actual_wrvu: Optional[int]
    collections_cents: Optional[int]
    attained: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class MentorshipAssignment(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    mentor_physician_id: str
    checkins_recorded: int
    escalated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false (PRD §2.5) — ONLY id + created_at beside domain fields.
class CheckIn(TypedDict, total=False):
    id: str
    mentorship_id: str
    day_marker: str
    sentiment: str
    occurred_on: str
    notes: Optional[str]
    created_at: str


# common_fields: false (PRD §2.5) — ONLY id + created_at beside domain fields.
class RetentionRiskSnapshot(TypedDict, total=False):
    id: str
    onboarding_case_id: str
    variant: str
    milestone_risk: float
    panel_risk: float
    sentiment_risk: float
    schedule_risk: float
    score: float
    risk_band: str
    created_at: str
