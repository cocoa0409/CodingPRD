"""Domain types: entity TypedDicts, status enums, role enum for the feedback panel API."""
from enum import Enum
from typing import TypedDict, Optional, List, Any, Dict


class UserRole(str, Enum):
    PANEL_MANAGER = "PanelManager"
    SURVEY_DESIGNER = "SurveyDesigner"
    DATA_ANALYST = "DataAnalyst"
    INCENTIVE_CLERK = "IncentiveClerk"
    PRIVACY_OFFICER = "PrivacyOfficer"
    DEPARTMENT_LIAISON = "DepartmentLiaison"


class AgeBand(str, Enum):
    AGE_18_29 = "AGE_18_29"
    AGE_30_44 = "AGE_30_44"
    AGE_45_64 = "AGE_45_64"
    AGE_65_PLUS = "AGE_65_PLUS"


class TenureBucket(str, Enum):
    RENTER = "RENTER"
    OWNER = "OWNER"


class PanelCellStatus(str, Enum):
    OPEN = "OPEN"
    SATURATED = "SATURATED"


class PanelistStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"
    ATTRITED = "ATTRITED"
    WITHDRAWN = "WITHDRAWN"


class InstrumentStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class TranslationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class WaveStatus(str, Enum):
    DRAFT = "DRAFT"
    ARMED = "ARMED"
    FIELDING = "FIELDING"
    CLOSED = "CLOSED"
    WEIGHTED = "WEIGHTED"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class InvitationStatus(str, Enum):
    SENT = "SENT"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPPRESSED = "SUPPRESSED"


class ResponseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    DISCARDED = "DISCARDED"


class AwardEligibility(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class AwardPayout(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"


class SnapshotMethod(str, Enum):
    RIM = "RIM"
    POST_STRAT = "POST_STRAT"


class SnapshotStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


class CommitmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    BREACHED = "BREACHED"
    SUSPENDED = "SUSPENDED"


class HoldScope(str, Enum):
    NO_CONTACT = "NO_CONTACT"
    FULL_SUPPRESS = "FULL_SUPPRESS"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class RefreshRunStatus(str, Enum):
    OPEN = "OPEN"
    APPLIED = "APPLIED"
    ABORTED = "ABORTED"


class PanelCell(TypedDict, total=False):
    id: str
    age_band: str
    district: str
    tenure_bucket: str
    target_size: int
    reserved_count: int
    active_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Panelist(TypedDict, total=False):
    id: str
    external_ref: str
    full_name: str
    age_band: str
    district: str
    tenure_bucket: str
    preferred_locale: str
    home_cell_id: Optional[str]
    status: str
    missed_streak: int
    last_contacted_at: Optional[str]
    lapsed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict, total=False):
    id: str
    title: str
    question_count: int
    required_locales: List[str]
    base_locale: str
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Translation(TypedDict, total=False):
    id: str
    instrument_id: str
    locale: str
    translator_ref: str
    instrument_revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyWave(TypedDict, total=False):
    id: str
    wave_code: str
    instrument_id: str
    opens_at: str
    closes_at: str
    min_response_rate: float
    incentive_pool_total_cents: int
    base_incentive_cents: int
    incentive_pool_available_cents: int
    incentive_pool_reserved_cents: int
    incentive_pool_paid_cents: int
    invited_count: int
    completed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invitation(TypedDict, total=False):
    id: str
    wave_id: str
    panelist_id: str
    sent_at: str
    reminder_count: int
    last_reminder_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Response(TypedDict, total=False):
    id: str
    invitation_id: str
    wave_id: str
    panelist_id: str
    answers_payload: Dict[str, Any]
    completeness_pct: float
    completion_seconds: int
    speeder_flag: bool
    low_effort_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveAward(TypedDict, total=False):
    id: str
    response_id: str
    wave_id: str
    amount_cents: int
    eligibility_status: str
    payout_status: str
    created_at: str
    updated_at: str
    version: int


class WeightSnapshot(TypedDict, total=False):
    id: str
    wave_id: str
    method: str
    weight_mass: float
    accepted_count: int
    design_effect: float
    weighted_cell_shares: Dict[str, float]
    status: str
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Publication(TypedDict, total=False):
    id: str
    wave_id: str
    weight_snapshot_id: str
    title: str
    k_threshold: int
    breakdown_cells: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUpCommitment(TypedDict, total=False):
    id: str
    publication_id: str
    department_name: str
    summary: str
    due_at: str
    breached_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PrivacyHold(TypedDict, total=False):
    id: str
    panelist_id: str
    scope: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RefreshRun(TypedDict, total=False):
    id: str
    run_label: str
    attrition_grace_days: int
    planned_attrition_count: int
    applied_attrition_count: Optional[int]
    applied_forfeit_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
