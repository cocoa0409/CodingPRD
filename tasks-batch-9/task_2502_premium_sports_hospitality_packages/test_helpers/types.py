"""TypedDict shapes for every resource of the Premium Sports Hospitality API.

PRD §2.4 states that every resource carries ``id``, ``created_at``,
``updated_at`` and ``version``, and that no entity is exempt, so every shape
below extends the same common base.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Event(CommonFields):
    name: str
    sport: str
    venue_name: str
    hospitality_zone_codes: List[str]
    event_date: str
    original_event_date: Optional[str]
    status: str
    postponement_count: int
    rebook_deadline_at: Optional[str]
    fulfillment_risk_score: int
    risk_posture: str


class RightsDeal(CommonFields):
    event_id: str
    rights_holder_name: str
    inventory_type: str
    contracted_units: int
    guaranteed_minimum_units: int
    unit_cost_cents: int
    deal_status: str
    released_units: int
    shortfall_units: int
    unallocated_units: int
    minimum_liability_cents: int
    committed_by_user_id: Optional[str]
    settled_at: Optional[str]


class ReleaseTranche(CommonFields):
    rights_deal_id: str
    promised_units: int
    promised_release_at: str
    confirmed_units: int
    tranche_state: str
    confirmed_at: Optional[str]
    lapsed_at: Optional[str]


class AllocationBlock(CommonFields):
    rights_deal_id: str
    channel: str
    target_units: int
    priority_rank: int
    allocated_units: int
    committed_units: int
    released_back_units: int
    block_state: str
    recalled_at: Optional[str]


class PackageProduct(CommonFields):
    event_id: str
    name: str
    tier: str
    tickets_per_package: int
    hotel_nights: int
    transport_included: bool
    min_margin_pct: float
    package_status: str
    base_cost_cents: int
    component_price_subtotal_cents: int
    list_price_cents: int
    margin_pct: float
    priced_by_user_id: Optional[str]
    priced_at: Optional[str]
    published_by_user_id: Optional[str]
    published_at: Optional[str]


class PackageComponent(CommonFields):
    package_product_id: str
    component_type: str
    descriptor: str
    quantity: int
    unit_cost_cents: int
    markup_pct: float
    sequence_no: int
    line_cost_cents: int
    line_price_cents: int


class Client(CommonFields):
    name: str
    client_type: str
    credit_limit_cents: int
    client_status: str
    outstanding_cents: int
    overdue_installment_count: int


class Booking(CommonFields):
    client_id: str
    package_product_id: str
    channel: str
    units: int
    allocation_block_id: Optional[str]
    fulfillment_status: str
    payment_status: str
    gross_price_cents: int
    volume_discount_pct: float
    discounted_subtotal_cents: int
    partner_commission_cents: int
    guarantee_surcharge_cents: int
    net_price_cents: int
    paid_cents: int
    settlement_variant: Optional[str]
    cancellation_fee_cents: int
    refund_cents: int
    balance_due_cents: int
    credentials_issued_count: int
    credential_serial_prefix: Optional[str]
    itinerary: Optional[Dict[str, Any]]
    rebook_count: int


class PaymentInstallment(CommonFields):
    booking_id: str
    sequence_no: int
    amount_cents: int
    due_at: str
    installment_kind: str
    installment_state: str
    paid_amount_cents: int
    paid_at: Optional[str]
    days_overdue: int


class HospitalityBuild(CommonFields):
    event_id: str
    zone_code: str
    service_window_start: str
    service_window_end: str
    space_units: int
    catering_covers: int
    staff_count: int
    build_cost_cents: int
    catering_cost_cents: int
    staffing_cost_cents: int
    total_cost_cents: int
    build_state: str
    approved_by_user_id: Optional[str]


class OnSiteHost(CommonFields):
    full_name: str
    languages: List[str]
    max_concurrent_bookings: int
    active_assignment_count: int


class HostAssignment(CommonFields):
    on_site_host_id: str
    booking_id: str
    hospitality_build_id: str
    shift_start: str
    shift_end: str
    assignment_state: str
    released_at: Optional[str]


class MarginReport(TypedDict):
    """The computed read returned by GET /events/{id}/margin-report (§3.9)."""

    variant: str
    revenue_cents: int
    rights_cost_cents: int
    build_cost_cents: int
    cost_cents: int
    unsold_units: int
    unsold_exposure_cents: int
    margin_cents: int
    net_margin_cents: int
    margin_pct: float


class DailyRunReport(TypedDict):
    """The sweep answer returned by POST /operations/daily-run (§3.6)."""

    run_at: str
    lapsed_tranche_count: int
    overdue_installment_count: int
    shortfall_deal_count: int
    client_status_change_count: int


class ClockState(TypedDict):
    """The echo returned by POST /_clock/set_current_utc (§2.4)."""

    current_utc: str
