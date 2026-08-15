"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CASTING_DIRECTOR = "CastingDirector"
    CLIENT = "Client"
    TALENT = "Talent"
    STUDIO_ENGINEER = "StudioEngineer"
    AGENT = "Agent"
    PLATFORM_ADMIN = "PlatformAdmin"


class RosterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    CASTING = "CASTING"
    CAST = "CAST"
    IN_SESSION = "IN_SESSION"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AuditionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    REJECTED = "REJECTED"
    SELECTED = "SELECTED"


class StudioStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SessionStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SessionKind(str, Enum):
    PRIMARY = "PRIMARY"
    PICKUP = "PICKUP"
    RETAKE = "RETAKE"


class UsageType(str, Enum):
    BROADCAST = "BROADCAST"
    DIGITAL = "DIGITAL"
    TERM = "TERM"


class ProductCategory(str, Enum):
    AUTOMOTIVE = "AUTOMOTIVE"
    PHARMA = "PHARMA"
    FAST_FOOD = "FAST_FOOD"
    FINANCE = "FINANCE"
    TECH = "TECH"
    RETAIL = "RETAIL"
    ALCOHOL = "ALCOHOL"
    GAMING = "GAMING"


class VoiceProfile(str, Enum):
    MALE_DEEP = "MALE_DEEP"
    MALE_LIGHT = "MALE_LIGHT"
    FEMALE_DEEP = "FEMALE_DEEP"
    FEMALE_LIGHT = "FEMALE_LIGHT"
    NONBINARY = "NONBINARY"
    CHILD = "CHILD"


class UnionStatus(str, Enum):
    UNION = "UNION"
    NON_UNION = "NON_UNION"
    FICORE = "FICORE"


class InvoiceKind(str, Enum):
    BUYOUT = "BUYOUT"
    SESSION_FEE = "SESSION_FEE"
    PICKUP_FEE = "PICKUP_FEE"


class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class ExclusionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class ExclusionSource(str, Enum):
    PROJECT_CAST = "PROJECT_CAST"
    MANUAL_HOLD = "MANUAL_HOLD"


# --- Entities carrying id + created_at + updated_at + version (PRD §2.4) ---


class Talent(TypedDict, total=False):
    id: str
    stage_name: str
    email: str
    voice_profile: str
    languages: List[str]
    union_status: str
    base_session_fee_cents: int
    roster_status: str
    active_conflict_categories: List[str]
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    billing_email: str
    default_currency: str
    account_status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    client_id: str
    title: str
    product_category: str
    usage_type: str
    term_months: Optional[int]
    spots_count: int
    exclusivity_required: bool
    brief_text: str
    audition_deadline: str
    status: str
    selected_talent_id: Optional[str]
    buyout_quote_cents: Optional[int]
    buyout_final_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SelfAudition(TypedDict, total=False):
    id: str
    project_id: str
    talent_id: str
    audio_file_url: str
    slate_text: str
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Studio(TypedDict, total=False):
    id: str
    studio_name: str
    location: str
    has_directed_patch: bool
    hourly_rate_cents: int
    operating_tz: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    project_id: str
    talent_id: str
    studio_id: str
    session_kind: str
    directed_patch: bool
    start_at: str
    duration_minutes: int
    status: str
    end_at: str
    created_at: str
    updated_at: str
    version: int


class UsageTerms(TypedDict, total=False):
    id: str
    project_id: str
    usage_type: str
    term_months: Optional[int]
    broadcast_regions: List[str]
    digital_placements: List[str]
    buyout_cents: int
    agent_commission_cents: int
    talent_payout_cents: int
    locked_at_cast: bool
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    project_id: str
    invoice_kind: str
    talent_amount_cents: int
    agent_commission_cents: int
    total_cents: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConflictExclusion(TypedDict, total=False):
    id: str
    talent_id: str
    product_category: str
    starts_at: str
    ends_at: str
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Entities carrying ONLY id + created_at (PRD §2.4 deviations) ---


class Delivery(TypedDict, total=False):
    id: str
    project_id: str
    session_id: str
    file_url: str
    delivered_at: str
    revision_window_hours: int
    revision_window_closes_at: str
    revision_requested: bool
    created_at: str
    # NOTE: no updated_at, no version — Delivery deviates from the common shape.


class ClockState(TypedDict, total=False):
    id: str
    current_utc: str
    created_at: str
    # NOTE: no updated_at, no version — ClockState deviates from the common shape.
