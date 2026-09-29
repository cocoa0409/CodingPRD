"""
TypedDict shapes for every persisted resource of the Prepaid Restaurant
Ticketing API.

Field names and field sets are transcribed from the PRD. Every resource except
``PaymentTransaction`` carries the common ``id``, ``created_at``,
``updated_at`` and ``version`` properties; a ``PaymentTransaction`` "carries
only id and created_at, and both updated_at and version are absent from it
entirely".
"""

from typing import Any, Dict, List, Optional, TypedDict

# ─── common property sets ─────────────────────────────────────────────────

COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]
LEDGER_COMMON_FIELDS = ["id", "created_at"]
LEDGER_ABSENT_FIELDS = ["updated_at", "version"]


class Restaurant(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    service_charge_bp: int
    hold_ttl_minutes: int
    offer_ttl_minutes: int
    max_offer_rounds: int
    max_name_changes: int
    name_change_cutoff_minutes: int
    transfer_cutoff_minutes: int
    max_transfers_per_guest: int
    no_show_grace_minutes: int
    goodwill_credit_cap_cents: int
    prep_lead_minutes: int
    refund_scrutiny_threshold_cents: int


class Guest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    display_name: str
    is_broker_flagged: bool
    no_show_strikes: int
    completed_reservations_count: int
    transfers_initiated_count: int
    lifetime_refunded_cents: int
    refund_scrutiny_flag: bool


class Table(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    restaurant_id: str
    table_code: str
    seats_min: int
    seats_max: int
    turn_buffer_minutes: int


class ExperiencePackage(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    restaurant_id: str
    name: str
    course_count: int
    base_price_cents: int
    prepayment_mode: str
    deposit_bp: int
    forfeiture_schedule_code: str
    forfeiture_basis: str
    release_discount_bp: int
    kitchen_prep_minutes_per_cover: int
    min_party_size: int
    max_party_size: int


class AddOn(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    restaurant_id: str
    name: str
    price_cents: int
    prep_minutes_per_unit: int
    max_qty_per_cover: int
    order_cutoff_minutes: int
    requires_kitchen_ack: bool


class Service(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    restaurant_id: str
    service_date: str
    day_of_week: str
    meal_period: str
    seating_start_utc: str
    seating_end_utc: str
    turn_time_minutes: int
    demand_tier: str
    seats_capacity: int
    unsold_release_bp: int
    release_lead_minutes: int
    waitlist_policy: str
    kitchen_prep_capacity_minutes: int
    status: str
    release_run_count: int
    seats_released_total: int
    last_release_released_count: int
    last_release_promoted_count: int
    covers_confirmed: int
    gross_charged_cents: int
    refunded_cents: int
    forfeited_cents: int
    net_settled_cents: int


class TicketClass(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    service_id: str
    package_id: str
    seats_allocated: int
    min_party_size: int
    max_party_size: int
    seats_sold: int
    seats_held: int
    seats_released: int
    seats_available: int
    sell_through_bp: int
    list_price_per_cover_cents: int
    release_price_per_cover_cents: int
    status: str


class Reservation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    service_id: str
    ticket_class_id: str
    guest_id: str
    assigned_table_id: Optional[str]
    transferred_from_reservation_id: Optional[str]
    party_size: int
    primary_guest_name: str
    fulfillment_status: str
    payment_status: str
    is_release_priced: bool
    price_locked_per_cover_cents: int
    ticket_subtotal_cents: int
    add_on_total_cents: int
    service_charge_cents: int
    grand_total_cents: int
    deposit_due_cents: int
    deposit_frozen: bool
    balance_due_cents: int
    amount_paid_cents: int
    goodwill_applied_cents: int
    refunded_cents: int
    forfeited_cents: int
    hold_expires_at_utc: Optional[str]
    seat_from_utc: Optional[str]
    seat_to_utc: Optional[str]
    prep_minutes_total: int
    name_change_count: int
    cancel_settlement_basis: Optional[str]


class ReservationAddOn(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    reservation_id: str
    add_on_id: str
    qty: int
    unit_price_cents_locked: int
    line_subtotal_cents: int
    line_service_charge_cents: int
    line_prep_minutes: int
    ack_required: bool


class DietaryNote(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    reservation_id: str
    guest_index: int
    restriction_code: str
    severity: str
    note_text: str
    prep_minutes: int
    ack_status: str
    reject_reason_code: Optional[str]
    amend_count: int
    acked_by_user_id: Optional[str]


class WaitlistEntry(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    service_id: str
    guest_id: str
    requested_package_id: Optional[str]
    offered_reservation_id: Optional[str]
    party_size: int
    status: str
    offer_round: int
    offer_expires_at_utc: Optional[str]
    priority_penalty_applied: bool
    priority_score: int


class PaymentTransaction(TypedDict):
    """The immutable ledger row: only ``id`` and ``created_at`` are common."""

    id: str
    created_at: str
    reservation_id: str
    goodwill_credit_id: Optional[str]
    kind: str
    amount_cents: int
    signed_amount_cents: int
    memo_code: str


class RefundException(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    reservation_id: str
    reason_code: str
    requested_cents: int
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    approved_cents: int
    shortfall_cents: int
    decision_note_code: Optional[str]


class GoodwillCredit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    refund_exception_id: str
    guest_id: str
    restaurant_id: str
    issued_cents: int
    expires_at_utc: str
    redeemed_cents: int
    revoked_cents: int
    remaining_cents: int
    status: str
    issued_by_user_id: str


# ─── field sets used by the completeness assertions ───────────────────────

RESTAURANT_POLICY_KNOBS = [
    "service_charge_bp",
    "hold_ttl_minutes",
    "offer_ttl_minutes",
    "max_offer_rounds",
    "max_name_changes",
    "name_change_cutoff_minutes",
    "transfer_cutoff_minutes",
    "max_transfers_per_guest",
    "no_show_grace_minutes",
    "goodwill_credit_cap_cents",
    "prep_lead_minutes",
    "refund_scrutiny_threshold_cents",
]

TICKET_CLASS_SEAT_COUNTERS = [
    "seats_sold",
    "seats_held",
    "seats_released",
    "seats_available",
]

RESERVATION_MONEY_FIELDS = [
    "price_locked_per_cover_cents",
    "ticket_subtotal_cents",
    "add_on_total_cents",
    "service_charge_cents",
    "grand_total_cents",
    "deposit_due_cents",
    "balance_due_cents",
    "amount_paid_cents",
    "goodwill_applied_cents",
    "refunded_cents",
    "forfeited_cents",
]

ListResponse = List[Dict[str, Any]]
