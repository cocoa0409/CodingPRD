"""Domain types for the Hall of Fame Induction & Voting Administration API.

Entity TypedDicts, status enums and the role enum, all derived from the PRD.
Entities that carry only ``id`` and ``created_at`` (EligibilityRule, VoterBloc)
deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    ELECTION_ADMINISTRATOR = "ElectionAdministrator"
    SCREENING_COMMITTEE_MEMBER = "ScreeningCommitteeMember"
    ELECTOR = "Elector"
    INDEPENDENT_AUDITOR = "IndependentAuditor"
    CURATORIAL_STAFF = "CuratorialStaff"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class CycleStatus(str, Enum):
    SETUP = "SETUP"
    NOMINATIONS_OPEN = "NOMINATIONS_OPEN"
    SCREENING = "SCREENING"
    BALLOTING = "BALLOTING"
    CERTIFIED = "CERTIFIED"
    CEREMONY_PLANNED = "CEREMONY_PLANNED"
    CLOSED = "CLOSED"


class AusterityTier(str, Enum):
    FULL = "FULL"
    REDUCED = "REDUCED"
    MINIMAL = "MINIMAL"


class Category(str, Enum):
    PLAYER = "PLAYER"
    COACH = "COACH"
    CONTRIBUTOR = "CONTRIBUTOR"


class Pathway(str, Enum):
    MODERN = "MODERN"
    VETERANS = "VETERANS"
    POSTHUMOUS = "POSTHUMOUS"
    SPECIAL = "SPECIAL"


class HofStatus(str, Enum):
    NOT_INDUCTED = "NOT_INDUCTED"
    INDUCTED = "INDUCTED"
    PERMANENTLY_INELIGIBLE = "PERMANENTLY_INELIGIBLE"


class CandidacyStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    INFO_REQUESTED = "INFO_REQUESTED"
    ADVANCED = "ADVANCED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    ON_BALLOT = "ON_BALLOT"
    ELECTED = "ELECTED"
    CARRYOVER_ELIGIBLE = "CARRYOVER_ELIGIBLE"
    EXPIRED = "EXPIRED"
    ELIMINATED = "ELIMINATED"
    STRUCK = "STRUCK"


class ElectorStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CREDENTIALED = "CREDENTIALED"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"


class VotingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class TallyStatus(str, Enum):
    NOT_TALLIED = "NOT_TALLIED"
    PENDING_AUDIT = "PENDING_AUDIT"
    AUDIT_REJECTED = "AUDIT_REJECTED"
    AUDIT_CERTIFIED = "AUDIT_CERTIFIED"


class BallotOutcome(str, Enum):
    ELECTION_COMPLETE = "ELECTION_COMPLETE"
    RUNOFF_REQUIRED = "RUNOFF_REQUIRED"
    NO_ELECTION = "NO_ELECTION"


class SlotStatus(str, Enum):
    LISTED = "LISTED"
    ELECTED = "ELECTED"
    NOT_ELECTED = "NOT_ELECTED"
    CARRIED_TO_RUNOFF = "CARRIED_TO_RUNOFF"
    STRUCK = "STRUCK"


class SubmissionStatus(str, Enum):
    COUNTED = "COUNTED"
    WITHDRAWN = "WITHDRAWN"
    INVALIDATED = "INVALIDATED"


class InductionStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    ENSHRINED = "ENSHRINED"


class TravelStatus(str, Enum):
    PENDING = "PENDING"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    WAIVED = "WAIVED"


class ArtifactStatus(str, Enum):
    AWAITED = "AWAITED"
    RECEIVED = "RECEIVED"
    EXEMPT = "EXEMPT"


class ExhibitStatus(str, Enum):
    NOT_PLANNED = "NOT_PLANNED"
    INSTALLED = "INSTALLED"


class DelegationType(str, Enum):
    LIVING = "LIVING"
    POSTHUMOUS_DELEGATION = "POSTHUMOUS_DELEGATION"


class GrantVariant(str, Enum):
    LIVING_INDUCTEE = "LIVING_INDUCTEE"
    POSTHUMOUS_DELEGATION = "POSTHUMOUS_DELEGATION"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class InstallationStatus(str, Enum):
    INSTALLED = "INSTALLED"
    WITHDRAWN = "WITHDRAWN"


# --------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------
class InductionCycle(TypedDict):
    id: str
    cycle_year: int
    sport_code: str
    max_inductees: int
    status: str
    current_round: int
    nomination_count: int
    advanced_candidacy_count: int
    special_election_used: int
    credentialed_roster_count: int
    ceremony_date: Optional[str]
    ceremony_venue: Optional[str]
    travel_budget_cents: int
    travel_committed_cents: int
    escort_pool_size: int
    austerity_tier: str
    induction_count: int
    ceremony_ready_count: int
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    full_name: str
    category: str
    retirement_year: int
    career_seasons: int
    career_metric_value: float
    is_deceased: bool
    death_year: Optional[int]
    hof_status: str
    permanently_ineligible_reason: Optional[str]
    ballot_appearances_used: int
    veterans_eligible_from_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Candidacy(TypedDict):
    id: str
    cycle_id: str
    candidate_id: str
    nominated_by_elector_id: str
    screened_by_elector_id: Optional[str]
    carryover_from_candidacy_id: Optional[str]
    pathway: str
    justification: Optional[str]
    status: str
    eligible_from_year: int
    appearance_number: Optional[int]
    info_request_count: int
    latest_round_votes: int
    latest_round_pct: float
    screening_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Elector(TypedDict):
    id: str
    full_name: str
    bloc_id: str
    is_screening_member: bool
    credential_expires_on: Optional[str]
    status: str
    consecutive_missed_cycles: int
    last_participated_cycle_year: Optional[int]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict):
    id: str
    cycle_id: str
    round_number: int
    voting_status: str
    tally_status: str
    opens_at: str
    closes_at: str
    max_votes_per_elector: int
    slot_count: int
    ballots_cast: int
    total_selections_counted: int
    credentialed_roster_at_close: int
    threshold_votes_provisional: int
    threshold_votes_final: int
    elected_slot_count: int
    outcome: Optional[str]
    tallied_by_user_id: Optional[str]
    audit_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BallotSlot(TypedDict):
    id: str
    ballot_id: str
    candidacy_id: str
    candidate_name_snapshot: str
    pathway_snapshot: str
    candidacy_version_pinned: int
    votes_received: int
    vote_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class VoteSubmission(TypedDict):
    id: str
    ballot_id: str
    elector_id: str
    selected_slot_ids: Optional[List[str]]
    selection_count: int
    is_abstention: bool
    status: str
    ballot_version_after: int
    cast_at: str
    invalidated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Induction(TypedDict):
    id: str
    cycle_id: str
    candidacy_id: str
    candidate_id: str
    status: str
    travel_status: str
    artifact_status: str
    exhibit_status: str
    delegation_type: str
    artifact_count: int
    ceremony_ready: bool
    created_at: str
    updated_at: str
    version: int


class TravelGrant(TypedDict):
    id: str
    cycle_id: str
    induction_id: str
    nights: int
    requested_airfare_cents: int
    escort_from: Optional[str]
    escort_to: Optional[str]
    variant: str
    traveler_count: int
    austerity_tier_applied: str
    award_cents: int
    status: str
    cycle_version_after: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExhibitCase(TypedDict):
    id: str
    case_code: str
    capacity_artifacts: int
    changeover_buffer_days: int
    artifacts_installed: int
    created_at: str
    updated_at: str
    version: int


class ExhibitInstallation(TypedDict):
    id: str
    induction_id: str
    exhibit_case_id: str
    display_starts_on: str
    display_ends_on: str
    artifact_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Entities carrying ONLY id + created_at (no updated_at, no version)
# --------------------------------------------------------------------------
class EligibilityRule(TypedDict):
    id: str
    category: str
    pathway: str
    waiting_period_years: int
    min_career_seasons: int
    min_career_metric: float
    max_ballot_appearances: int
    election_threshold_pct: float
    carryover_min_pct: float
    runoff_floor_pct: float
    created_at: str


class VoterBloc(TypedDict):
    id: str
    bloc_code: str
    name: str
    seat_cap: int
    min_participation_pct: float
    seats_filled: int
    created_at: str
