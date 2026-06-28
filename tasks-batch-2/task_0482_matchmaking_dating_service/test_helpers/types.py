"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the full set of common properties
(id, created_at, updated_at, version), so every TypedDict lists them.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BILLING_ADMIN = "BillingAdmin"
    SCREENING_OFFICER = "ScreeningOfficer"
    MATCHMAKER = "Matchmaker"
    MEMBER = "Member"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class MembershipPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MemberStatus(str, Enum):
    PROSPECT = "PROSPECT"
    SCREENING = "SCREENING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    EXITED = "EXITED"


class ScreeningDecision(str, Enum):
    NONE = "NONE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class FreezeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RESUMED = "RESUMED"
    CANCELLED = "CANCELLED"


class IntroductionStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    ONE_SIDED = "ONE_SIDED"
    MUTUAL = "MUTUAL"
    DECLINED = "DECLINED"
    CLOSED = "CLOSED"


class ResponseValue(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class DateEventOutcome(str, Enum):
    NONE = "NONE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class DateEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CoachingSessionStatus(str, Enum):
    BOOKED = "BOOKED"
    HELD = "HELD"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BackgroundCheckResult(str, Enum):
    NONE = "NONE"
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class BackgroundCheckStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class MembershipPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    term_months: int
    guaranteed_introductions: int
    priority_match_enabled: bool
    included_coaching_sessions: int
    coaching_value_cents: int
    background_check_addon_cents: int
    archived: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    birth_date: str
    city: str
    gender: str
    status: str
    screening_decision: str
    active_membership_id: Optional[str]
    guarantee_remaining_committed: int
    guarantee_remaining_forecast: int
    no_show_strikes: int
    coaching_suspended: bool
    wallet_credit_cents: int
    frozen_days_total: int
    term_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Screening(TypedDict):
    id: str
    member_id: str
    questionnaire_score: int
    identity_verified: bool
    decision: str
    decision_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Preference(TypedDict):
    id: str
    member_id: str
    seeking_gender: str
    min_age: int
    max_age: int
    max_distance_band: int
    attribute_weights: Dict[str, int]
    dealbreaker_tags: List[str]
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    plan_id: str
    start_at: str
    base_term_end_at: str
    guaranteed_introductions: int
    credits_consumed_committed: int
    guarantee_met: bool
    status: str
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class Freeze(TypedDict):
    id: str
    membership_id: str
    start_at: str
    end_at: str
    committed_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Introduction(TypedDict):
    id: str
    member_a_id: str
    member_b_id: str
    compatibility_score: float
    credits_consumed: int
    a_response: str
    b_response: str
    status: str
    win_back_promo: bool
    created_at: str
    updated_at: str
    version: int


class Feedback(TypedDict):
    id: str
    introduction_id: str
    author_member_id: str
    rating: int
    continue_interest: bool
    comments: str
    created_at: str
    updated_at: str
    version: int


class DateEvent(TypedDict):
    id: str
    introduction_id: str
    scheduled_by_member_id: str
    start_at: str
    end_at: str
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CoachingSession(TypedDict):
    id: str
    member_id: str
    coach_user_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    member_id: str
    provider_ref: str
    fee_charged_cents: int
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int
