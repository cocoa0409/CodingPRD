"""
TypedDict shapes for every entity the API returns.

These exist for editor clarity and for the shape assertions in ``assertions.py``;
the tests themselves read plain dicts out of the response envelope.

Note that ``PaymentEvent`` deliberately omits ``updated_at`` and ``version``:
the PRD states the payment ledger is append-only and its rows carry only ``id``
and ``created_at`` of the common field block.
"""

from typing import Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Sailing(CommonFields):
    ship_code: str
    voyage_code: str
    embark_date: str
    nights: int
    total_lower_berths: int
    final_payment_days_before: int
    deposit_due_days_after_booking: int
    status: str
    suspension_count: int
    suspension_reason: Optional[str]
    inventory_posture: str
    lower_berths_sold: int
    third_berths_sold: int
    fourth_berths_sold: int
    occupancy_pct: float
    gross_ticket_revenue_cents: int
    projected_onboard_revenue_cents: int
    compensation_liability_cents: int
    available_lower_berth_days_gross: int
    available_lower_berth_days_net: int
    ralbd_gross_cents: int
    ralbd_net_cents: int
    revenue_alert: bool
    confirmed_bookings_count: int
    paid_in_full_bookings_count: int
    final_payment_risk_flag: bool


class CabinCategory(CommonFields):
    code: str
    tier_rank: int
    is_guarantee: bool
    lower_berths: int
    max_occupancy: int
    onboard_spend_lower_per_night_cents: int
    onboard_spend_upper_per_night_cents: int
    upgrade_to_category_id: Optional[str]
    upgrade_chain_length: int


class SailingInventory(CommonFields):
    sailing_id: str
    cabin_category_id: str
    physical_cabins: int
    oversell_allowance: int
    effective_oversell_cabins: int
    group_held_cabins: int
    booked_cabins: int
    waitlisted_bookings_count: int
    available_cabins: int
    released_cabins_total: int


class FareRule(CommonFields):
    sailing_id: str
    cabin_category_id: str
    window_open_days_to_sail: int
    window_close_days_to_sail: int
    base_lower_berth_fare_cents: int
    third_berth_fare_cents: int
    fourth_berth_fare_cents: int
    bookings_pinned_count: int


class Promotion(CommonFields):
    sailing_id: str
    code: str
    audience: str
    discount_pct: float
    starts_on: str
    ends_on: str
    max_redemptions: int
    redemption_count: int
    status: str
    withdraw_reason: Optional[str]


class GroupBlock(CommonFields):
    sailing_id: str
    cabin_category_id: str
    agency_name: str
    cabins_held: int
    picked_up_cabins: int
    review_date: str
    release_policy: str
    status: str
    review_count: int
    review_extension_count: int
    released_cabins_total: int
    created_by_user_id: str
    confirmed_by_user_id: Optional[str]
    contract_reference: Optional[str]


class Guest(CommonFields):
    full_name: str
    email: str
    prior_sailings_count: int
    loyalty_tier: str
    repeat_guest_offer_pct: float
    bookings_count: int


class Booking(CommonFields):
    sailing_id: str
    cabin_category_id: str
    assigned_cabin_category_id: Optional[str]
    guest_id: str
    group_block_id: Optional[str]
    promotion_id: Optional[str]
    fare_rule_id: str
    pinned_fare_rule_version: int
    occupancy_adults: int
    third_berth_guests: int
    fourth_berth_guests: int
    guest_count: int
    allow_waitlist: bool
    booking_status: str
    payment_status: str
    booked_days_to_sail: int
    lower_berth_subtotal_cents: int
    berth_discount_pct: float
    third_berth_net_cents: int
    fourth_berth_net_cents: int
    gross_ticket_cents: int
    promo_discount_cents: int
    loyalty_discount_cents: int
    net_ticket_cents: int
    upgrade_charge_cents: int
    itinerary_compensation_obc_cents: int
    itinerary_refund_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    deposit_due_cents: int
    deposit_due_date: str
    final_payment_due_date: str
    payment_terms: str
    provisional_penalty_cents: Optional[int]
    cancellation_penalty_cents: Optional[int]
    refund_cents: Optional[int]
    cancelled_at: Optional[str]
    cancel_reason: Optional[str]
    settled_at: Optional[str]
    delinquent_since: Optional[str]
    projected_onboard_gross_cents: int
    projected_onboard_net_cents: int
    created_by_user_id: str


class PaymentEvent(TypedDict):
    """Append-only ledger row: no ``updated_at``, no ``version`` (PRD §2.4)."""

    id: str
    created_at: str
    booking_id: str
    kind: str
    amount_cents: int
    posted_at: str
    resulting_payment_status: str
    note: Optional[str]


class UpgradeBid(CommonFields):
    booking_id: str
    target_cabin_category_id: str
    bid_amount_per_guest_cents: int
    guest_count: int
    min_acceptable_per_guest_cents: int
    countered_min_per_guest_cents: Optional[int]
    counter_rounds: int
    award_amount_cents: Optional[int]
    submitted_days_to_sail: int
    status: str
    decline_reason: Optional[str]


class ItineraryChange(CommonFields):
    sailing_id: str
    kind: str
    affected_port_code: str
    compensation_policy: str
    obc_per_guest_cents: int
    refund_pct: float
    status: str
    published_at: Optional[str]
    affected_bookings_count: int
    total_obc_granted_cents: int
    total_refund_granted_cents: int
