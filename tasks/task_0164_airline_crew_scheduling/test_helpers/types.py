"""Domain types — entity TypedDicts, status enums, role enum.

Field names mirror the PRD verbatim. The PRD §2.4 declares three child
entities as immutable append-only — they carry only `id` and
`created_at`: DutyPeriod, FlightLeg, and SickCall.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CREW_SCHEDULER = "CrewScheduler"
    PILOT = "Pilot"
    FLIGHT_ATTENDANT = "FlightAttendant"
    UNION_STEWARD = "UnionSteward"


# ---------------------------------------------------------------------------
# Rank enum — PRD §3.1
# ---------------------------------------------------------------------------
class CrewRank(str, Enum):
    CAPTAIN = "CAPTAIN"
    FIRST_OFFICER = "FIRST_OFFICER"
    PURSER = "PURSER"
    FLIGHT_ATTENDANT = "FLIGHT_ATTENDANT"


# ---------------------------------------------------------------------------
# Status / state enums
# ---------------------------------------------------------------------------
class CrewMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_SICK_CALL = "ON_SICK_CALL"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class PairingStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    BIDDING_OPEN = "BIDDING_OPEN"
    AWARDED = "AWARDED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    NOT_AWARDED = "NOT_AWARDED"
    WITHDRAWN = "WITHDRAWN"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class AssignmentSource(str, Enum):
    BID_AWARD = "BID_AWARD"
    RESERVE_CALLOUT = "RESERVE_CALLOUT"
    TRADE = "TRADE"
    ADMIN_OVERRIDE = "ADMIN_OVERRIDE"


class ReservePoolState(str, Enum):
    AVAILABLE = "AVAILABLE"
    CALLED_OUT = "CALLED_OUT"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class TradeRequestState(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTER_PROPOSED = "COUNTER_PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class LegType(str, Enum):
    REVENUE = "REVENUE"
    DEADHEAD = "DEADHEAD"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true) — carry id + created_at + updated_at
# + version per PRD §2.4.
# ---------------------------------------------------------------------------
class CrewMember(TypedDict, total=False):
    id: str
    employee_no: str
    rank: str
    base_airport: str
    union_seniority_number: int
    union_local_id: str
    status: str
    cumulative_duty_minutes_7d: int
    cumulative_block_minutes_30d: int
    last_duty_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pairing(TypedDict, total=False):
    id: str
    pairing_code: str
    base_airport: str
    start_at: Optional[str]
    end_at: Optional[str]
    required_rank_composition: dict
    total_block_minutes: int
    total_duty_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    crew_member_id: str
    pairing_id: str
    preference_rank: int
    bid_window_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    pairing_id: str
    crew_member_id: str
    assigned_rank_slot: str
    source: str
    status: str
    scheduled_block_minutes: int
    actual_block_minutes: int
    pay_credit_minutes: int
    created_at: str
    updated_at: str
    version: int


class ReservePool(TypedDict, total=False):
    id: str
    crew_member_id: str
    reserve_date: str
    standby_start_at: str
    standby_end_at: str
    state: str
    created_at: str
    updated_at: str
    version: int


class TradeRequest(TypedDict, total=False):
    id: str
    initiator_assignment_id: str
    counterparty_assignment_id: str
    initiator_id: str
    counterparty_id: str
    state: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable append-only / child entities (common_fields: false) — carry ONLY
# id + created_at per PRD §2.4: "The child entities DutyPeriod, FlightLeg,
# and SickCall carry only id and created_at; they have no updated_at field
# and no version field."
# ---------------------------------------------------------------------------
class DutyPeriod(TypedDict, total=False):
    id: str
    pairing_id: str
    sequence_no: int
    report_at: str
    release_at: str
    duty_minutes: int
    block_minutes: int
    created_at: str


class FlightLeg(TypedDict, total=False):
    id: str
    duty_period_id: str
    leg_sequence_no: int
    flight_number: str
    dep_airport: str
    arr_airport: str
    dep_at: str
    arr_at: str
    block_minutes: int
    leg_type: str
    created_at: str


class SickCall(TypedDict, total=False):
    id: str
    crew_member_id: str
    assignment_id: Optional[str]
    reported_at: str
    effective_from: str
    expected_return_at: str
    covered_by_assignment_id: Optional[str]
    created_at: str


__all__ = [
    "Assignment",
    "AssignmentSource",
    "AssignmentStatus",
    "Bid",
    "BidStatus",
    "CrewMember",
    "CrewMemberStatus",
    "CrewRank",
    "DutyPeriod",
    "FlightLeg",
    "LegType",
    "Pairing",
    "PairingStatus",
    "ReservePool",
    "ReservePoolState",
    "SickCall",
    "TradeRequest",
    "TradeRequestState",
    "UserRole",
]
