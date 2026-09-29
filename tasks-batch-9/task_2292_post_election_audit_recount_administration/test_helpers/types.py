"""Domain types for the post-election audit and recount service.

Entity TypedDicts, status/enum classes and the role enum, all named exactly as
the PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ELECTIONS_DIRECTOR = "ElectionsDirector"
    AUDIT_MANAGER = "AuditManager"
    CUSTODY_OFFICER = "CustodyOfficer"
    TALLY_TEAM_LEAD = "TallyTeamLead"
    CANVASSING_BOARD_MEMBER = "CanvassingBoardMember"
    CANDIDATE_REPRESENTATIVE = "CandidateRepresentative"
    OBSERVER = "Observer"


# ---------------------------------------------------------------------------
# Lifecycle status enums
# ---------------------------------------------------------------------------
class ElectionStatus(str, Enum):
    OPEN = "OPEN"
    CANVASSED = "CANVASSED"
    CERTIFIED = "CERTIFIED"


class ContestStatus(str, Enum):
    PENDING_CANVASS = "PENDING_CANVASS"
    CANVASSED = "CANVASSED"
    CERTIFIED = "CERTIFIED"


class BallotBatchCustodyStatus(str, Enum):
    SEALED = "SEALED"
    CHECKED_OUT = "CHECKED_OUT"
    RESEALED = "RESEALED"
    QUARANTINED = "QUARANTINED"


class AuditStatus(str, Enum):
    PLANNED = "PLANNED"
    SEEDED = "SEEDED"
    SAMPLING = "SAMPLING"
    TALLYING = "TALLYING"
    DISCREPANCY_REVIEW = "DISCREPANCY_REVIEW"
    ESCALATED_FULL_HAND_COUNT = "ESCALATED_FULL_HAND_COUNT"
    COMPLETE = "COMPLETE"
    TERMINATED = "TERMINATED"


class AuditRoundStatus(str, Enum):
    SELECTED = "SELECTED"
    TALLYING = "TALLYING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUPERSEDED = "SUPERSEDED"
    COMPLETE = "COMPLETE"


class AuditBatchRetrievalStatus(str, Enum):
    PENDING_RETRIEVAL = "PENDING_RETRIEVAL"
    RETRIEVED = "RETRIEVED"
    RETURNED = "RETURNED"


class AuditBatchTallyStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COUNTED = "COUNTED"
    VOIDED = "VOIDED"


class TallyTeamStatus(str, Enum):
    FORMING = "FORMING"
    READY = "READY"
    DISBANDED = "DISBANDED"


class ManualTallyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_ADJUDICATION = "PENDING_ADJUDICATION"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"


class DiscrepancyStatus(str, Enum):
    OPEN = "OPEN"
    DOCUMENTED = "DOCUMENTED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    VOIDED = "VOIDED"


class BallotInterpretationStatus(str, Enum):
    PENDING = "PENDING"
    ADJUDICATED = "ADJUDICATED"
    DEADLOCKED = "DEADLOCKED"


class RecountStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    DENIED = "DENIED"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class ObserverCredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Non-lifecycle enums
# ---------------------------------------------------------------------------
class ContestType(str, Enum):
    CANDIDATE = "CANDIDATE"
    MEASURE = "MEASURE"


class TimelineStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"


class AuditType(str, Enum):
    RISK_LIMITING = "RISK_LIMITING"
    COMPARISON = "COMPARISON"
    FIXED_PERCENTAGE = "FIXED_PERCENTAGE"


class MeasureVariant(str, Enum):
    NET_MARGIN_SHIFT = "NET_MARGIN_SHIFT"
    MAX_RELATIVE_OVERSTATEMENT = "MAX_RELATIVE_OVERSTATEMENT"


class CustodyEventType(str, Enum):
    INTAKE = "INTAKE"
    AUTHORIZED = "AUTHORIZED"
    CHECK_OUT = "CHECK_OUT"
    CHECK_IN = "CHECK_IN"
    QUARANTINE = "QUARANTINE"


class Party(str, Enum):
    DEM = "DEM"
    REP = "REP"
    UNAFFILIATED = "UNAFFILIATED"


class SeatRole(str, Enum):
    LEAD = "LEAD"
    COUNTER = "COUNTER"
    LIAISON = "LIAISON"


class BoardVote(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class DiscrepancyType(str, Enum):
    OVERSTATEMENT = "OVERSTATEMENT"
    UNDERSTATEMENT = "UNDERSTATEMENT"
    BALLOT_COUNT_MISMATCH = "BALLOT_COUNT_MISMATCH"


class AmbiguityType(str, Enum):
    OVERVOTE = "OVERVOTE"
    STRAY_MARK = "STRAY_MARK"
    WRITE_IN_INTENT = "WRITE_IN_INTENT"
    DAMAGED = "DAMAGED"
    PARTIAL_MARK = "PARTIAL_MARK"


class RecountTriggerType(str, Enum):
    AUTOMATIC_MARGIN = "AUTOMATIC_MARGIN"
    CANDIDATE_REQUESTED = "CANDIDATE_REQUESTED"
    AUDIT_ESCALATION = "AUDIT_ESCALATION"


class RecountScope(str, Enum):
    FULL_CONTEST = "FULL_CONTEST"
    PARTIAL_BATCHES = "PARTIAL_BATCHES"


class RefundVariant(str, Enum):
    NONE = "NONE"
    STATUTORY_REFUND = "STATUTORY_REFUND"
    PRORATED_COST_RECOVERY = "PRORATED_COST_RECOVERY"
    WITHDRAWAL_RETENTION = "WITHDRAWAL_RETENTION"


class DepositStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    HELD = "HELD"
    REFUNDED_FULL = "REFUNDED_FULL"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    FORFEITED = "FORFEITED"


class CorrectiveActionCategory(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    PROCESS = "PROCESS"
    TRAINING = "TRAINING"


class PartyAffiliation(str, Enum):
    DEM = "DEM"
    REP = "REP"
    UNAFFILIATED = "UNAFFILIATED"
    PRESS = "PRESS"


# ---------------------------------------------------------------------------
# Entity shapes.  Every entity below carries id / created_at / updated_at /
# version except CustodyEvent, which the PRD declares append-only: it carries
# only id and created_at.
# ---------------------------------------------------------------------------
class Election(TypedDict):
    id: str
    jurisdiction_code: str
    election_name: str
    election_date: str
    certification_deadline_at: str
    effective_certification_deadline_at: str
    contest_window_ends_at: str
    status: str
    timeline_status: str
    certification_risk_flag: bool
    open_audit_count: int
    open_recount_count: int
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contest(TypedDict):
    id: str
    election_id: str
    contest_label: str
    office_name: str
    contest_type: str
    candidate_names: List[str]
    ballots_cast: int
    cvr_available: bool
    reported_votes: Optional[Dict[str, int]]
    winner_name: Optional[str]
    runner_up_name: Optional[str]
    margin_votes: Optional[int]
    margin_pct: Optional[float]
    automatic_recount_required: bool
    recount_request_deadline_at: Optional[str]
    canvassed_at: Optional[str]
    status: str
    open_recount_count: int
    created_at: str
    updated_at: str
    version: int


class BallotBatch(TypedDict):
    id: str
    election_id: str
    contest_id: str
    batch_label: str
    storage_location_code: str
    ballot_count: int
    machine_votes: Dict[str, int]
    current_seal_number: str
    custody_status: str
    retrieval_authorized_at: Optional[str]
    open_checkout_count: int
    checkout_cycle_count: int
    last_checked_out_at: Optional[str]
    last_resealed_at: Optional[str]
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustodyEvent(TypedDict):
    """Append-only custody log entry: no updated_at and no version dimension."""

    id: str
    sequence_no: int
    ballot_batch_id: str
    event_type: str
    actor_user_id: str
    actor_role: str
    seal_number_before: Optional[str]
    seal_number_after: Optional[str]
    occurred_at: str
    note: Optional[str]
    created_at: str


class Audit(TypedDict):
    id: str
    contest_id: str
    audit_type: str
    risk_limit_alpha: Optional[float]
    fixed_percentage_pct: Optional[float]
    prior_error_rate: Optional[float]
    measure_variant: str
    random_seed: Optional[str]
    seed_published_at: Optional[str]
    status: str
    escalation_level: int
    planned_sample_size: Optional[int]
    sample_size_stale: bool
    cumulative_sampled_batches: int
    counted_ballots: int
    cumulative_net_error_votes: int
    discrepancy_measure: float
    projected_completion_at: Optional[str]
    slack_hours: Optional[float]
    extension_days_granted: int
    effective_slack_hours: Optional[float]
    effective_certification_deadline_at: Optional[str]
    timeline_status: str
    public_report_published: bool
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditRound(TypedDict):
    id: str
    audit_id: str
    previous_round_id: Optional[str]
    round_number: int
    is_full_hand_count: bool
    sample_size_batches: int
    selection_sequence: List[str]
    counted_ballots: int
    discrepancy_count: int
    cumulative_net_error_votes: int
    round_measure: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditBatch(TypedDict):
    id: str
    audit_round_id: str
    ballot_batch_id: str
    selection_index: int
    ballot_count: int
    retrieval_status: str
    tally_status: str
    created_at: str
    updated_at: str
    version: int


class TallyTeam(TypedDict):
    id: str
    election_id: str
    team_label: str
    room_code: str
    members: List[Dict[str, Any]]
    party_counts: Dict[str, int]
    is_bipartisan: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ManualTally(TypedDict):
    id: str
    audit_batch_id: str
    tally_team_id: str
    session_start_at: str
    session_end_at: str
    room_code: str
    counted_votes: Optional[Dict[str, int]]
    ambiguous_ballot_count: int
    no_vote_count: int
    machine_margin_votes: Optional[int]
    manual_margin_votes: Optional[int]
    net_error_votes: Optional[int]
    relative_taint: Optional[float]
    status: str
    reopen_count: int
    submitted_at: Optional[str]
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Discrepancy(TypedDict):
    id: str
    manual_tally_id: str
    discrepancy_type: str
    magnitude_votes: int
    relative_taint: float
    status: str
    documentation_note: Optional[str]
    escalation_reason: Optional[str]
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BallotInterpretation(TypedDict):
    id: str
    manual_tally_id: str
    ballot_ref: str
    ambiguity_type: str
    proposed_determination: str
    board_votes: List[Dict[str, Any]]
    votes_cast: int
    accept_count: int
    reject_count: int
    quorum_met: bool
    final_determination: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Recount(TypedDict):
    id: str
    contest_id: str
    audit_id: Optional[str]
    trigger_type: str
    requested_by_candidate_name: Optional[str]
    requested_by_user_id: str
    scope: str
    scope_batch_ids: Optional[List[str]]
    ballots_in_scope: int
    required_deposit_cents: int
    deposit_paid_cents: int
    refunded_cents: int
    forfeited_cents: int
    admin_retained_cents: int
    actual_cost_cents: int
    team_hours: Optional[float]
    refund_variant: str
    deposit_status: str
    status: str
    final_votes: Optional[Dict[str, int]]
    final_margin_votes: Optional[int]
    margin_change_votes: Optional[int]
    outcome_changed: Optional[bool]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    discrepancy_id: str
    category: str
    description: str
    due_at: str
    status: str
    completed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    completed_at: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObserverCredential(TypedDict):
    id: str
    election_id: str
    organization_name: str
    party_affiliation: str
    room_code: str
    access_start_at: str
    access_end_at: str
    status: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
