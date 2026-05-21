"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 — common-fields vs append-only entities:

    "All primary entities — Park, Visitor, AmericaTheBeautifulPass,
    Campground, LotteryPermit, BackcountryZone, TimedEntryReservation,
    CampgroundReservation, LotteryApplication, and BackcountryPermit —
    carry the same four system-managed fields: id, created_at,
    updated_at, version."

    "Two entities are append-only event records and therefore omit the
    mutation-tracking fields. The WaitlistEntry and LedgerEntry resources
    carry only id and created_at — both updated_at and version are absent."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    VISITOR = "Visitor"
    PARK_ADMIN = "ParkAdmin"
    PARK_RANGER = "ParkRanger"
    SYSTEM_OPERATOR = "SystemOperator"


# ---------------------------------------------------------------------------
# Status enums — PRD §2.7, §3
# ---------------------------------------------------------------------------
class ParkStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PassType(str, Enum):
    ANNUAL = "ANNUAL"
    SENIOR_ANNUAL = "SENIOR_ANNUAL"
    SENIOR_LIFETIME = "SENIOR_LIFETIME"
    MILITARY = "MILITARY"
    ACCESS = "ACCESS"
    VOLUNTEER = "VOLUNTEER"
    FOURTH_GRADE = "FOURTH_GRADE"


class TimedEntryStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    USED = "USED"
    NO_SHOW = "NO_SHOW"


class CampgroundReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"


class BackcountryPermitStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    USED = "USED"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class LotteryPermitStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DRAWN = "DRAWN"
    ARCHIVED = "ARCHIVED"


class LotteryApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WAITLISTED = "WAITLISTED"
    AWARDED = "AWARDED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    FORFEITED = "FORFEITED"


class SiteKind(str, Enum):
    STANDARD = "STANDARD"
    GROUP = "GROUP"


class LedgerKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    FEE_CHARGE = "FEE_CHARGE"
    FEE_REFUND = "FEE_REFUND"
    LOTTERY_FEE = "LOTTERY_FEE"
    PERMIT_FEE = "PERMIT_FEE"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerReferenceKind(str, Enum):
    TIMED_ENTRY_RESERVATION = "TimedEntryReservation"
    CAMPGROUND_RESERVATION = "CampgroundReservation"
    BACKCOUNTRY_PERMIT = "BackcountryPermit"
    LOTTERY_APPLICATION = "LotteryApplication"
    NONE = "None"


# ---------------------------------------------------------------------------
# Common-fields entities — PRD §2.4: id, created_at, updated_at, version
# ---------------------------------------------------------------------------
class Park(TypedDict, total=False):
    id: str
    name: str
    code: str
    timezone: str
    timed_entry_daily_capacity: int
    timed_entry_window_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Visitor(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    wallet_balance_cents: int
    lottery_strikes: int
    created_at: str
    updated_at: str
    version: int


class AmericaTheBeautifulPass(TypedDict, total=False):
    id: str
    visitor_id: str
    pass_type: str
    serial: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Campground(TypedDict, total=False):
    id: str
    park_id: str
    name: str
    standard_site_count: int
    group_site_count: int
    nightly_standard_fee_cents: int
    nightly_group_fee_cents: int
    max_consecutive_nights: int
    waitlist_window_hours: int
    created_at: str
    updated_at: str
    version: int


class LotteryPermit(TypedDict, total=False):
    id: str
    park_id: str
    name: str
    lottery_open_at: str
    lottery_close_at: str
    draw_at: str
    hike_date: str
    daily_slot_count: int
    per_application_max_party: int
    application_fee_cents: int
    permit_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BackcountryZone(TypedDict, total=False):
    id: str
    park_id: str
    name: str
    nightly_quota_people: int
    ranger_buffer_minutes: int
    per_party_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class TimedEntryReservation(TypedDict, total=False):
    id: str
    park_id: str
    visitor_id: str
    vehicle_plate: str
    entry_date_local: str
    window_start_local: str
    window_end_local: str
    pass_id: Optional[str]
    entry_fee_cents: int
    status: str
    held_until: Optional[str]
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class CampgroundReservation(TypedDict, total=False):
    id: str
    campground_id: str
    visitor_id: str
    site_kind: str
    party_size: int
    check_in_date_local: str
    check_out_date_local: str
    nights: int
    nightly_rate_cents: int
    total_fee_cents: int
    status: str
    held_until: Optional[str]
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class LotteryApplication(TypedDict, total=False):
    id: str
    lottery_permit_id: str
    visitor_id: str
    party_size: int
    rank_seed: int
    application_fee_cents: int
    status: str
    award_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackcountryPermit(TypedDict, total=False):
    id: str
    zone_id: str
    visitor_id: str
    party_size: int
    entry_datetime_local: str
    exit_datetime_local: str
    nights: int
    fee_cents: int
    status: str
    held_until: Optional[str]
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — PRD §2.4: id + created_at only (no updated_at,
# no version).
# ---------------------------------------------------------------------------
class WaitlistEntry(TypedDict, total=False):
    id: str
    campground_id: str
    visitor_id: str
    site_kind: str
    check_in_date_local: str
    nights: int
    priority_score: int
    status: str
    promoted_reservation_id: Optional[str]
    created_at: str


class LedgerEntry(TypedDict, total=False):
    id: str
    visitor_id: str
    kind: str
    amount_cents: int
    reference_kind: str
    reference_id: Optional[str]
    created_at: str


__all__ = [
    "UserRole",
    "ParkStatus",
    "PassStatus",
    "PassType",
    "TimedEntryStatus",
    "CampgroundReservationStatus",
    "BackcountryPermitStatus",
    "WaitlistEntryStatus",
    "LotteryPermitStatus",
    "LotteryApplicationStatus",
    "SiteKind",
    "LedgerKind",
    "LedgerReferenceKind",
    "Park",
    "Visitor",
    "AmericaTheBeautifulPass",
    "Campground",
    "LotteryPermit",
    "BackcountryZone",
    "TimedEntryReservation",
    "CampgroundReservation",
    "LotteryApplication",
    "BackcountryPermit",
    "WaitlistEntry",
    "LedgerEntry",
]
