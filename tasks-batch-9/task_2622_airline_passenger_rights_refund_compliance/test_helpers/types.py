"""TypedDict shapes for every resource the API returns.

Field sets follow the PRD: §2.4 for the common identity/version fields and §3
for each entity's stored and computed fields. The complaint activity trail is
append-only and immutable, so per §2.4 its rows carry only ``id`` and
``created_at`` — neither ``updated_at`` nor ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """Identity, timestamps and row version shared by every entity but the trail."""

    id: str
    created_at: str
    updated_at: str
    version: int


class PolicyProfile(CommonFields):
    carrier_code: str
    domestic_significant_delay_minutes: int
    international_significant_delay_minutes: int
    credit_card_refund_deadline_days: int
    other_method_refund_deadline_days: int
    bag_delay_threshold_hours_domestic: int
    bag_delay_threshold_hours_international: int
    tarmac_deplane_deadline_minutes_domestic: int
    tarmac_deplane_deadline_minutes_international: int
    complaint_ack_deadline_days: int
    complaint_answer_deadline_days_general: int
    complaint_answer_deadline_days_disability: int
    travel_credit_default_permitted: bool
    travel_credit_election_bonus_pct: float
    report_count: int
    open_violation_count: int


class Passenger(CommonFields):
    email: str
    full_name: str
    requires_disability_assistance: bool
    travel_credit_balance_cents: int
    open_complaint_count: int


class Booking(CommonFields):
    passenger_id: str
    policy_profile_id: str
    record_locator: str
    total_fare_cents: int
    payment_method: str
    itinerary_scope: str
    collected_total_cents: int
    total_refund_obligated_cents: int
    earliest_refund_deadline_utc: Optional[str]
    disruption_posture: str
    segment_count: int
    unused_segment_count: int
    travel_commenced: bool
    suppressed_obligation_count: int


class FlightSegment(CommonFields):
    booking_id: str
    sequence_index: int
    flight_number: str
    origin_iata: str
    destination_iata: str
    is_international: bool
    scheduled_departure_utc: str
    scheduled_arrival_utc: str
    segment_fare_cents: int
    status: str
    disruption_type: str
    revised_arrival_utc: Optional[str]
    delay_minutes: int
    is_significant_delay: bool
    disruption_declared_at_utc: Optional[str]
    actual_departure_utc: Optional[str]
    actual_arrival_utc: Optional[str]
    cumulative_tarmac_minutes: int
    exempted_tarmac_event_count: int


class AncillaryPurchase(CommonFields):
    booking_id: str
    flight_segment_id: str
    service_type: str
    amount_cents: int
    delivery_status: str
    non_provision_reason: Optional[str]
    refund_obligation_created: bool


class CheckedBag(CommonFields):
    booking_id: str
    tag_number: str
    fee_cents: int
    checked_at_utc: str
    scheduled_delivery_utc: str
    delivered_at_utc: Optional[str]
    loss_declared_at_utc: Optional[str]
    status: str
    delivery_delay_hours: float
    fee_refund_obligated: bool


class DeniedBoardingRecord(CommonFields):
    booking_id: str
    flight_segment_id: str
    category: str
    oversale_confirmed: bool
    written_disclosure_provided: bool
    one_way_fare_cents: int
    substitute_arrival_utc: str
    voluntary_agreed_amount_cents: Optional[int]
    substitute_delay_minutes: int
    statutory_compensation_cents: int
    compensation_cents: int
    effective_category: Optional[str]
    status: str
    finalized_at_utc: Optional[str]


class TarmacDelayEvent(CommonFields):
    flight_segment_id: str
    tarmac_start_utc: str
    phase: str
    status: str
    interval_end_utc: Optional[str]
    deplane_completed_utc: Optional[str]
    exemption_reason: Optional[str]
    exemption_declared_at_utc: Optional[str]
    tarmac_minutes: int
    deadline_minutes: int
    is_violation: bool
    report_reference: Optional[str]
    corrective_action_summary: Optional[str]
    report_filed_at_utc: Optional[str]


class RefundObligation(CommonFields):
    booking_id: str
    flight_segment_id: Optional[str]
    checked_bag_id: Optional[str]
    ancillary_purchase_id: Optional[str]
    denied_boarding_record_id: Optional[str]
    basis: str
    issuance_mode: str
    variant_applied: str
    gross_entitlement_cents: int
    headroom_at_creation_cents: int
    amount_cents: int
    credit_bonus_cents: int
    payable_total_cents: int
    election_status: str
    election_source: Optional[str]
    credit_consent_reference: Optional[str]
    settlement_status: str
    settlement_method: Optional[str]
    obligation_start_utc: str
    deadline_utc: str
    election_deadline_utc: str
    deadline_breached: bool
    settlement_attempt_count: int
    settlement_initiated_at_utc: Optional[str]
    settled_at_utc: Optional[str]
    last_failure_reason: Optional[str]
    void_reason: Optional[str]
    created_by_user_id: Optional[str]
    settlement_initiated_by_user_id: Optional[str]


class ConsumerComplaint(CommonFields):
    booking_id: str
    category: str
    channel: str
    received_at_utc: str
    summary: str
    status: str
    ack_due_utc: str
    answer_due_utc: str
    acknowledged_at_utc: Optional[str]
    answered_at_utc: Optional[str]
    info_requested_count: int
    reopen_count: int
    ack_breached: bool
    answer_breached: bool
    disposition: Optional[str]
    accessibility_resolution_code: Optional[str]
    granted_amount_cents: int


class ComplaintActivity(TypedDict):
    """Append-only trail row: PRD §2.4 gives it only ``id`` and ``created_at``."""

    id: str
    created_at: str
    complaint_id: str
    activity_type: str
    occurred_at_utc: str
    actor_role: str
    actor_user_id: Optional[str]
    detail: Optional[str]


class RegulatorReport(CommonFields):
    policy_profile_id: str
    period_start_utc: str
    period_end_utc: str
    status: str
    complaint_count: int
    disability_complaint_count: int
    late_answer_count: int
    tarmac_violation_count: int
    involuntary_denied_boarding_count: int
    refund_obligation_cents_total: int
    overdue_refund_count: int
    policy_version_pinned: int
    submitted_at_utc: Optional[str]
    amendment_count: int
    amendment_reason: Optional[str]
    submitted_by_user_id: Optional[str]


class RefundExposure(TypedDict):
    """The computed, non-persisting exposure read of PRD §3.6."""

    proactive_full_itinerary_cents: int
    request_based_proration_cents: int
    variant_delta_cents: int
    obligated_total_cents: int
    remaining_headroom_cents: int
    collected_total_cents: int
    segment_count: int
    unused_segment_count: int
    travel_commenced: bool


class SweepResult(TypedDict):
    """The compliance sweep counters of PRD §3.9."""

    policy_profile_id: str
    deadline_breach_flagged_count: int
    election_auto_defaulted_count: int
    complaint_ack_breach_flagged_count: int
    complaint_answer_breach_flagged_count: int
    complaint_auto_closed_count: int
    open_violation_count: int
    policy_profile_version: int


class ClockReading(TypedDict):
    """The logical-clock control response of PRD §2.8."""

    current_utc: str


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
