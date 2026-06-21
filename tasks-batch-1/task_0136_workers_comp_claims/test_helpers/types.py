"""Domain types: entity TypedDicts, status enums, role enum.

All field names match the PRD's contract exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    MEDICAL_REVIEWER = "MedicalReviewer"
    EMPLOYER = "Employer"


# ─── Status enums ─────────────────────────────────────

class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    MEDICAL_ONLY = "MEDICAL_ONLY"
    LOST_TIME = "LOST_TIME"
    MMI = "MMI"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    DENIED = "DENIED"


class ClaimClass(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    MEDICAL_ONLY = "MEDICAL_ONLY"
    LOST_TIME = "LOST_TIME"


class EdiStatus(str, Enum):
    DRAFT = "DRAFT"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"


class ReportKind(str, Enum):
    FROI = "FROI"
    SROI = "SROI"


class BenefitType(str, Enum):
    TTD = "TTD"
    TPD = "TPD"
    PPD = "PPD"


class BenefitPaymentStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class RatingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"


class RaterRole(str, Enum):
    TREATING = "TREATING"
    IME = "IME"


class RtwOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ImeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class SeverityTier(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ───

class Employer(TypedDict):
    id: str
    legal_name: str
    state_code: str
    open_claim_count: int
    current_emr: float
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    employer_id: str
    policy_number: str
    manual_premium_cents: int
    effective_date: str
    expiration_date: str
    modified_premium_cents: int
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    employer_id: str
    full_name: str
    gross_wages_cents: int
    weeks_worked: int
    average_weekly_wage_cents: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    worker_id: str
    status: str
    claim_class: str
    disability_days: int
    date_of_injury: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InjuryReport(TypedDict):
    id: str
    claim_id: str
    report_kind: str
    maintenance_type_code: str
    edi_status: str
    rejection_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitPayment(TypedDict):
    id: str
    claim_id: str
    benefit_type: str
    light_duty_weekly_cents: int
    impairment_rating_id: Optional[str]
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpairmentRating(TypedDict):
    id: str
    claim_id: str
    whole_body_pct: float
    rater_role: str
    status: str
    finalized_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ReturnToWorkOffer(TypedDict):
    id: str
    claim_id: str
    light_duty_weekly_cents: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reserve(TypedDict):
    id: str
    claim_id: str
    severity_tier: str
    projected_weeks: int
    indemnity_reserve_cents: int
    medical_reserve_cents: int
    indemnity_paid_cents: int
    medical_paid_cents: int
    total_incurred_cents: int
    created_at: str
    updated_at: str
    version: int


class IMEOrder(TypedDict):
    id: str
    claim_id: str
    scheduled_start: str
    scheduled_end: str
    examiner_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExperienceModEntry(TypedDict):
    id: str
    employer_id: str
    rating_year: int
    weighting_factor: float
    ballast_cents: int
    expected_primary_cents: int
    expected_excess_cents: int
    mod_factor: float
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false → ONLY id + created_at) ───

class WageStatement(TypedDict):
    id: str
    claim_id: str
    average_weekly_wage_cents: int
    ttd_weekly_rate_cents: int
    created_at: str
    # NO updated_at, NO version — immutable append-only record
