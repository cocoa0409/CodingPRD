"""TypedDict shapes for every entity the API returns.

Field names follow the PRD prose exactly. These types are advisory: they document
the response shape for readers and give editors autocompletion; they are not
enforced at runtime.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

__all__ = [
    "InsurancePlan",
    "Patient",
    "Prescription",
    "FillCycle",
    "CycleLine",
    "PouchRoll",
    "Pouch",
    "PouchContent",
    "Shipment",
    "RefillAuthorizationRequest",
    "VacationExceptionRequest",
    "CreditMemo",
    "AdherenceEvent",
    "AdherenceSummary",
    "Clock",
    "JsonDict",
]

JsonDict = Dict[str, Any]


class InsurancePlan(TypedDict, total=False):
    """Payer plan carrying the edit thresholds and the three per-day copay rates."""

    id: str
    payer_name: str
    bin_number: str
    generic_copay_cents_per_day: int
    brand_copay_cents_per_day: int
    specialty_copay_cents_per_day: int
    refill_too_soon_threshold_pct: int
    max_day_supply_days: int
    vacation_overrides_per_year: int
    coinsurance_pct: int
    allows_payer_vacation_override: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    """Enrolled patient with synchronization, auto-ship, adherence and credit figures."""

    id: str
    full_name: str
    date_of_birth: str
    email: str
    state_code: str
    insurance_plan_id: str
    sync_status: str
    sync_mode: Optional[str]
    anchor_fill_day: Optional[int]
    next_cycle_start_date: Optional[str]
    autoship_status: str
    pause_reason: Optional[str]
    adherence_score_pct: int
    consecutive_missed_pickups: int
    credit_balance_cents: int
    vacation_exceptions_used_this_year: int
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    """Recorded prescription with refill, dispense-history and packability state."""

    id: str
    patient_id: str
    prescriber_npi: str
    drug_name: str
    ndc: str
    strength: str
    form: str
    copay_tier: str
    dose_times: List[str]
    quantity_per_dose: int
    days_supply_written: int
    refills_authorized: int
    refills_remaining: int
    refills_consumed: int
    written_date: str
    expiration_date: str
    refrigerated: bool
    is_controlled: bool
    packable: bool
    status: str
    last_dispensed_date: Optional[str]
    last_dispensed_days_supply: int
    prior_last_dispensed_date: Optional[str]
    prior_last_dispensed_days_supply: int
    days_dispensed_total: int
    sync_bridge_days: int
    sync_trim_days: int
    supersedes_rx_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FillCycle(TypedDict, total=False):
    """Fill cycle carrying both independent state dimensions and its money figures."""

    id: str
    patient_id: str
    cycle_start_date: str
    cycle_end_date: str
    day_supply_days: int
    sync_mode: str
    packaging_status: str
    insurance_status: str
    total_copay_cents: int
    final_copay_cents: Optional[int]
    rounding_delta_cents: Optional[int]
    credit_applied_cents: int
    reissue_fee_cents: int
    approved_vacation_extra_days: int
    vacation_exception_id: Optional[str]
    is_partial_reissue: bool
    reissue_of_cycle_id: Optional[str]
    reissue_required: bool
    roll_pouch_count: int
    created_at: str
    updated_at: str
    version: int


class CycleLine(TypedDict, total=False):
    """One claim line of a cycle with its routing, day-supply and copay figures."""

    id: str
    cycle_id: str
    prescription_id: str
    line_status: str
    hold_reason: Optional[str]
    line_start_date: Optional[str]
    line_end_date: Optional[str]
    days_supply_filled: int
    bridge_days_applied: int
    trim_days_applied: int
    quantity_dispensed: int
    refill_pct_used: int
    allowance_days: int
    copay_cents: int
    packable_route: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PouchRoll(TypedDict, total=False):
    """Dose-time pouch roll with its segment, pack and verification identities."""

    id: str
    cycle_id: str
    roll_serial: str
    segment_start_date: str
    segment_end_date: str
    pouch_count: int
    verification_status: str
    packed_by_user_id: Optional[str]
    packed_at: Optional[str]
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    mismatch_pouch_count: int
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class PouchContent(TypedDict, total=False):
    """One contributing line's contribution to a single pouch."""

    prescription_id: str
    quantity: int


class Pouch(TypedDict, total=False):
    """One pouch of a roll with its contents, expected count and imaging result."""

    id: str
    roll_id: str
    pouch_index: int
    dose_date: str
    dose_slot: str
    contents: List[PouchContent]
    expected_pill_count: int
    detected_pill_count: Optional[int]
    verification_result: str
    image_confidence_pct: Optional[int]
    imaged_by_user_id: Optional[str]
    imaged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    """One parcel of a cycle's split shipment with freight cost and transit stamps."""

    id: str
    cycle_id: str
    shipment_kind: str
    carrier_service: str
    packaging: str
    status: str
    covers_line_ids: List[str]
    ship_cost_cents: int
    tracking_number: Optional[str]
    cold_chain_excursion_minutes: int
    staged_at: Optional[str]
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    pickup_confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefillAuthorizationRequest(TypedDict, total=False):
    """Prescriber chase with its round counters and response window stamps."""

    id: str
    prescription_id: str
    prescriber_npi: str
    requested_refills: int
    approved_refills: Optional[int]
    status: str
    chase_round: int
    escalation_level: int
    first_sent_at: Optional[str]
    last_sent_at: Optional[str]
    next_chase_due_at: Optional[str]
    no_response_recorded_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VacationExceptionRequest(TypedDict, total=False):
    """Travel early-supply exception with its approved days and waiver flag."""

    id: str
    patient_id: str
    travel_start_date: str
    travel_end_date: str
    requested_extra_days: int
    approved_extra_days: Optional[int]
    status: str
    waives_refill_too_soon: bool
    denial_reason: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditMemo(TypedDict, total=False):
    """Credit ledger row with its amount, reason and application state."""

    id: str
    patient_id: str
    cycle_id: str
    reason: str
    amount_cents: int
    status: str
    applied_to_cycle_id: Optional[str]
    applied_at: Optional[str]
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class AdherenceEvent(TypedDict, total=False):
    """Immutable adherence event.

    Unlike every other entity this row carries only ``id`` and ``created_at``
    beyond its own payload: it has no ``updated_at`` and no ``version``, because
    it is never modified or deleted.
    """

    id: str
    cycle_id: str
    event_type: str
    occurred_at: str
    dose_slot: Optional[str]
    pouch_index: Optional[int]
    source: str
    created_at: str


class AdherenceSummary(TypedDict, total=False):
    """Computed read exposing both adherence variants side by side."""

    patient_id: str
    rolling_28_day_score_pct: int
    cycle_scoped_score_pct: int
    taken_count: int
    missed_count: int
    expected_pouch_count: int
    consecutive_missed_pickups: int
    autoship_status: str


class Clock(TypedDict, total=False):
    """Response of the logical-clock setter."""

    current_utc: str
