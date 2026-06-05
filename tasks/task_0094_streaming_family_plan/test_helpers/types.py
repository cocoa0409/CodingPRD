"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Streaming Family Plan resource model (PRD §2.4, §2.5, §3).
Full-spine resources carry id + created_at + updated_at + version; the three
write-once configuration/audit resources (SubscriptionPlan, Title, PlanChange)
carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Enums --------------------------------------------------------------


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_OWNER = "AccountOwner"
    PROFILE_USER = "ProfileUser"
    ANONYMOUS = "Anonymous"


class PlanTier(str, Enum):
    AD_SUPPORTED = "AD_SUPPORTED"
    AD_FREE = "AD_FREE"
    PREMIUM = "PREMIUM"


class MaturityRating(str, Enum):
    G = "G"
    PG = "PG"
    PG13 = "PG13"
    R = "R"
    NC17 = "NC17"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BillingStatus(str, Enum):
    OPEN = "OPEN"
    INVOICED = "INVOICED"


class ProfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProfileKind(str, Enum):
    ADULT = "ADULT"
    TEEN = "TEEN"
    KID = "KID"


class InviteStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DevicePlatform(str, Enum):
    TV = "TV"
    MOBILE = "MOBILE"
    WEB = "WEB"
    TABLET = "TABLET"


class DeviceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    DEREGISTERED = "DEREGISTERED"


class StreamSessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class DownloadStatus(str, Enum):
    DOWNLOADING = "DOWNLOADING"
    READY = "READY"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class DownloadQuality(str, Enum):
    SD = "SD"
    HD = "HD"


class PlanChangeDirection(str, Enum):
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"
    LATERAL = "LATERAL"


# --- Write-once configuration / audit resources (id + created_at only) ---


class SubscriptionPlan(TypedDict):
    id: str
    created_at: str
    tier: str
    monthly_fee_cents: int
    max_profiles: int
    concurrent_stream_cap: int
    max_registered_devices: int
    download_quota_per_profile: int
    ad_free: bool
    hd_offline_allowed: bool


class Title(TypedDict):
    id: str
    created_at: str
    name: str
    maturity_rating: str
    runtime_minutes: int
    downloadable: bool
    license_size_mb: int


class PlanChange(TypedDict):
    id: str
    created_at: str
    account_id: str
    to_plan_id: str
    from_plan_id: str
    direction: str


# --- Full-spine resources (id + created_at + updated_at + version) -------


class Account(TypedDict):
    id: str
    plan_id: str
    owner_email: str
    status: str
    billing_anchor_day: int
    wallet_credit_cents: int
    billing_status: str
    period_charge_cents: int
    proration_adjustment_cents: int
    active_stream_count: int
    registered_device_count: int
    created_at: str
    updated_at: str
    version: int


class Profile(TypedDict):
    id: str
    account_id: str
    display_name: str
    kind: str
    status: str
    max_rating_allowed: str
    daily_watch_minutes_used: int
    created_at: str
    updated_at: str
    version: int


class ParentalControl(TypedDict):
    id: str
    profile_id: str
    max_rating: str
    daily_watch_limit_minutes: int
    curfew_start_min: int
    curfew_end_min: int
    created_at: str
    updated_at: str
    version: int


class Invite(TypedDict):
    id: str
    account_id: str
    invitee_email: str
    token: str
    status: str
    expires_at: str
    created_profile_id: Optional[str]
    hold_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    account_id: str
    device_label: str
    platform: str
    status: str
    supports_hd: bool
    created_at: str
    updated_at: str
    version: int


class StreamSession(TypedDict):
    id: str
    profile_id: str
    device_id: str
    title_id: str
    status: str
    started_at_min: int
    minutes_watched: int
    ad_breaks_served: int
    created_at: str
    updated_at: str
    version: int


class Download(TypedDict):
    id: str
    profile_id: str
    device_id: str
    title_id: str
    status: str
    quality: str
    license_expires_at: Optional[str]
    size_mb: int
    created_at: str
    updated_at: str
    version: int


class WatchProgress(TypedDict):
    id: str
    profile_id: str
    title_id: str
    position_min: int
    last_device_id: str
    completed: bool
    created_at: str
    updated_at: str
    version: int
