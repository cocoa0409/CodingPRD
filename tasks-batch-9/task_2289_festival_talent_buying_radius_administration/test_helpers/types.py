"""TypedDict shapes for every persisted resource.

Every resource in this API carries `id`, `created_at`, `updated_at` and
`version`; there are no exceptions, so the common fields appear on all twelve
shapes below.
"""

from typing import Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Festival(CommonFields):
    name: str
    edition_year: int
    market_latitude: float
    market_longitude: float
    event_start_date: str
    event_end_date: str
    talent_budget_cents: int
    contingency_reserve_pct: float
    allocatable_budget_cents: int
    committed_budget_cents: int
    tiers_allocated: bool
    announcement_phase: str
    lineup_posture: str
    headliner_anchor_count: int


class BudgetTier(CommonFields):
    festival_id: str
    tier_code: str
    tier_rank: int
    allocation_pct: float
    max_slots: int
    genre_focus: str
    allocation_cents: int
    committed_cents: int
    slots_committed: int
    status: str


class Stage(CommonFields):
    festival_id: str
    name: str
    capacity: int
    changeover_buffer_minutes: int
    daily_curfew_minute: int
    daily_program_minutes_cap: int
    is_flagship: bool
    booked_minutes: int


class Artist(CommonFields):
    legal_name: str
    performing_name: str
    primary_genre: str
    agency: str
    draw_score: int
    default_radius_miles: int
    reported_conflict_count: int
    radius_breach_count: int
    strict_risk_score: int
    adjudicated_risk_score: int


class Offer(CommonFields):
    festival_id: str
    artist_id: str
    budget_tier_id: str
    stage_id: str
    guarantee_cents: int
    production_fee_cents: int
    billing_position: int
    set_length_minutes: int
    slot_start_utc: str
    slot_end_utc: str
    offer_expires_utc: str
    status: str
    round_number: int
    genre_balance_factor: Optional[float]
    guarantee_ceiling_cents: Optional[int]
    issued_by_user_id: Optional[str]
    counter_guarantee_cents: Optional[int]
    counter_billing_position: Optional[int]
    counter_set_length_minutes: Optional[int]
    counter_note: Optional[str]
    decline_reason: Optional[str]
    replaces_booking_id: Optional[str]


class RadiusClause(CommonFields):
    offer_id: str
    booking_id: Optional[str]
    radius_miles: int
    window_start_date: str
    window_end_date: str
    exclusivity_scope: str
    enforcement_status: str
    waiver_status: str
    waiver_fee_cents: int
    waiver_fee_offer_cents: Optional[int]
    waiver_competing_performance_id: Optional[str]
    breach_count: int
    request_note: Optional[str]
    decision_note: Optional[str]


class CompetingPerformance(CommonFields):
    artist_id: str
    venue_city: str
    venue_latitude: float
    venue_longitude: float
    performance_date: str
    is_ticketed: bool
    is_festival: bool
    announced_capacity: Optional[int]
    status: str
    conflict_assessment: str
    conflicting_radius_clause_id: Optional[str]
    distance_to_market_miles: Optional[float]
    reported_by_user_id: str
    finding_note: Optional[str]


class Booking(CommonFields):
    festival_id: str
    artist_id: str
    budget_tier_id: str
    stage_id: str
    offer_id: str
    guarantee_cents: int
    production_fee_cents: int
    billing_position: int
    set_length_minutes: int
    slot_start_utc: str
    slot_end_utc: str
    contract_status: str
    settlement_status: str
    rider_proposed_cents: int
    rider_estimate_cents: int
    deposit_paid_cents: int
    settlement_total_cents: int
    announcement_wave_id: Optional[str]
    reveal_order: Optional[int]
    cancelled_at: Optional[str]
    cancelling_party: Optional[str]
    cancellation_reason: Optional[str]
    contractual_recovery_cents: int
    actual_recovered_cents: int
    replaces_booking_id: Optional[str]


class RiderItem(CommonFields):
    booking_id: str
    category: str
    description: str
    quantity: int
    unit_cost_cents: int
    substitute_unit_cost_cents: Optional[int]
    is_promoter_provided: bool
    approval_status: str
    line_cost_cents: int
    decision_note: Optional[str]


class AdvancePacket(CommonFields):
    booking_id: str
    stage_plot_ref: str
    input_channel_count: int
    monitor_mix_count: int
    travel_party_size: int
    load_in_offset_minutes: Optional[int]
    status: str
    submission_count: int
    channel_overage: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    return_reason: Optional[str]


class PaymentInstallment(CommonFields):
    booking_id: str
    installment_type: str
    sequence_index: int
    amount_cents: int
    due_date: str
    status: str
    released_at: Optional[str]
    paid_at: Optional[str]
    paid_amount_cents: int
    recovered_cents: int


class AnnouncementWave(CommonFields):
    festival_id: str
    wave_number: int
    phase: str
    scheduled_reveal_utc: str
    status: str
    assignment_count: int
    headliner_count: int
    published_at: Optional[str]
