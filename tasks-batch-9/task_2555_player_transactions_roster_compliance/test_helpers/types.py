"""TypedDict shapes for every resource the API returns.

Two field families exist. Almost every resource carries the identity block of
PRD 2.4 - ``id``, ``created_at``, ``updated_at`` and ``version``. The compliance
check row is the single exception: it is an immutable event record that carries
only ``id`` and ``created_at``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class VersionedResource(TypedDict):
    """Identity block shared by every mutable resource (PRD 2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableResource(TypedDict):
    """Identity block for an immutable event row: no updated_at, no version."""

    id: str
    created_at: str


class Team(VersionedResource):
    name: str
    market_code: str
    salary_cap_limit_cents: int
    active_roster_limit: int
    reserve_roster_limit: int
    injured_reserve_limit: int
    practice_squad_limit: int
    waiver_priority_rank: int
    active_roster_count: int
    reserve_roster_count: int
    injured_reserve_count: int
    practice_squad_count: int
    provisional_cap_committed_cents: int
    final_cap_committed_cents: int
    dead_money_cents: int
    cap_space_cents: int
    open_medical_review_count: int
    compliance_status: str
    grace_expires_at: Optional[str]
    consecutive_noncompliant_checks: int


class Player(VersionedResource):
    full_name: str
    position: str
    current_team_id: Optional[str]
    roster_designation: str
    medical_status: str
    designation_effective_at: str
    accrued_active_days: int
    accrued_reserve_days: int
    accrued_ir_days: int
    accrued_practice_days: int
    practice_squad_seasons_used: int
    pension_credit_days: int
    roster_service_days: int
    service_years: int
    contract_rights_class: str
    practice_squad_eligible: bool
    waiver_revocability_class: str
    last_physical_passed_at: Optional[str]


class Contract(VersionedResource):
    player_id: str
    team_id: str
    signed_via_transaction_id: Optional[str]
    status: str
    years: int
    base_salary_cents: int
    base_guaranteed: bool
    signing_bonus_cents: int
    start_season_year: int
    is_practice_squad_contract: bool
    proration_years: int
    annual_proration_cents: int
    final_season_proration_cents: int
    current_season_cap_charge_cents: int
    total_value_cents: int
    option_type: str
    option_deadline_at: Optional[str]
    option_salary_cents: Optional[int]
    option_status: str
    dead_money_current_season_cents: int
    dead_money_next_season_cents: int
    termination_reason: Optional[str]


class BonusAllocation(VersionedResource):
    contract_id: str
    bonus_type: str
    season_year: int
    amount_cents: int
    allocation_status: str
    counts_against_provisional: bool
    earned_at: Optional[str]


class Transaction(VersionedResource):
    team_id: str
    player_id: str
    transaction_type: str
    status: str
    target_designation: Optional[str]
    injury_designation_id: Optional[str]
    filing_deadline_at: str
    filed_at: Optional[str]
    decided_at: Optional[str]
    effective_at: Optional[str]
    rejection_reason: Optional[str]
    revision_count: int
    requires_physical: bool
    filed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    contract_id: Optional[str]
    prior_designation: Optional[str]


class WaiverRequest(VersionedResource):
    player_id: str
    from_team_id: str
    transaction_id: str
    contract_id: Optional[str]
    origin_designation: str
    revocability: str
    status: str
    placed_at: str
    clearance_deadline_at: str
    processed_at: Optional[str]
    awarded_to_team_id: Optional[str]
    claim_count: int
    releasing_team_dead_money_cents: int


class WaiverClaim(VersionedResource):
    waiver_request_id: str
    claiming_team_id: str
    status: str
    priority_rank_snapshot: int
    cap_space_snapshot_cents: int
    required_cap_charge_cents: int
    submitted_at: str


class Trade(VersionedResource):
    initiating_team_id: str
    counterparty_team_id: str
    status: str
    conditional_clause_type: str
    condition_note: Optional[str]
    round_count: int
    accepted_at: Optional[str]
    medical_review_deadline_at: Optional[str]
    executed_at: Optional[str]
    void_reason: Optional[str]
    cap_delta_initiating_cents: int
    cap_delta_counterparty_cents: int


class TradeAsset(VersionedResource):
    trade_id: str
    asset_kind: str
    direction: str
    contract_id: Optional[str]
    draft_pick_year: Optional[int]
    draft_pick_round: Optional[int]
    cash_amount_cents: Optional[int]
    status: str
    cap_charge_snapshot_cents: int


class QualifyingOffer(VersionedResource):
    player_id: str
    team_id: str
    offer_type: str
    tender_level: str
    prior_base_salary_cents: int
    amount_cents: int
    deadline_at: str
    status: str
    issued_at: str
    responded_at: Optional[str]
    resulting_transaction_id: Optional[str]


class InjuryDesignation(VersionedResource):
    player_id: str
    team_id: str
    designation_type: str
    status: str
    paperwork_reference: Optional[str]
    placed_at: str
    paperwork_filed_at: Optional[str]
    activated_at: Optional[str]
    minimum_stay_days: int
    return_window_opens_at: Optional[str]
    return_window_closes_at: Optional[str]
    ir_service_credit_days: Optional[int]
    closed_at: Optional[str]


class PhysicalExam(VersionedResource):
    player_id: str
    team_id: str
    transaction_id: Optional[str]
    trade_id: Optional[str]
    exam_type: str
    status: str
    window_start_at: str
    window_end_at: str
    performed_at: Optional[str]
    result_recorded_at: Optional[str]
    expires_at: Optional[str]


class ComplianceCheck(ImmutableResource):
    """An immutable sweep row: only id and created_at from the identity block."""

    team_id: str
    checked_at: str
    active_roster_count: int
    reserve_roster_count: int
    injured_reserve_count: int
    practice_squad_count: int
    final_cap_committed_cents: int
    cap_space_cents: int
    violation_codes: List[str]
    result: str
    grace_expires_at: Optional[str]
    resulting_compliance_status: str


# The cap-ledger view is a computed read that returns the club itself with both
# cap variants recomputed side by side, so it carries the Team shape.
CapLedger = Team


Headers = Dict[str, str]
Payload = Dict[str, Any]

VERSIONED_IDENTITY_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_IDENTITY_FIELDS = ("id", "created_at")
