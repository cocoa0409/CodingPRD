"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class MeetStatus(str, Enum):
    SETUP = "SETUP"
    ENTRIES_OPEN = "ENTRIES_OPEN"
    ENTRIES_CLOSED = "ENTRIES_CLOSED"
    SEEDED = "SEEDED"
    COMPLETED = "COMPLETED"
    OFFICIAL = "OFFICIAL"


class TeamStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WITHDRAWN = "WITHDRAWN"


class SwimmerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SwimEventStatus(str, Enum):
    PENDING = "PENDING"
    SEEDED = "SEEDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OFFICIAL = "OFFICIAL"
    CANCELLED = "CANCELLED"


class EventEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    SEEDED = "SEEDED"
    FINISHED = "FINISHED"
    DQ = "DQ"
    NO_SHOW = "NO_SHOW"
    SCRATCHED = "SCRATCHED"


class QualificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RelayTeamStatus(str, Enum):
    DECLARED = "DECLARED"
    LEGS_LOCKED = "LEGS_LOCKED"
    SCRATCHED = "SCRATCHED"


class LaneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ReconciliationStatus(str, Enum):
    PENDING_READINGS = "PENDING_READINGS"
    AUTO_CONFIRMED = "AUTO_CONFIRMED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    RESOLVED = "RESOLVED"


class ReconciledVariant(str, Enum):
    PRIMARY_PRIORITY = "PRIMARY_PRIORITY"
    BACKUP_MEAN_PRIORITY = "BACKUP_MEAN_PRIORITY"


class ResultStatus(str, Enum):
    UNOFFICIAL = "UNOFFICIAL"
    OFFICIAL = "OFFICIAL"
    DQ_EXCLUDED = "DQ_EXCLUDED"


class OfficialAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class DisqualificationStatus(str, Enum):
    RECORDED = "RECORDED"
    COACH_NOTIFIED = "COACH_NOTIFIED"
    PROTESTED = "PROTESTED"
    UPHELD = "UPHELD"
    CONFIRMED = "CONFIRMED"
    OVERTURNED = "OVERTURNED"


class MeetRecordStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    MEET_DIRECTOR = "MeetDirector"
    TEAM_COACH = "TeamCoach"
    TIMING_OPERATOR = "TimingOperator"
    DECK_OFFICIAL = "DeckOfficial"
    MEET_REFEREE = "MeetReferee"
    RECORDS_OFFICER = "RecordsOfficer"


class AgeGroup(str, Enum):
    TEN_AND_UNDER = "TEN_AND_UNDER"
    ELEVEN_TWELVE = "ELEVEN_TWELVE"
    THIRTEEN_FOURTEEN = "THIRTEEN_FOURTEEN"
    FIFTEEN_AND_OVER = "FIFTEEN_AND_OVER"


class Meet(TypedDict, total=False):
    id: str
    meet_name: str
    course: str
    start_date: str
    entry_deadline_utc: str
    lane_count: int
    points_table: List[int]
    relay_points_multiplier: int
    max_individual_entries_per_swimmer: int
    dq_protest_window_minutes: int
    min_recovery_minutes: int
    timing_delta_threshold_cs: int
    scoring_tie_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    meet_id: str
    team_code: str
    team_name: str
    status: str
    provisional_points: float
    official_points: float
    active_entry_count: int
    created_at: str
    updated_at: str
    version: int


class Swimmer(TypedDict, total=False):
    id: str
    team_id: str
    full_name: str
    birth_date: str
    gender: str
    age_on_meet_start: int
    age_group: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SwimEvent(TypedDict, total=False):
    id: str
    meet_id: str
    event_number: int
    gender: str
    age_group: str
    stroke: str
    distance_meters: int
    is_relay: bool
    qualifying_time_cs: Optional[int]
    session_date: str
    scheduled_start_minute: int
    scheduled_end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventEntry(TypedDict, total=False):
    id: str
    event_id: str
    swimmer_id: Optional[str]
    relay_team_id: Optional[str]
    seed_time_cs: Optional[int]
    qualification_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RelayTeam(TypedDict, total=False):
    id: str
    team_id: str
    event_id: str
    relay_name: str
    entry_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RelayLeg(TypedDict, total=False):
    # Thin join record: carries ONLY id + created_at (PRD §2.5).
    id: str
    relay_team_id: str
    leg_number: int
    swimmer_id: str
    created_at: str


class LaneAssignment(TypedDict, total=False):
    id: str
    event_id: str
    entry_id: str
    heat_number: int
    lane_number: int
    lane_status: str
    pad_cs: Optional[int]
    backup1_cs: Optional[int]
    backup2_cs: Optional[int]
    watch_cs: Optional[int]
    pad_status: str
    reconciliation_status: str
    reconciled_variant: Optional[str]
    final_time_cs: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Result(TypedDict, total=False):
    id: str
    entry_id: str
    event_id: str
    team_id: str
    final_time_cs: Optional[int]
    place: Optional[int]
    points: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Official(TypedDict, total=False):
    id: str
    meet_id: str
    full_name: str
    lsc_membership_id: str
    certifications: List[str]
    certification_expires_on: str
    created_at: str
    updated_at: str
    version: int


class OfficialAssignment(TypedDict, total=False):
    id: str
    event_id: str
    official_id: str
    role_on_deck: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Disqualification(TypedDict, total=False):
    id: str
    lane_assignment_id: str
    reporting_official_id: str
    resolved_by_referee_id: Optional[str]
    dq_code: str
    call_notes: str
    status: str
    notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeetRecord(TypedDict, total=False):
    id: str
    event_id: str
    record_time_cs: int
    holder_name: str
    holder_team: str
    set_on_date: str
    challenger_entry_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
