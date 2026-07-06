"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status / enum value sets ---

class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Industry(str, Enum):
    TECH = "TECH"
    HEALTH = "HEALTH"
    FINANCE = "FINANCE"
    CONSUMER = "CONSUMER"
    NONPROFIT = "NONPROFIT"


class AccountTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ENTERPRISE = "ENTERPRISE"


class OutletTier(str, Enum):
    NATIONAL = "NATIONAL"
    REGIONAL = "REGIONAL"
    TRADE = "TRADE"
    BLOG = "BLOG"


class JournalistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKLISTED = "BLOCKLISTED"


class Beat(str, Enum):
    TECH = "TECH"
    HEALTH = "HEALTH"
    FINANCE = "FINANCE"
    CONSUMER = "CONSUMER"
    POLITICS = "POLITICS"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class CampaignObjective(str, Enum):
    LAUNCH = "LAUNCH"
    THOUGHT_LEADERSHIP = "THOUGHT_LEADERSHIP"
    CRISIS = "CRISIS"
    AWARENESS = "AWARENESS"


class RetainerPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SpokespersonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class MediaListStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXHAUSTED = "EXHAUSTED"
    ARCHIVED = "ARCHIVED"


class PitchStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class PressReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class DistributionStatus(str, Enum):
    QUEUED = "QUEUED"
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"


class Sentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class Prominence(str, Enum):
    FEATURE = "FEATURE"
    MENTION = "MENTION"
    PASSING = "PASSING"


class CoverageStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    RETRACTED = "RETRACTED"


class InterviewStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CrisisSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CrisisSeverityStatus(str, Enum):
    ASSESSING = "ASSESSING"
    CONTAINED = "CONTAINED"
    ESCALATED = "ESCALATED"


class CrisisResponseStatus(str, Enum):
    DRAFTING = "DRAFTING"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class WorkType(str, Enum):
    STRATEGY = "STRATEGY"
    WRITING = "WRITING"
    OUTREACH = "OUTREACH"
    MONITORING = "MONITORING"
    CRISIS = "CRISIS"


class TimeEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    VOID = "VOID"


class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    MEDIA_SPECIALIST = "MediaSpecialist"
    SCHEDULING_COORDINATOR = "SchedulingCoordinator"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity TypedDicts ---

# common_fields: true — id + created_at + updated_at + version
class Client(TypedDict):
    id: str
    name: str
    industry: str
    monthly_retainer_cents: int
    monthly_hours_cap: float
    overage_rate_cents: int
    account_tier: str
    status: str
    lifetime_earned_media_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable reference data: only id + created_at
class Outlet(TypedDict):
    id: str
    name: str
    tier: str
    monthly_unique_visitors: int
    domain_authority: int
    created_at: str


# common_fields: true
class Journalist(TypedDict):
    id: str
    outlet_id: str
    full_name: str
    email: str
    beat: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Campaign(TypedDict):
    id: str
    client_id: str
    title: str
    objective: str
    budget_cents: int
    target_beat: str
    status: str
    earned_media_value_cents: int
    cost_basis_cents: int
    roi_ratio: Optional[float]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class RetainerPeriod(TypedDict):
    id: str
    client_id: str
    period_month: str
    hours_cap: float
    overage_rate_cents: int
    hours_consumed: float
    provisional_total_cents: int
    final_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Spokesperson(TypedDict):
    id: str
    client_id: str
    full_name: str
    title: str
    prep_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class MediaList(TypedDict):
    id: str
    campaign_id: str
    name: str
    journalist_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Pitch(TypedDict):
    id: str
    campaign_id: str
    media_list_id: str
    journalist_id: str
    angle: str
    is_exclusive: bool
    status: str
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class PressRelease(TypedDict):
    id: str
    campaign_id: str
    headline: str
    embargo_until: str
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Distribution(TypedDict):
    id: str
    press_release_id: str
    journalist_id: str
    status: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Coverage(TypedDict):
    id: str
    campaign_id: str
    journalist_id: str
    pitch_id: Optional[str]
    headline: str
    published_at: str
    sentiment: str
    prominence: str
    estimated_media_value_cents: int
    media_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Interview(TypedDict):
    id: str
    campaign_id: str
    spokesperson_id: str
    journalist_id: str
    pitch_id: Optional[str]
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class CrisisEvent(TypedDict):
    id: str
    client_id: str
    campaign_id: Optional[str]
    summary: str
    severity: str
    severity_status: str
    response_status: str
    holding_statement: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class TimeEntry(TypedDict):
    id: str
    retainer_period_id: str
    campaign_id: Optional[str]
    staff_id: str
    work_type: str
    billable_hours: float
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
