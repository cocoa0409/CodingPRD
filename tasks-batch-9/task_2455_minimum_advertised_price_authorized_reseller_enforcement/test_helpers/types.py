"""Domain types for the Map Authorized Reseller Enforcement API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every one of the twelve entity types carries the four common
properties `id`, `created_at`, `updated_at` and `version` (PRD 2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --------------------------------------------------------------------------- #
# Roles (PRD 2.1)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    BRAND_CHANNEL_MANAGER = "BrandChannelManager"
    BRAND_LEGAL_COUNSEL = "BrandLegalCounsel"
    MONITORING_ANALYST = "MonitoringAnalyst"
    PLATFORM_ADMIN = "PlatformAdmin"
    RESELLER = "Reseller"
    DISTRIBUTOR = "Distributor"


ALL_ROLES = [r.value for r in UserRole]
BRAND_STAFF_ROLES = [
    UserRole.BRAND_CHANNEL_MANAGER.value,
    UserRole.BRAND_LEGAL_COUNSEL.value,
    UserRole.MONITORING_ANALYST.value,
    UserRole.PLATFORM_ADMIN.value,
]


# --------------------------------------------------------------------------- #
# Shared enumerations
# --------------------------------------------------------------------------- #
class Channel(str, Enum):
    MARKETPLACE = "MARKETPLACE"
    RETAILER_SITE = "RETAILER_SITE"
    OWN_WEBSITE = "OWN_WEBSITE"
    PHYSICAL_RETAIL = "PHYSICAL_RETAIL"


ALL_CHANNELS = [c.value for c in Channel]


class QualityObligation(str, Enum):
    AUTHENTICITY_LABELING = "AUTHENTICITY_LABELING"
    WARRANTY_HONORED = "WARRANTY_HONORED"
    PACKAGING_INTACT = "PACKAGING_INTACT"
    AUTHORIZED_SERVICE_ONLY = "AUTHORIZED_SERVICE_ONLY"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_LEGAL_REVIEW = "IN_LEGAL_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ReviewDecision(str, Enum):
    APPROVE_FOR_PUBLICATION = "APPROVE_FOR_PUBLICATION"
    RETURN_FOR_REVISION = "RETURN_FOR_REVISION"


class ProductLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARANCE = "CLEARANCE"
    DISCONTINUED = "DISCONTINUED"


class FloorSource(str, Enum):
    STANDARD = "STANDARD"
    EXCEPTION = "EXCEPTION"


class DistributorStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class AuthorizationStatus(str, Enum):
    APPLIED = "APPLIED"
    PENDING_AGREEMENT = "PENDING_AGREEMENT"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SupplyStatus(str, Enum):
    OPEN = "OPEN"
    HOLD = "HOLD"
    CUT_OFF = "CUT_OFF"


class HoldReason(str, Enum):
    NONE = "NONE"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    QUALITY_OBLIGATION = "QUALITY_OBLIGATION"
    SUSPENSION = "SUSPENSION"
    AGREEMENT_EXPIRED = "AGREEMENT_EXPIRED"
    TERMINATION = "TERMINATION"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    COUNTERSIGNED = "COUNTERSIGNED"
    DECLINED = "DECLINED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class AgreementResponseDecision(str, Enum):
    COUNTERSIGN = "COUNTERSIGN"
    DECLINE = "DECLINE"


class EvaluationStatus(str, Enum):
    CAPTURED = "CAPTURED"
    EVALUATED_COMPLIANT = "EVALUATED_COMPLIANT"
    EVALUATED_BREACH = "EVALUATED_BREACH"


class ViolationStatus(str, Enum):
    DETECTED = "DETECTED"
    NOTICED = "NOTICED"
    DISPUTED = "DISPUTED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"
    CLOSED_MOOT = "CLOSED_MOOT"


class ViolationDisputeDecision(str, Enum):
    REJECT = "REJECT"
    SUSTAIN = "SUSTAIN"


class NoticeRung(str, Enum):
    WARNING = "WARNING"
    SUSPENSION = "SUSPENSION"
    TERMINATION = "TERMINATION"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SATISFIED = "SATISFIED"
    RESCINDED = "RESCINDED"


class DeliveryChannel(str, Enum):
    EMAIL = "EMAIL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    PORTAL = "PORTAL"


class ExceptionType(str, Enum):
    CLEARANCE = "CLEARANCE"
    BUNDLE = "BUNDLE"
    PROMOTIONAL_EVENT = "PROMOTIONAL_EVENT"


class ChannelScope(str, Enum):
    ALL = "ALL"
    MARKETPLACE = "MARKETPLACE"
    RETAILER_SITE = "RETAILER_SITE"
    OWN_WEBSITE = "OWN_WEBSITE"
    PHYSICAL_RETAIL = "PHYSICAL_RETAIL"


class ExceptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class ExceptionDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class DealerInputSource(str, Enum):
    NONE = "NONE"
    RESELLER_PRICING_REQUEST = "RESELLER_PRICING_REQUEST"
    RETAILER_INVENTORY_REPORT = "RETAILER_INVENTORY_REPORT"
    BRAND_MARKETING_PLAN = "BRAND_MARKETING_PLAN"


class SerialUnitStatus(str, Enum):
    SHIPPED_TO_DISTRIBUTOR = "SHIPPED_TO_DISTRIBUTOR"
    SHIPPED_TO_RESELLER = "SHIPPED_TO_RESELLER"
    TRACED_UNAUTHORIZED = "TRACED_UNAUTHORIZED"
    RECALLED = "RECALLED"


class TestPurchaseStatus(str, Enum):
    ORDERED = "ORDERED"
    SERIAL_CAPTURED = "SERIAL_CAPTURED"
    CONFIRMED_UNAUTHORIZED = "CONFIRMED_UNAUTHORIZED"
    CLEARED = "CLEARED"


class TestPurchaseOutcome(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    AUTHORIZED = "AUTHORIZED"


class ChargebackStatus(str, Enum):
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"


class ChargebackDisputeDecision(str, Enum):
    UPHOLD = "UPHOLD"
    REVERSE = "REVERSE"


class ExposureVariant(str, Enum):
    TRACE_ATTRIBUTED = "TRACE_ATTRIBUTED"
    LOT_PRORATED = "LOT_PRORATED"


# --------------------------------------------------------------------------- #
# Entity shapes (all twelve carry id / created_at / updated_at / version)
# --------------------------------------------------------------------------- #
class PricingPolicy(TypedDict):
    id: str
    policy_code: str
    revision_number: int
    status: str
    effective_from: Optional[str]
    shipping_counts_as_advertised: bool
    auto_coupon_counts_as_advertised: bool
    promo_code_counts_as_advertised: bool
    max_discount_attribution_pct: float
    non_negotiation_ack_required: bool
    cure_window_days: int
    suspension_points_threshold: int
    termination_points_threshold: int
    suspension_cooling_off_days: int
    legal_review_notes: Optional[str]
    reviewed_by_user_id: Optional[str]
    published_by_user_id: Optional[str]
    superseded_by_policy_id: Optional[str]
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    msrp_cents: int
    standard_map_floor_cents: int
    lifecycle_status: str
    clearance_discount_pct: float
    serialization_enabled: bool
    governing_policy_id: str
    open_exception_count: int
    created_at: str
    updated_at: str
    version: int


class Reseller(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    primary_channel: str
    authorization_status: str
    supply_status: str
    hold_reason: str
    violation_points_total: float
    review_required: bool
    sourcing_distributor_id: Optional[str]
    suspension_ends_at: Optional[str]
    last_suspension_ended_at: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict):
    id: str
    legal_name: str
    annual_chargeback_cap_cents: int
    standing: str
    diversion_score: float
    chargeback_balance_cents: int
    shipped_units_total: int
    probation_entered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResellerAgreement(TypedDict):
    id: str
    reseller_id: str
    policy_id: str
    status: str
    permitted_channels: List[str]
    quality_obligations: List[str]
    term_ends_at: str
    price_terms_included: bool
    non_negotiation_acknowledged: bool
    sent_at: Optional[str]
    countersigned_at: Optional[str]
    countersigned_by_user_id: Optional[str]
    activated_at: Optional[str]
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceObservation(TypedDict):
    id: str
    product_id: str
    channel: str
    marketplace_name: Optional[str]
    seller_display_name: str
    listing_url: str
    listed_price_cents: int
    shipping_cents: int
    auto_coupon_cents: int
    promo_code_cents: int
    is_bundle: bool
    bundle_total_price_cents: Optional[int]
    bundle_components: Optional[List[Any]]
    matched_reseller_id: Optional[str]
    observed_at: str
    evidence_hash: str
    evidence_captured_by_user_id: str
    allocated_component_price_cents: Optional[int]
    effective_advertised_price_cents: Optional[int]
    effective_map_floor_cents: Optional[int]
    deviation_cents: Optional[int]
    deviation_pct: Optional[float]
    evaluation_status: str
    unauthorized_seller_confirmed: bool
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    observation_id: str
    reseller_id: str
    cited_policy_id: str
    status: str
    provisional_floor_cents: int
    provisional_points: float
    assessed_floor_cents: Optional[int]
    assessed_points: Optional[float]
    cure_deadline_at: Optional[str]
    dispute_rounds: int
    dispute_reason: Optional[str]
    resolution_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementNotice(TypedDict):
    id: str
    violation_id: str
    reseller_id: str
    rung: str
    status: str
    issued_by_user_id: str
    cumulative_points_at_issue: float
    assessed_points: float
    suspension_starts_at: Optional[str]
    suspension_ends_at: Optional[str]
    delivery_channel: str
    contains_pricing_discussion: bool
    acknowledged_at: Optional[str]
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PricingException(TypedDict):
    id: str
    product_id: str
    exception_type: str
    channel_scope: str
    starts_at: str
    ends_at: str
    requested_override_floor_cents: Optional[int]
    override_floor_cents: Optional[int]
    status: str
    retroactive: bool
    dealer_input_source: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    decision_reason: Optional[str]
    voided_violation_count: int
    created_at: str
    updated_at: str
    version: int


class SerialUnit(TypedDict):
    id: str
    serial_number: str
    product_id: str
    lot_code: str
    shipped_distributor_id: str
    downstream_reseller_id: Optional[str]
    status: str
    shipped_downstream_at: Optional[str]
    traced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestPurchase(TypedDict):
    id: str
    observation_id: str
    ordered_at: str
    purchase_price_cents: int
    purchaser_user_id: str
    status: str
    captured_serial_number: Optional[str]
    traced_serial_unit_id: Optional[str]
    outcome_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributorChargeback(TypedDict):
    id: str
    distributor_id: str
    test_purchase_id: str
    diverted_units: int
    tier_rate_cents_per_unit: int
    amount_cents: int
    score_delta_applied: float
    status: str
    dispute_rounds: int
    dispute_reason: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
