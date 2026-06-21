"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class ChapterRiskStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class GreekType(str, Enum):
    SORORITY = "SORORITY"
    FRATERNITY = "FRATERNITY"


class PNMStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    MATCHED = "MATCHED"
    WITHDRAWN = "WITHDRAWN"
    BID_ACCEPTED = "BID_ACCEPTED"
    BID_DECLINED = "BID_DECLINED"


class RoundPhase(str, Enum):
    PARTY = "PARTY"
    MUTUAL_SELECTION = "MUTUAL_SELECTION"
    BID_DAY = "BID_DAY"
    CLOSED = "CLOSED"


class PartyStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RsvpStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class PreferenceSide(str, Enum):
    PNM_TO_CHAPTER = "PNM_TO_CHAPTER"
    CHAPTER_TO_PNM = "CHAPTER_TO_PNM"


class BidMatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class PriorityKind(str, Enum):
    LEGACY = "LEGACY"
    STANDARD = "STANDARD"


class DuesEntryKind(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class RiskIncidentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DISMISSED = "DISMISSED"


class UserRole(str, Enum):
    PanhellenicAdmin = "PanhellenicAdmin"
    RecruitmentChair = "RecruitmentChair"
    ChapterOfficer = "ChapterOfficer"
    RiskOfficer = "RiskOfficer"
    PNM = "PNM"
    Anonymous = "Anonymous"


# --- Entity TypedDicts (per PRD §2.4 common fields branch) ---

# Chapter: common_fields=true — carries id, created_at, updated_at, version
class Chapter(TypedDict):
    id: str
    name: str
    greek_type: str
    quota_total: int
    dues_per_member_cents: int
    legacy_priority_slots: int
    risk_status: str
    risk_points: int
    pledged_count: int
    legacy_pledged_count: int
    created_at: str
    updated_at: str
    version: int


# PNM: common_fields=true
class PNM(TypedDict):
    id: str
    full_name: str
    gpa: float
    legacy_chapter_id: Optional[str]
    is_legacy: bool
    status: str
    matched_chapter_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# RecruitmentRound: common_fields=true
class RecruitmentRound(TypedDict):
    id: str
    cycle_label: str
    phase: str
    bid_day_at: str
    created_at: str
    updated_at: str
    version: int


# Party: common_fields=true
class Party(TypedDict):
    id: str
    round_id: str
    chapter_id: str
    scheduled_start_utc: str
    duration_minutes: int
    capacity: int
    confirmed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# PartyInvitation: common_fields=true
class PartyInvitation(TypedDict):
    id: str
    party_id: str
    pnm_id: str
    rsvp_status: str
    created_at: str
    updated_at: str
    version: int


# Preference: common_fields=true
class Preference(TypedDict):
    id: str
    round_id: str
    side: str
    pnm_id: str
    chapter_id: str
    rank: int
    created_at: str
    updated_at: str
    version: int


# BidMatch: common_fields=true
class BidMatch(TypedDict):
    id: str
    round_id: str
    chapter_id: str
    pnm_id: str
    status: str
    priority_kind: str
    dues_charged_cents: int
    created_at: str
    updated_at: str
    version: int


# DuesLedgerEntry: common_fields=FALSE — append-only; only id + created_at
class DuesLedgerEntry(TypedDict):
    id: str
    chapter_id: str
    bid_match_id: str
    amount_cents: int
    entry_kind: str
    running_balance_cents: int
    created_at: str


# RiskIncident: common_fields=true
class RiskIncident(TypedDict):
    id: str
    chapter_id: str
    party_id: Optional[str]
    severity_points: int
    status: str
    reason: str
    created_at: str
    updated_at: str
    version: int
