"""
Entity shapes and enumerations for the Trade Show Exhibitor Sales API.

The TypedDicts below name every field PRD.md says a row carries, so a test can
assert the *presence* of a field as well as its value.  Note the deliberate
asymmetry around the common system fields: §2.4 says most rows carry
`updated_at` and `version` while "a lead scan carries only `id` and
`created_at`.  It has no `updated_at` and no `version` field at all."
"""

from typing import List, Optional, TypedDict


# ─── Roles (§2.1) ────────────────────────────────────────────────────────────
class Role:
    """"Exactly five roles are recognised, spelled precisely as follows"."""

    SHOW_DIRECTOR = "ShowDirector"
    SALES_REP = "SalesRep"
    FLOOR_MANAGER = "FloorManager"
    EXHIBITOR = "Exhibitor"
    REGISTRANT = "Registrant"

    ALL = [SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR, REGISTRANT]


# ─── Status enumerations ─────────────────────────────────────────────────────
class VenueContractStatus:
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class ShowStatus:
    PLANNING = "PLANNING"
    SPACE_SELECTION = "SPACE_SELECTION"
    SELLING = "SELLING"
    ON_SITE = "ON_SITE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FloorPosture:
    """"it takes one of exactly three values: `OPEN`, `SPACE_LOCKED`, or `FROZEN`"."""

    OPEN = "OPEN"
    SPACE_LOCKED = "SPACE_LOCKED"
    FROZEN = "FROZEN"


class BoothStatus:
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    ASSIGNED = "ASSIGNED"
    MERGED = "MERGED"


class LocationClass:
    INLINE = "INLINE"
    CORNER = "CORNER"
    PENINSULA = "PENINSULA"
    ISLAND = "ISLAND"


class PremiumZone:
    NONE = "NONE"
    MAIN_AISLE = "MAIN_AISLE"
    ENTRANCE = "ENTRANCE"
    FOOD_COURT = "FOOD_COURT"


class ExhibitorStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PriorityTier:
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"


class AppointmentState:
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXERCISED = "EXERCISED"
    EXPIRED = "EXPIRED"
    FORFEITED = "FORFEITED"


class SpaceContractStatus:
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    SIGNED = "SIGNED"
    CLOSED_OUT = "CLOSED_OUT"
    CANCELLED = "CANCELLED"


class ServiceType:
    LABOR = "LABOR"
    ELECTRICAL = "ELECTRICAL"
    MATERIAL_HANDLING = "MATERIAL_HANDLING"


class RateVariant:
    ADVANCE = "ADVANCE"
    FLOOR = "FLOOR"


class ServiceOrderStatus:
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"


class DealStatus:
    PROPOSED = "PROPOSED"
    SIGNED = "SIGNED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus:
    NOT_STARTED = "NOT_STARTED"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    BREACHED = "BREACHED"


class ObligationStatus:
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    WAIVED = "WAIVED"
    MISSED = "MISSED"


class RegistrationCategory:
    BUYER = "BUYER"
    VIP_BUYER = "VIP_BUYER"
    PRESS = "PRESS"
    STUDENT = "STUDENT"
    EXHIBITOR_STAFF = "EXHIBITOR_STAFF"


class PurchasingAuthority:
    NONE = "NONE"
    INFLUENCER = "INFLUENCER"
    RECOMMENDER = "RECOMMENDER"
    DECISION_MAKER = "DECISION_MAKER"


class SpendBand:
    UNDER_50K = "UNDER_50K"
    K50_250K = "K50_250K"
    K250K_1M = "K250K_1M"
    OVER_1M = "OVER_1M"


class QualificationStatus:
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"


class ViolationType:
    BOOTH_HEIGHT = "BOOTH_HEIGHT"
    NOISE = "NOISE"
    AISLE_ENCROACHMENT = "AISLE_ENCROACHMENT"
    SALES_CONDUCT = "SALES_CONDUCT"


class ViolationStatus:
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"


class CancellationReason:
    """The two literals the system itself writes into `cancellation_reason`."""

    VENUE_CONTRACT_TERMINATED = "VENUE_CONTRACT_TERMINATED"
    SHOW_CANCELLED = "SHOW_CANCELLED"
    SHOW_CLOSED_UNSIGNED = "SHOW_CLOSED_UNSIGNED"


# ─── Entity shapes ───────────────────────────────────────────────────────────
class VenueContract(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    venue_code: str
    hall_code: str
    hall_gross_sqft: int
    min_aisle_ratio_pct: int
    max_booth_height_ft: int
    contract_year_start: int
    contract_year_count: int
    committed_net_sqft_per_year: int
    attrition_allowance_pct: int
    advance_order_discount_pct: int
    labor_rate_cents_per_hour: int
    electrical_rate_cents_per_amp: int
    material_handling_rate_cents_per_cwt: int
    cancellation_fee_schedule: List[dict]
    status: str
    executed_at: Optional[str]
    terminated_effective_date: Optional[str]
    reason: Optional[str]
    show_count: int


class Show(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    venue_contract_id: str
    name: str
    edition_year: int
    move_in_start: str
    event_start: str
    event_end: str
    move_out_end: str
    gross_sqft: int
    aisle_ratio_pct: int
    base_rate_cents_per_sqft: int
    selection_desk_capacity: int
    status: str
    selection_round: int
    floor_posture: str
    cancellation_reason: Optional[str]
    net_sellable_sqft: Optional[int]
    advance_order_deadline: Optional[str]
    sellable_booth_sqft: int
    held_net_sqft: int
    assigned_net_sqft: int
    available_net_sqft: int
    committed_ratio_pct: int
    upheld_violation_count: int
    attrition_shortfall_sqft: int
    attrition_settlement_cents: int


class Booth(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    booth_number: str
    width_ft: int
    depth_ft: int
    area_sqft: int
    location_class: str
    premium_zone: str
    max_height_ft: int
    status: str
    space_contract_id: Optional[str]
    combined_parent_booth_id: Optional[str]


class Exhibitor(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    contact_email: str
    consecutive_years: int
    status: str
    ledger_points: int
    space_points_provisional: int
    space_points_certified: int
    sponsorship_fulfillment_points: int
    penalty_points: int
    provisional_priority_points: int
    certified_priority_points: int
    priority_tier: str


class SelectionAppointment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    exhibitor_id: str
    round_index: int
    window_start: str
    window_end: str
    state: str
    rank: Optional[int]
    certified_points_at_rank: Optional[int]


class SpaceContract(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    exhibitor_id: str
    status: str
    offered_booth_ids: List[str]
    offered_net_sqft: int
    assigned_net_sqft: int
    premium_placement_requested: bool
    requested_sqft: int
    negotiation_round: int
    requested_discount_pct: int
    approved_discount_pct: Optional[int]
    last_offer_by_user_id: Optional[str]
    volume_tier_pct: float
    space_fee_cents: int
    sponsorship_attached_cents: int
    bundle_discount_pct: float
    bundle_discount_cents: int
    invoice_total_cents: int
    min_deposit_cents: int
    deposit_paid_cents: int
    cancellation_fee_cents: int
    fee_applied_to_deposit_cents: int
    refund_cents: int
    balance_due_cents: int
    points_awarded: int
    signed_at: Optional[str]
    rebooked_from_space_contract_id: Optional[str]
    cancellation_reason: Optional[str]


class ServiceOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    space_contract_id: str
    service_type: str
    quantity: int
    billable_quantity: int
    unit_rate_cents: int
    rate_variant: str
    line_total_cents: int
    ordered_at: str
    status: str


class SponsorshipPackage(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    package_code: str
    list_price_cents: int
    price_floor_cents: int
    inventory_total: int
    inventory_committed: int
    inventory_available: int
    exclusivity_category: str
    obligation_codes: List[str]
    priority_point_value: int


class SponsorshipDeal(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    sponsorship_package_id: str
    exhibitor_id: str
    negotiated_price_cents: int
    deal_status: str
    fulfillment_status: str
    obligation_count: int
    resolved_obligation_count: int
    fulfillment_credited: bool
    proposed_by_user_id: str
    signed_by_user_id: Optional[str]
    cancellation_reason: Optional[str]


class FulfillmentObligation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    sponsorship_deal_id: str
    obligation_code: str
    status: str
    due_date: str
    resolved_by_user_id: Optional[str]
    note: Optional[str]


class Registration(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    category: str
    company_name: str
    job_title: str
    purchasing_authority: str
    annual_spend_band: str
    email: str
    qualification_score: int
    qualification_status: str
    screening_override_reason: Optional[str]
    lead_scan_count: int


class RuleViolation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    space_contract_id: str
    violation_type: str
    notes: str
    measured_value: Optional[int]
    status: str
    penalty_points: int
    reported_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    waiver_reason: Optional[str]


class LeadScan(TypedDict, total=False):
    """
    The single entity with no `updated_at` and no `version`:
    "a lead scan is an append-only record with no update endpoint, so a lead
    scan carries only `id` and `created_at`." (§2.4)
    """

    id: str
    created_at: str
    space_contract_id: str
    registration_id: str
    scanned_at: str


# Field sets used by the shared system-field assertions.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
LEAD_SCAN_FIELDS = ("id", "created_at")
LEAD_SCAN_ABSENT_FIELDS = ("updated_at", "version")
