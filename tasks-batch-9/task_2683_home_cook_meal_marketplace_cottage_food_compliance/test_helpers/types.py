"""Entity shapes, status vocabularies and the role enum for the Home-Cook
Meal Marketplace & Cottage-Food Compliance API.

All eleven resource types carry `id`, `created_at`, `updated_at` and an integer
`version` (PRD 2.4), so every TypedDict below inherits `CommonFields`.
TypedDicts are declared `total=False`: they document the shape the PRD promises
without forcing tests to assert on fields the PRD never names in a response.
"""

from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
class Role:
    ANONYMOUS = "Anonymous"
    COOK = "Cook"
    DINER = "Diner"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    SAFETY_OFFICER = "SafetyOfficer"
    FINANCE_OPERATOR = "FinanceOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLES = (
    Role.ANONYMOUS,
    Role.COOK,
    Role.DINER,
    Role.COMPLIANCE_REVIEWER,
    Role.SAFETY_OFFICER,
    Role.FINANCE_OPERATOR,
    Role.PLATFORM_ADMIN,
)

# Roles for which X-User-ID is mandatory (PRD 2.1 / ladder step 3)
USER_ID_MANDATORY_ROLES = (
    Role.COOK,
    Role.COMPLIANCE_REVIEWER,
    Role.SAFETY_OFFICER,
    Role.FINANCE_OPERATOR,
)


# --------------------------------------------------------------------------
# Status vocabularies (PRD 2.7)
# --------------------------------------------------------------------------
COOK_ONBOARDING_STATUSES = ("DRAFT", "DOCS_SUBMITTED", "VERIFIED", "ACTIVE", "REJECTED")
COOK_COMPLIANCE_STANDINGS = ("CLEAR", "WARNED", "SUSPENDED", "REVOKED")
DOCUMENT_REVIEW_STATUSES = (
    "SUBMITTED", "VERIFIED", "REJECTED", "PASSED", "FAILED", "WAIVED", "SUPERSEDED",
)
MENU_ITEM_REVIEW_STATUSES = (
    "DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "REJECTED", "DELISTED",
)
WINDOW_STATUSES = ("OPEN", "CUTOFF_PASSED", "IN_PRODUCTION", "CLOSED", "CANCELLED")
HUB_STATUSES = ("OPEN", "CLOSED")
ORDER_FULFILLMENT_STATUSES = (
    "PLACED", "ROUTED", "IN_PRODUCTION", "HANDED_OFF", "DELIVERED", "CANCELLED",
)
ORDER_PAYMENT_STATUSES = (
    "AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED", "VOIDED",
)
INCIDENT_STATUSES = ("INTAKE", "TRIAGED", "SUBSTANTIATED", "UNSUBSTANTIATED", "DISMISSED")
STATEMENT_STATUSES = ("DRAFT", "FINALIZED", "PAID", "REVERSED", "SUPERSEDED")
REFUND_STATUSES = ("PENDING", "SETTLED")

CAP_STATUSES = ("UNDER_CAP", "CAP_WARNING", "CAP_REACHED")
LABEL_COMPLIANCE_STATUSES = ("COMPLIANT", "MISSING_FIELDS")

# Terminal states, quoted from PRD 2.7
TERMINAL_COOK_ONBOARDING = ("REJECTED",)
TERMINAL_COOK_STANDING = ("REVOKED",)
TERMINAL_DOCUMENT = ("REJECTED", "FAILED", "SUPERSEDED")
TERMINAL_MENU_ITEM = ("REJECTED",)
TERMINAL_WINDOW = ("CLOSED", "CANCELLED")
TERMINAL_ORDER_FULFILLMENT = ("DELIVERED", "CANCELLED")
TERMINAL_ORDER_PAYMENT = ("VOIDED", "REFUNDED")
TERMINAL_INCIDENT = ("SUBSTANTIATED", "UNSUBSTANTIATED", "DISMISSED")
TERMINAL_STATEMENT = ("REVERSED", "SUPERSEDED")
TERMINAL_REFUND = ("SETTLED",)


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class CommonFields(TypedDict, total=False):
    """PRD 2.4: every persisted resource carries these four fields."""

    id: str
    created_at: str
    updated_at: str
    version: int


class StatePolicy(CommonFields, total=False):
    state_code: str
    cottage_food_annual_cap_cents: int
    allowed_kitchen_types: List[str]
    tcs_requires_commercial_kitchen: bool
    max_shelf_life_days_non_refrigerated: int
    label_required_fields: List[str]
    cert_validity_max_days: int


class Cook(CommonFields, total=False):
    legal_name: str
    email: str
    state_code: str
    claimed_kitchen_type: str
    verified_kitchen_type: Optional[str]
    weekly_capacity_meals: int
    onboarding_status: str
    compliance_standing: str
    standing_reason: Optional[str]
    safety_score: int
    cap_status: str
    ytd_gross_sales_cents: int
    ytd_cottage_revenue_cents: int
    pending_payout_cents: int
    lifetime_paid_cents: int


class OnboardingDocument(CommonFields, total=False):
    cook_id: str
    doc_type: str
    review_status: str
    certificate_number: Optional[str]
    issuing_authority: Optional[str]
    issued_on: Optional[str]
    expires_on: Optional[str]
    kitchen_type_claimed: Optional[str]
    inspection_date: Optional[str]
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]
    note: Optional[str]
    superseded_by_document_id: Optional[str]


class MenuItem(CommonFields, total=False):
    cook_id: str
    name: str
    food_category: str
    allergens: List[str]
    allergen_free_attested: bool
    shelf_life_days: int
    requires_refrigeration: bool
    handoff_mode: str
    unit_price_cents: int
    label_fields: List[str]
    label_compliance_status: str
    review_status: str
    revision_round: int
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    allergen_review_notes: Optional[str]
    revision_note: Optional[str]
    delist_reason: Optional[str]


class ProductionWindow(CommonFields, total=False):
    cook_id: str
    week_start_date: str
    order_cutoff_at: str
    handoff_start_at: str
    handoff_end_at: str
    capacity_meals: int
    committed_meals: int
    spoilage_reserve_meals: int
    effective_capacity_meals: int
    status: str
    cancelled_reason: Optional[str]
    closed_at: Optional[str]


class DeliveryZone(CommonFields, total=False):
    state_policy_id: str
    zone_code: str
    state_code: str
    service_mode: str
    postal_codes: List[str]
    max_cold_chain_minutes: int


class PickupHub(CommonFields, total=False):
    delivery_zone_id: str
    name: str
    address: str
    slot_capacity_orders: int
    hub_window_start_at: str
    hub_window_end_at: str
    assigned_order_count: int
    status: str


class Order(CommonFields, total=False):
    cook_id: str
    menu_item_id: str
    production_window_id: str
    delivery_zone_id: str
    pickup_hub_id: Optional[str]
    diner_user_id: str
    diner_contact_email: str
    quantity: int
    unit_price_cents_snapshot: int
    subtotal_cents: int
    diner_service_fee_cents: int
    cold_chain_surcharge_cents: int
    total_charge_cents: int
    commission_rate: float
    platform_commission_cents: int
    cook_earnings_cents: int
    routing_mode: Optional[str]
    fulfillment_status: str
    payment_status: str
    captured_at: Optional[str]
    effective_year: Optional[int]
    cancelled_reason: Optional[str]
    refunded_cents: int
    cook_chargeback_cents: int
    commission_reversed_cents: int
    platform_absorbed_cents: int


class SafetyIncident(CommonFields, total=False):
    cook_id: str
    subject_type: str
    order_id: Optional[str]
    menu_item_id: Optional[str]
    category: str
    severity: str
    severity_points: int
    description: str
    occurred_at: str
    status: str
    reported_by_user_id: str
    triaged_by_user_id: Optional[str]
    triaged_at: Optional[str]
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]
    resolution_note: Optional[str]


class PayoutStatement(CommonFields, total=False):
    cook_id: str
    production_window_id: str
    basis: str
    status: str
    tier_rate: float
    included_order_count: int
    gross_sales_cents: int
    commission_cents: int
    refund_chargeback_cents: int
    safety_hold_cents: int
    net_payout_cents: int
    finalized_at: Optional[str]
    paid_at: Optional[str]
    superseded_at: Optional[str]
    note: Optional[str]


class RefundEvent(CommonFields, total=False):
    order_id: str
    safety_incident_id: Optional[str]
    reason: str
    fault_party: str
    refund_amount_cents: int
    cook_chargeback_cents: int
    commission_reversed_cents: int
    platform_absorbed_cents: int
    status: str
    settled_at: Optional[str]
    created_by_user_id: str


class ComplianceSummary(TypedDict, total=False):
    """Computed projection returned by GET /cooks/{id}/compliance-summary (PRD 3.7)."""

    cook_id: str
    safety_score: int
    provisional_safety_score: int
    compliance_standing: str
    cap_status: str
    ytd_cottage_revenue_cents: int
    cap_remaining_cents: int
    open_incident_count: int
    substantiated_incident_count: int
    approved_menu_item_count: int


Json = Dict[str, Any]
