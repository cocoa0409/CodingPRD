"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 — common-resource properties:

    "Every primary resource — Election, Precinct, Voter, AbsenteeBallot,
    CuringCase, BallotCast, VotingMachine, and RecountRequest — carries
    four system-managed fields: id, created_at, updated_at, version."

    "Two entities are immutable-event-style and carry only id and
    created_at — they do not expose updated_at and they do not expose
    version. These are PartyRegistration (an append-only audit log of
    party changes) and ClockState (the server-controlled wall-clock
    row)."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ELECTION_BOARD = "ElectionBoard"
    REGISTRAR_CLERK = "RegistrarClerk"
    REVIEWER_CLERK = "ReviewerClerk"
    PRECINCT_OFFICER = "PrecinctOfficer"
    VOTER = "Voter"
    TEST_DRIVER = "TestDriver"


# ---------------------------------------------------------------------------
# Status enums — PRD §2.12
# ---------------------------------------------------------------------------
class ElectionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_REGISTRATION = "OPEN_REGISTRATION"
    EARLY_VOTING = "EARLY_VOTING"
    ELECTION_DAY = "ELECTION_DAY"
    TALLY = "TALLY"
    RECOUNT = "RECOUNT"
    CERTIFIED = "CERTIFIED"


class VoterStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PURGED = "PURGED"


class AbsenteeBallotStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CURED = "CURED"


class CuringCaseStatus(str, Enum):
    OPEN_PENDING_VOTER = "OPEN_PENDING_VOTER"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_ACCEPT = "RESOLVED_ACCEPT"
    RESOLVED_REJECT = "RESOLVED_REJECT"
    EXPIRED = "EXPIRED"


class BallotCastStatus(str, Enum):
    CAST = "CAST"
    TALLIED = "TALLIED"
    CHALLENGED = "CHALLENGED"
    INVALIDATED = "INVALIDATED"


class VotingMachineStatus(str, Enum):
    READY = "READY"
    IN_USE = "IN_USE"
    DOWN = "DOWN"
    DECOMMISSIONED = "DECOMMISSIONED"


class RecountRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED_NO_CHANGE = "RESOLVED_NO_CHANGE"
    RESOLVED_OVERTURN = "RESOLVED_OVERTURN"
    DENIED = "DENIED"


# ---------------------------------------------------------------------------
# Other enums — PRD §2.12
# ---------------------------------------------------------------------------
class ReasonCode(str, Enum):
    MILITARY = "MILITARY"
    OVERSEAS = "OVERSEAS"
    DISABILITY = "DISABILITY"
    ABSENT = "ABSENT"
    NO_REASON = "NO_REASON"


class SignatureMatch(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"


class DefectCode(str, Enum):
    SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"
    SIGNATURE_MISSING = "SIGNATURE_MISSING"


class BallotMethod(str, Enum):
    EARLY_IN_PERSON = "EARLY_IN_PERSON"
    ELECTION_DAY_MACHINE = "ELECTION_DAY_MACHINE"
    ELECTION_DAY_PROVISIONAL = "ELECTION_DAY_PROVISIONAL"
    ABSENTEE = "ABSENTEE"


class ChallengeReason(str, Enum):
    DOUBLE_VOTE = "DOUBLE_VOTE"
    MACHINE_FAILURE = "MACHINE_FAILURE"
    RECOUNT_DISCREPANCY = "RECOUNT_DISCREPANCY"


class FailureReason(str, Enum):
    POWER = "POWER"
    JAM = "JAM"
    TAMPER = "TAMPER"
    OTHER = "OTHER"


class PartyAffiliation(str, Enum):
    DEMOCRATIC = "DEMOCRATIC"
    REPUBLICAN = "REPUBLICAN"
    INDEPENDENT = "INDEPENDENT"
    UNAFFILIATED = "UNAFFILIATED"


class RequestedByRole(str, Enum):
    ELECTION_BOARD = "ElectionBoard"
    SYSTEM = "system"


class ActorRole(str, Enum):
    VOTER_SELF = "VoterSelf"
    REGISTRAR_CLERK = "RegistrarClerk"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields entities (id, created_at, updated_at,
# version) per PRD §2.4
# ---------------------------------------------------------------------------
class Election(TypedDict, total=False):
    id: str
    name: str
    election_date: str
    registration_deadline: str
    absentee_request_deadline: str
    early_voting_starts_at: str
    early_voting_ends_at: str
    ballot_return_deadline: str
    cure_deadline: str
    certification_deadline: str
    state: str
    recount_threshold_pct: float
    total_registered_active: int
    certified_winner_voter_choice: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Precinct(TypedDict, total=False):
    id: str
    election_id: str
    code: str
    street_pattern: str
    capacity_machines: int
    provisional_ballot_count: int
    machine_failure_active: bool
    created_at: str
    updated_at: str
    version: int


class Voter(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    residency_address: str
    residency_since: str
    is_citizen: bool
    election_id: str
    precinct_id: Optional[str]
    status: str
    party_affiliation: str
    party_locked_at: Optional[str]
    registered_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbsenteeBallot(TypedDict, total=False):
    id: str
    voter_id: str
    election_id: str
    requested_at: str
    issued_at: Optional[str]
    returned_at: Optional[str]
    decided_at: Optional[str]
    reason_code: str
    signature_match: Optional[str]
    status: str
    linked_curing_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CuringCase(TypedDict, total=False):
    id: str
    absentee_ballot_id: str
    voter_id: str
    election_id: str
    defect_code: str
    round_count: int
    max_rounds: int
    voter_submission_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BallotCast(TypedDict, total=False):
    id: str
    precinct_id: str
    voter_id: str
    election_id: str
    method: str
    machine_id: Optional[str]
    absentee_ballot_id: Optional[str]
    voter_choice: str
    cast_at: str
    status: str
    challenge_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VotingMachine(TypedDict, total=False):
    id: str
    precinct_id: str
    serial_no: str
    status: str
    failure_reason: Optional[str]
    down_since: Optional[str]
    backup_emergency_ballots_issued: int
    created_at: str
    updated_at: str
    version: int


class RecountRequest(TypedDict, total=False):
    id: str
    election_id: str
    requested_by_role: str
    petition_count: int
    trigger_margin_pct: float
    status: str
    reconciled_totals_json: Optional[dict]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lean entities — PRD §2.4: PartyRegistration and ClockState carry only
# id + created_at (no updated_at, no version).
# ---------------------------------------------------------------------------
class PartyRegistration(TypedDict, total=False):
    id: str
    voter_id: str
    previous_party: str
    new_party: str
    actor_role: str
    created_at: str


class ClockState(TypedDict, total=False):
    now: str


__all__ = [
    "UserRole",
    "ElectionStatus",
    "VoterStatus",
    "AbsenteeBallotStatus",
    "CuringCaseStatus",
    "BallotCastStatus",
    "VotingMachineStatus",
    "RecountRequestStatus",
    "ReasonCode",
    "SignatureMatch",
    "DefectCode",
    "BallotMethod",
    "ChallengeReason",
    "FailureReason",
    "PartyAffiliation",
    "RequestedByRole",
    "ActorRole",
    "Election",
    "Precinct",
    "Voter",
    "AbsenteeBallot",
    "CuringCase",
    "BallotCast",
    "VotingMachine",
    "RecountRequest",
    "PartyRegistration",
    "ClockState",
]
