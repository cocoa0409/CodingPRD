"""Typed dictionaries and literal enums for the Draft & Combine Operations API.

Field names mirror the API contract exactly. Every resource carries the
common fields (id, created_at, updated_at, version).
"""

from typing import List, Literal, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

UserRole = Literal[
    "LeagueDraftAdmin",
    "ClubGM",
    "ClubMedicalDirector",
    "CombineMedicalExaminer",
    "EligibilityCommittee",
    "ProspectAgent",
]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

DraftCycleStatus = Literal[
    "SETUP",
    "DECLARATION_OPEN",
    "COMBINE_WEEK",
    "ORDER_PENDING",
    "ORDER_FINAL",
    "DRAFT_LIVE",
    "DRAFT_SUSPENDED",
    "DRAFT_COMPLETE",
    "UDFA_WINDOW",
    "CLOSED",
]
CyclePosture = Literal["OPEN", "RESTRICTED", "FROZEN"]

ClubRegistrationStatus = Literal["REGISTERED", "WITHDRAWN"]
TradeAuthorizationTier = Literal["FULL", "LIMITED", "SUSPENDED"]

PositionGroup = Literal["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "ST"]
DeclarationStatus = Literal["UNDECLARED", "DECLARED", "WITHDRAWN"]
EligibilityStatus = Literal["UNREVIEWED", "ELIGIBLE", "INELIGIBLE"]
InvitationStatus = Literal[
    "NOT_INVITED", "INVITED", "ACCEPTED", "DECLINED", "WITHDRAWN"
]
ConsentStatus = Literal["NONE", "GRANTED", "REVOKED"]
ConsentScope = Literal["SUMMARY", "FULL"]
MedicalClearanceStatus = Literal["PENDING", "CLEARED", "UNVERIFIED", "FAILED"]
SigningStatus = Literal["UNSIGNED", "OFFER_OUT", "SIGNED"]

WaiverType = Literal["LATE_DECLARATION", "EARLY_ENTRY", "MEDICAL_HARDSHIP"]
WaiverStatus = Literal[
    "SUBMITTED",
    "UNDER_REVIEW",
    "INFO_REQUESTED",
    "GRANTED",
    "DENIED",
    "WITHDRAWN",
]

ExamType = Literal["ORTHO", "CARDIAC", "IMAGING", "NEURO"]
ResourceStatus = Literal["AVAILABLE", "OFFLINE"]

BookingType = Literal["MEDICAL_EXAM", "ON_FIELD_TEST", "CLUB_INTERVIEW"]
BookingStatus = Literal[
    "SCHEDULED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"
]

MedicalGrade = Literal["PASS", "PASS_WITH_NOTE", "FAIL_RECHECK", "RED_FLAG"]
ConfidentialityTier = Literal["STANDARD", "RESTRICTED"]
DisclosureState = Literal["DISCLOSABLE", "SEALED"]

ShareStatus = Literal[
    "REQUESTED", "GRANTED", "DENIED", "REVOKED", "EXPIRED", "SUPERSEDED"
]
EffectiveAccess = Literal["NONE", "SUMMARY", "FULL"]

DraftPickStatus = Literal[
    "PENDING", "ON_CLOCK", "USED", "PASSED", "FORFEITED", "LAPSED"
]
SelectionSource = Literal["ON_TIME", "AFTER_PASS", "OUT_OF_ORDER"]
PassReason = Literal["VOLUNTARY", "EXPIRED"]

TradeStatus = Literal[
    "PROPOSED",
    "COUNTERED",
    "ACCEPTED",
    "REJECTED",
    "WITHDRAWN",
    "VOIDED_BY_CAPITAL",
    "RESCINDED",
]
ConditionalConditionCode = Literal[
    "PLAYOFF_BERTH", "SNAP_THRESHOLD", "PRO_BOWL_SELECTION"
]
ConditionalProbabilityTier = Literal["LIKELY", "POSSIBLE", "REMOTE"]
ConditionalStatus = Literal[
    "NONE", "OPEN", "MET_CONVEYED", "UNMET_EXTINGUISHED", "DEFERRED", "VOID"
]

ClaimType = Literal["DEPARTURE", "ARRIVAL"]
PostseasonHonor = Literal["NONE", "ALL_CONFERENCE", "ALL_LEAGUE"]
ClaimStatus = Literal[
    "SUBMITTED", "VERIFIED", "REJECTED", "AWARDED", "REJECTED_CAP"
]

ContractOrigin = Literal["DRAFTED", "UDFA"]
ContractStatus = Literal["OFFERED", "SIGNED", "VOIDED", "LAPSED"]


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class DraftCycle(CommonFields, total=False):
    season_year: int
    declaration_deadline_at: str
    combine_week_start_at: str
    combine_week_end_at: str
    draft_start_at: str
    rounds_count: int
    compressed_final_day: bool
    status: DraftCycleStatus
    club_count: int
    lottery_completed: bool
    lottery_slot_club_ids: List[str]
    order_finalized_at: Optional[str]
    current_overall_number: Optional[int]
    udfa_window_close_at: Optional[str]
    posture: CyclePosture
    pick_inventory_chart_points: float
    pick_inventory_count: int


class Club(CommonFields, total=False):
    draft_cycle_id: str
    club_code: str
    market_name: str
    registration_status: ClubRegistrationStatus
    playoff_qualified: bool
    playoff_exit_round: int
    prior_season_win_pct: float
    strength_of_schedule: float
    head_to_head_rank: int
    lottery_combinations: int
    forfeited_round_numbers: List[int]
    pre_lottery_rank: Optional[int]
    draft_order_index: Optional[int]
    rookie_pool_total_cents: int
    rookie_pool_remaining_cents: int
    draft_capital_points: float
    trade_authorization_tier: TradeAuthorizationTier
    timeouts_remaining: int
    udfa_pool_total_cents: Optional[int]
    udfa_pool_remaining_cents: Optional[int]


class Prospect(CommonFields, total=False):
    draft_cycle_id: str
    full_name: str
    position_group: PositionGroup
    school_code: str
    seasons_played: int
    scouting_grade: float
    position_group_scarcity_rank: int
    declaration_status: DeclarationStatus
    declared_at: Optional[str]
    late_declaration_waived: bool
    early_entry_waived: bool
    eligibility_status: EligibilityStatus
    invitation_status: InvitationStatus
    consent_status: ConsentStatus
    consent_scope: Optional[ConsentScope]
    consent_expires_at: Optional[str]
    medical_clearance_status: MedicalClearanceStatus
    drafted_pick_overall_number: Optional[int]
    signing_status: SigningStatus


class EligibilityWaiver(CommonFields, total=False):
    prospect_id: str
    waiver_type: WaiverType
    rationale: str
    status: WaiverStatus
    info_request_count: int
    submitted_by_user_id: str
    opened_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]


class MedicalStation(CommonFields, total=False):
    station_code: str
    exam_type: ExamType
    turnaround_buffer_minutes: int
    status: ResourceStatus


class InterviewRoom(CommonFields, total=False):
    room_code: str
    concurrent_capacity: int
    status: ResourceStatus


class CombineBooking(CommonFields, total=False):
    prospect_id: str
    booking_type: BookingType
    medical_station_id: Optional[str]
    interview_room_id: Optional[str]
    club_id: Optional[str]
    starts_at: str
    ends_at: str
    status: BookingStatus
    duration_minutes: int


class MedicalEvaluation(CommonFields, total=False):
    combine_booking_id: str
    prospect_id: str
    filed_by_user_id: str
    findings_code: str
    medical_grade: MedicalGrade
    confidentiality_tier: ConfidentialityTier
    disclosure_state: DisclosureState
    active_share_count: int


class MedicalRecordShare(CommonFields, total=False):
    medical_evaluation_id: str
    club_id: str
    requested_by_user_id: str
    requested_by_role: Literal["ClubGM", "ClubMedicalDirector"]
    scope: ConsentScope
    status: ShareStatus
    granted_at: Optional[str]
    expires_at: Optional[str]
    effective_access: EffectiveAccess
    denial_reason: Optional[str]


class DraftPick(CommonFields, total=False):
    draft_cycle_id: str
    owning_club_id: str
    original_club_id: str
    round_number: int
    pick_in_round: int
    overall_number: int
    is_compensatory: bool
    compensatory_sequence: int
    status: DraftPickStatus
    chart_value_points: float
    slot_total_value_cents: int
    slot_signing_bonus_cents: int
    slot_first_year_cap_charge_cents: int
    slot_total_cap_commitment_cents: int
    on_clock_started_at: Optional[str]
    deadline_at: Optional[str]
    timeouts_used: int
    out_of_order_authorized: bool
    selected_prospect_id: Optional[str]
    selection_source: Optional[SelectionSource]
    pass_reason: Optional[PassReason]


class PickTrade(CommonFields, total=False):
    draft_cycle_id: str
    proposing_club_id: str
    receiving_club_id: str
    offered_pick_ids: List[str]
    requested_pick_ids: List[str]
    round_index: int
    status: TradeStatus
    last_actor_club_id: Optional[str]
    chart_balance_points: float
    imbalance_ratio: float
    surplus_balance_points: float
    conditional_round_number: Optional[int]
    conditional_condition_code: Optional[ConditionalConditionCode]
    conditional_probability_tier: Optional[ConditionalProbabilityTier]
    conditional_status: ConditionalStatus
    conditional_conveyed_overall_number: Optional[int]


class CompensatoryClaim(CommonFields, total=False):
    draft_cycle_id: str
    club_id: str
    claim_type: ClaimType
    player_name: str
    departed_apy_cents: int
    snap_pct: float
    postseason_honor: PostseasonHonor
    status: ClaimStatus
    claim_score: float
    advisory_snap_adjusted_score: float
    qualifies: bool
    awarded_round: int
    awarded_sequence: int


class PlayerContract(CommonFields, total=False):
    prospect_id: str
    club_id: str
    draft_pick_id: Optional[str]
    origin: ContractOrigin
    status: ContractStatus
    contract_years: int
    total_value_cents: int
    signing_bonus_cents: int
    first_year_cap_charge_cents: int
    total_cap_commitment_cents: int
    signed_at: Optional[str]
