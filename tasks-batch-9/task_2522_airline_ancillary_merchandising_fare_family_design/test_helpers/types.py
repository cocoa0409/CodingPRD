"""Typed shapes of the resources the API returns.

These are documentation-grade ``TypedDict``s: they name every field a resource
carries so a test reads like the contract.  Note that every resource except a
revenue ledger entry carries the full common set (id, created_at, updated_at,
version); a ledger entry is immutable and therefore carries only id and
created_at.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


COMMON_FIELD_NAMES = ("id", "created_at", "updated_at", "version")
IMMUTABLE_COMMON_FIELD_NAMES = ("id", "created_at")


class AncillaryProduct(CommonFields):
    sku: str
    name: str
    category: str
    list_price_cents: int
    tax_treatment: str
    revenue_class: str
    revenue_account_code: str
    refundable: bool
    disclosable_fee: bool
    product_state: str


class FareFamily(CommonFields):
    code: str
    name: str
    cabin_class: str
    base_fare_cents: int
    bundle_price_cents: int
    refundability: str
    change_fee_cents: int
    boarding_priority_tier: int
    upsell_parent_family_id: Optional[str]
    design_owner_user_id: Optional[str]
    reviewer_user_id: Optional[str]
    status: str
    revision_no: int
    unbundled_value_cents: int
    a_la_carte_total_cents: int
    bundle_discount_bp: int
    included_attribute_count: int
    fee_fingerprint: Optional[str]
    publication_count: int


class FamilyAttribute(CommonFields):
    fare_family_id: str
    ancillary_product_id: str
    inclusion: str
    included_quantity: Optional[int]
    override_price_cents: Optional[int]
    waiver_eligible: bool
    effective_unit_cents: Optional[int]
    attr_value_cents: int
    attribute_state: str


class Flight(CommonFields):
    flight_no: str
    origin: str
    destination: str
    scheduled_departure_utc: str
    cabin_seat_total: int
    sales_phase: str
    irops_state: str
    booked_load_factor_pct: int
    demand_index_bp: int
    demand_tier: str
    active_waiver_count: int
    ticketed_booking_count: int


class SeatInventorySegment(CommonFields):
    flight_id: str
    ancillary_product_id: str
    zone: str
    row_start: int
    row_end: int
    seat_letters: List[str]
    base_price_cents: int
    total_seats: int
    available_seats: int
    held_seats: int
    sold_seats: int
    zone_multiplier_bp: int
    effective_price_cents: int
    segment_state: str


class DistributionChannel(CommonFields):
    channel_code: str
    channel_type: str
    commission_bp: int
    markup_bp: int
    max_ancillary_price_cents: int
    supported_categories: List[str]
    parity_required: bool
    content_parity_status: str
    parity_breach_count: int


class ChannelPublication(CommonFields):
    fare_family_id: str
    distribution_channel_id: str
    published_family_version: int
    published_fee_fingerprint: Optional[str]
    parity_state: str
    drift_reason: Optional[str]
    last_resync_at: Optional[str]


class Booking(CommonFields):
    record_locator: str
    flight_id: str
    fare_family_id: str
    distribution_channel_id: str
    passenger_name: str
    booking_status: str
    disclosure_state: str
    disclosed_fee_fingerprint: Optional[str]
    disclosed_total_fee_cents: Optional[int]
    disclosed_unbundled_list_cents: Optional[int]
    disclosure_issued_at: Optional[str]
    disclosure_acked_at: Optional[str]
    fare_component_cents: Optional[int]
    ancillary_gross_cents: int
    recognized_ancillary_net_cents: int
    commission_cents: int
    incentive_credit_cents: int
    channel_settlement_total_cents: int
    change_fee_waived_cents: int
    waiver_applied: bool
    pending_change_fee_cents: Optional[int]
    change_count: int


class SeatAssignment(CommonFields):
    booking_id: str
    seat_inventory_segment_id: str
    row: int
    seat_letter: str
    price_charged_cents: Optional[int]
    assignment_state: str
    released_reason: Optional[str]


class AncillaryOffer(CommonFields):
    booking_id: str
    ancillary_product_id: str
    touchpoint: str
    sequence_rank: int
    pricing_variant: str
    wtp_score_bp: int
    offered_price_cents: int
    expected_value_cents: int
    valid_from: str
    valid_until: str
    offer_status: str
    accepted_price_cents: Optional[int]


class IropsWaiver(CommonFields):
    flight_id: str
    event_type: str
    delay_minutes: int
    waiver_scope: List[str]
    declared_at: str
    waiver_state: str
    credited_bookings_count: int
    credited_amount_cents: int
    rescind_reason: Optional[str]


class RevenueEntry(TypedDict):
    """The ledger is append-only, so an entry has no updated_at and no version."""

    id: str
    created_at: str
    booking_id: str
    product_sku: str
    category: str
    entry_type: str
    gross_cents: int
    tax_cents: int
    net_cents: int
    tax_treatment: str
    revenue_class: str
    revenue_account_code: str
    accounting_period: str
    source_ref: str


# Field inventories, used by tests that assert an entire payload shape.
ANCILLARY_PRODUCT_FIELDS = tuple(AncillaryProduct.__annotations__)
FARE_FAMILY_FIELDS = tuple(FareFamily.__annotations__)
FAMILY_ATTRIBUTE_FIELDS = tuple(FamilyAttribute.__annotations__)
FLIGHT_FIELDS = tuple(Flight.__annotations__)
SEAT_INVENTORY_SEGMENT_FIELDS = tuple(SeatInventorySegment.__annotations__)
DISTRIBUTION_CHANNEL_FIELDS = tuple(DistributionChannel.__annotations__)
CHANNEL_PUBLICATION_FIELDS = tuple(ChannelPublication.__annotations__)
BOOKING_FIELDS = tuple(Booking.__annotations__)
SEAT_ASSIGNMENT_FIELDS = tuple(SeatAssignment.__annotations__)
ANCILLARY_OFFER_FIELDS = tuple(AncillaryOffer.__annotations__)
IROPS_WAIVER_FIELDS = tuple(IropsWaiver.__annotations__)
REVENUE_ENTRY_FIELDS = tuple(RevenueEntry.__annotations__)

JsonDict = Dict[str, Any]
