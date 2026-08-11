"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BENEFITS_ADMIN = "BenefitsAdmin"
    EMPLOYEE = "Employee"
    COACH = "Coach"
    VENDOR_MANAGER = "VendorManager"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class ParticipationStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ScreeningStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESULTED = "RESULTED"
    NO_SHOW = "NO_SHOW"


class ChallengeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class ChallengeParticipationStatus(str, Enum):
    JOINED = "JOINED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ActivityType(str, Enum):
    STEPS = "STEPS"
    MINUTES = "MINUTES"
    VISITS = "VISITS"


class LedgerKind(str, Enum):
    EARNED = "EARNED"
    BONUS = "BONUS"
    ADJUSTED = "ADJUSTED"


class LedgerStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    POSTED = "POSTED"
    EXPIRED = "EXPIRED"


class AwardTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AwardVariant(str, Enum):
    STANDARD = "STANDARD"
    REASONABLE_ALTERNATIVE = "REASONABLE_ALTERNATIVE"


class AwardStatus(str, Enum):
    PROJECTED = "PROJECTED"
    CONFIRMED = "CONFIRMED"
    APPLIED = "APPLIED"
    DISPUTED = "DISPUTED"


class ReferralReason(str, Enum):
    HIGH_RISK = "HIGH_RISK"
    TOBACCO_CESSATION = "TOBACCO_CESSATION"
    RA_REQUEST = "RA_REQUEST"


class ReferralSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_RISK = "AUTO_RISK"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    ENGAGED = "ENGAGED"
    DISCHARGED = "DISCHARGED"
    DECLINED = "DECLINED"


class ReferralOutcome(str, Enum):
    GOALS_MET = "GOALS_MET"
    GOALS_NOT_MET = "GOALS_NOT_MET"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class InvoiceLineType(str, Enum):
    MEMBER_MONTH = "MEMBER_MONTH"
    COACHING_SESSION = "COACHING_SESSION"
    ADJUSTMENT = "ADJUSTMENT"


class ReportStatus(str, Enum):
    GENERATED = "GENERATED"
    PUBLISHED = "PUBLISHED"


# --- Entity payloads (PRD §2.4 common fields: id, created_at, updated_at, version) ---

class Employer(TypedDict, total=False):
    id: str
    name: str
    annual_self_only_premium_cents: int
    tobacco_surcharge_cents: int
    pmpm_fee_cents: int
    coaching_session_fee_cents: int
    k_anonymity_threshold: int
    kiosk_capacity: int
    invoice_approval_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    employer_id: str
    email: str
    full_name: str
    department: str
    hire_date: str
    tobacco_attested: bool
    created_at: str
    updated_at: str
    version: int


class WellnessProgram(TypedDict, total=False):
    id: str
    employer_id: str
    name: str
    plan_year_start: str
    plan_year_end: str
    bronze_threshold: int
    silver_threshold: int
    gold_threshold: int
    bronze_award_cents: int
    silver_award_cents: int
    gold_award_cents: int
    premium_cap_pct: float
    coaching_required_sessions: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    ra_eligible: bool
    participation_status: str
    verification_status: str
    points_balance_provisional: int
    points_balance_settled: int
    auto_referral_count: int
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# HealthAssessment is an immutable scoring record: only id + created_at (PRD §2.4).
class HealthAssessment(TypedDict, total=False):
    id: str
    enrollment_id: str
    answers: list
    risk_score: int
    risk_band: str
    created_at: str


class BiometricScreening(TypedDict, total=False):
    id: str
    enrollment_id: str
    clinic_location: str
    slot_start: str
    slot_end: str
    bmi: float
    systolic_bp: int
    total_cholesterol: int
    glucose: int
    targets_met: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Challenge(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    activity_type: str
    goal_quantity: int
    points_reward: int
    starts_at: str
    ends_at: str
    completed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChallengeParticipation(TypedDict, total=False):
    id: str
    challenge_id: str
    enrollment_id: str
    progress_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ActivityEvent is an immutable ingestion record: only id + created_at (PRD §2.4).
class ActivityEvent(TypedDict, total=False):
    id: str
    enrollment_id: str
    device_source: str
    external_event_id: str
    activity_type: str
    quantity: int
    occurred_at: str
    points_granted: int
    created_at: str


class PointsLedgerEntry(TypedDict, total=False):
    id: str
    enrollment_id: str
    kind: str
    points_delta: int
    source_activity_event_id: Optional[str]
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveAward(TypedDict, total=False):
    id: str
    enrollment_id: str
    program_id: str
    tier: str
    standard_award_cents: int
    award_cents: int
    applied_variant: str
    surcharge_cents: int
    net_annual_differential_cents: int
    status: str
    confirmed_at: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoachingReferral(TypedDict, total=False):
    id: str
    enrollment_id: str
    reason: str
    source: str
    assigned_coach_id: Optional[str]
    sessions_completed: int
    session_dates: list
    referral_round: int
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    line_type: str
    ref_id: Optional[str]
    amount_cents: int
    note: Optional[str]


class VendorInvoice(TypedDict, total=False):
    id: str
    program_id: str
    vendor_name: str
    period_start: str
    period_end: str
    line_items: list
    total_cents: int
    submitted_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AggregateReport(TypedDict, total=False):
    id: str
    program_id: str
    department: str
    cohort_size: int
    avg_settled_points: float
    participation_rate: float
    tobacco_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int
