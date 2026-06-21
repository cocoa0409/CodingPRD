"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Audit-bearing entities (Election, Precinct,
VoterRegistration, AbsenteeBallot, CureCase, VotingMachine, RecountCase) carry the
full common set id/created_at/updated_at/version. MachineFailure and
EarlyVoteCheckIn are lightweight and immutable: they carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    ELECTION_ADMIN = "ElectionAdmin"
    ELECTION_OFFICIAL = "ElectionOfficial"
    VOTER = "Voter"
    POLL_WORKER = "PollWorker"
    CANVASSER = "Canvasser"


# --- Status enums ---
class ElectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    VOTING_OPEN = "VOTING_OPEN"
    POLLS_CLOSED = "POLLS_CLOSED"
    CERTIFIED = "CERTIFIED"


class CapacityPosture(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class TallyStatus(str, Enum):
    PENDING = "PENDING"
    TALLIED = "TALLIED"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class Party(str, Enum):
    DEMOCRAT = "DEMOCRAT"
    REPUBLICAN = "REPUBLICAN"
    INDEPENDENT = "INDEPENDENT"
    GREEN = "GREEN"
    LIBERTARIAN = "LIBERTARIAN"
    UNAFFILIATED = "UNAFFILIATED"


class RequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CureStatus(str, Enum):
    NONE = "NONE"
    FLAGGED = "FLAGGED"
    CURE_PENDING = "CURE_PENDING"
    CURED = "CURED"
    CURE_FAILED = "CURE_FAILED"


class CureReason(str, Enum):
    SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"
    MISSING_SIGNATURE = "MISSING_SIGNATURE"
    MISSING_WITNESS = "MISSING_WITNESS"


class CureCaseStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class MachineRole(str, Enum):
    PRIMARY = "PRIMARY"
    BACKUP = "BACKUP"


class MachineStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    FAILED = "FAILED"
    REPLACED = "REPLACED"
    RETIRED = "RETIRED"


class FailureResolution(str, Enum):
    BACKUP_ACTIVATED = "BACKUP_ACTIVATED"
    NO_BACKUP_AVAILABLE = "NO_BACKUP_AVAILABLE"


class RecountStatus(str, Enum):
    REQUESTED = "REQUESTED"
    MACHINE_DONE = "MACHINE_DONE"
    HAND_DONE = "HAND_DONE"
    BOTH_DONE = "BOTH_DONE"
    CERTIFIED = "CERTIFIED"
    DISMISSED = "DISMISSED"


class RecountPass(str, Enum):
    MACHINE = "MACHINE"
    HAND = "HAND"


class CureDecision(str, Enum):
    SUBMIT_RESPONSE = "SUBMIT_RESPONSE"
    APPROVE = "APPROVE"
    DENY = "DENY"


# --- Entity TypedDicts (audit-bearing: full common set) ---
class Election(TypedDict, total=False):
    id: str
    name: str
    election_date: str
    registration_deadline: str
    absentee_request_deadline: str
    cure_deadline: str
    early_voting_start: str
    early_voting_end: str
    status: str
    total_registered: int
    total_ballots_accepted: int
    turnout_pct: float
    projected_turnout_pct: float
    created_at: str
    updated_at: str
    version: int


class Precinct(TypedDict, total=False):
    id: str
    election_id: str
    code: str
    county_fips: str
    street_low: int
    street_high: int
    max_registrations: int
    assigned_count: int
    capacity_posture: str
    tally_status: str
    reported_vote_count: Optional[int]
    tally_recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VoterRegistration(TypedDict, total=False):
    id: str
    election_id: str
    precinct_id: Optional[str]
    first_name: str
    last_name: str
    national_id: str
    is_citizen: bool
    date_of_birth: str
    county_fips: str
    street_number: int
    party: str
    early_voted_at: Optional[str]
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbsenteeBallot(TypedDict, total=False):
    id: str
    registration_id: str
    election_id: str
    precinct_id: str
    mailing_address: str
    request_status: str
    cure_status: str
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CureCase(TypedDict, total=False):
    id: str
    ballot_id: str
    election_id: str
    reason: str
    voter_response_text: Optional[str]
    status: str
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VotingMachine(TypedDict, total=False):
    id: str
    precinct_id: str
    serial: str
    role: str
    status: str
    backup_for_machine_id: Optional[str]
    capacity: int
    created_at: str
    updated_at: str
    version: int


class RecountCase(TypedDict, total=False):
    id: str
    election_id: str
    precinct_id: str
    original_count: int
    machine_recount: Optional[int]
    hand_recount: Optional[int]
    certified_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Lightweight, immutable entities: id + created_at only ---
class MachineFailure(TypedDict, total=False):
    id: str
    machine_id: str
    reported_at: str
    backup_machine_id: Optional[str]
    resolution: str
    created_at: str


class EarlyVoteCheckIn(TypedDict, total=False):
    id: str
    registration_id: str
    precinct_id: str
    checked_in_at: str
    created_at: str


class ClockState(TypedDict, total=False):
    current_utc: str
