"""Domain types for the Marketplace Fulfillment Inventory & Storage Cost API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them. Resources that the PRD declares append-only records of a computation
(`StorageFeeAssessment`, `VelocityForecast`) carry only `id` and `created_at`.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    SELLER_OPERATOR = "SellerOperator"
    FC_OPERATOR = "FcOperator"
    CLAIMS_ADJUDICATOR = "ClaimsAdjudicator"
    MARKETPLACE_ADMIN = "MarketplaceAdmin"


# --------------------------------------------------------------------------- #
# Status / enum vocabularies
# --------------------------------------------------------------------------- #
class SellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ReceivingStatus(str, Enum):
    OPEN = "OPEN"
    THROTTLED = "THROTTLED"
    SUSPENDED = "SUSPENDED"


class PrepProfile(str, Enum):
    POLYBAG_REQUIRED = "POLYBAG_REQUIRED"
    LABEL_ONLY = "LABEL_ONLY"
    CASE_PACK_STRICT = "CASE_PACK_STRICT"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPPRESSED = "SUPPRESSED"


class InventoryHealth(str, Enum):
    HEALTHY = "HEALTHY"
    EXCESS_AGED = "EXCESS_AGED"
    STRANDED = "STRANDED"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class SuppressionReason(str, Enum):
    NONE = "NONE"
    MISSING_INVENTORY = "MISSING_INVENTORY"
    STRANDED_INVENTORY = "STRANDED_INVENTORY"
    ZERO_FULFILLABLE = "ZERO_FULFILLABLE"


class QuotaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class CapacityTier(str, Enum):
    TIER_ELEVATED = "TIER_ELEVATED"
    TIER_STANDARD = "TIER_STANDARD"
    TIER_RESTRICTED = "TIER_RESTRICTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_TRANSIT = "IN_TRANSIT"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED_COMPLETE = "RECEIVED_COMPLETE"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    WITHIN_LIMIT = "WITHIN_LIMIT"
    OVER_LIMIT = "OVER_LIMIT"


class PrepComplianceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"


class LabelType(str, Enum):
    FNSKU = "FNSKU"
    MANUFACTURER_BARCODE = "MANUFACTURER_BARCODE"
    NONE = "NONE"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_REMOVED = "PARTIALLY_REMOVED"
    DEPLETED = "DEPLETED"


class ReconciliationStatus(str, Enum):
    RECONCILED = "RECONCILED"
    DISCREPANCY_OPEN = "DISCREPANCY_OPEN"
    DISCREPANCY_CLAIMED = "DISCREPANCY_CLAIMED"
    DISCREPANCY_RESOLVED = "DISCREPANCY_RESOLVED"


class AgedBucket(str, Enum):
    UNDER_181 = "UNDER_181"
    D181_270 = "D181_270"
    D271_365 = "D271_365"
    OVER_365 = "OVER_365"


class RemovalMethod(str, Enum):
    DISPOSAL = "DISPOSAL"
    RETURN_TO_SELLER = "RETURN_TO_SELLER"
    LIQUIDATION = "LIQUIDATION"


class UnitPool(str, Enum):
    FULFILLABLE = "FULFILLABLE"
    UNFULFILLABLE = "UNFULFILLABLE"


class RemovalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    LOST_INBOUND = "LOST_INBOUND"
    DAMAGED_WAREHOUSE = "DAMAGED_WAREHOUSE"
    LOST_REMOVAL = "LOST_REMOVAL"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClaimDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ForecastVariant(str, Enum):
    TRAILING_30 = "TRAILING_30"
    SEASONAL_WEIGHTED = "SEASONAL_WEIGHTED"


class DestinationZone(str, Enum):
    ZONE_1 = "ZONE_1"
    ZONE_2 = "ZONE_2"
    ZONE_3 = "ZONE_3"


class FulfillmentChannel(str, Enum):
    MCF = "MCF"
    SELF_FULFILLED = "SELF_FULFILLED"


class McfOrderStatus(str, Enum):
    MCF_SHIPPED = "MCF_SHIPPED"
    SELF_SHIPPED = "SELF_SHIPPED"


# --------------------------------------------------------------------------- #
# Entities carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------- #
class SellerAccount(TypedDict):
    id: str
    legal_name: str
    storage_cubic_feet_entitlement: float
    unit_cost_cap_cents: int
    seller_status: str
    restock_reserved_units: int
    open_discrepancy_units: int
    suppressed_listing_count: int
    storage_fee_accrued_cents: int
    reimbursement_credit_cents: int
    mcf_fee_accrued_cents: int
    storage_utilization_ratio: float
    created_at: str
    updated_at: str
    version: int


class FulfillmentCenter(TypedDict):
    id: str
    fc_code: str
    region_code: str
    prep_profile: str
    case_pack_min_units: int
    receiving_capacity_units_per_window: int
    monthly_storage_rate_cents_per_cubic_foot: int
    ltsf_rate_cents_per_cubic_foot: int
    receiving_status: str
    committed_receiving_units: int
    created_at: str
    updated_at: str
    version: int


class SkuListing(TypedDict):
    id: str
    seller_account_id: str
    sku: str
    unit_cubic_feet: float
    unit_cost_cents: int
    listing_status: str
    inventory_health: str
    suppression_reason: str
    lot_ever_created: bool
    fulfillable_units: int
    unfulfillable_units: int
    missing_units: int
    aged_over_365_units: int
    recommended_replenishment_units: int
    created_at: str
    updated_at: str
    version: int


class RestockQuota(TypedDict):
    id: str
    seller_account_id: str
    period_start: str
    period_end: str
    base_capacity_units: int
    sell_through_rate: float
    excess_units_ratio: float
    stranded_ratio: float
    in_stock_rate: float
    status: str
    iprs_score: int
    base_capacity_tier: str
    capacity_tier: str
    capacity_tier_downgrade_steps: int
    restock_limit_units: int
    utilized_units: int
    created_at: str
    updated_at: str
    version: int


class InboundShipmentPlan(TypedDict):
    id: str
    seller_account_id: str
    destination_fc_id: str
    appointment_window_start: str
    appointment_window_end: str
    status: str
    declared_units: int
    provisional_allocated_units: int
    final_allocated_units: int
    allocated_units: int
    received_units: int
    missing_units: int
    allocation_status: str
    prep_compliance_status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentLineItem(TypedDict):
    id: str
    shipment_plan_id: str
    sku_listing_id: str
    units: int
    case_pack_units: int
    polybagged: bool
    label_type: str
    provisional_allocated_units: int
    final_allocated_units: int
    received_units: int
    shortfall_units: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    sku_listing_id: str
    fulfillment_center_id: str
    lot_status: str
    reconciliation_status: str
    units_received_total: int
    fulfillable_units: int
    unfulfillable_units: int
    units_reserved_for_removal: int
    units_removed: int
    units_shipped_mcf: int
    missing_units: int
    first_received_at: str
    age_days: int
    aged_bucket: str
    ltsf_exposed: bool
    storage_fee_accrued_cents: int
    discrepancy_opened_at: Optional[str]
    unfulfillable_recorded_at: Optional[str]
    last_removal_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemovalOrder(TypedDict):
    id: str
    inventory_lot_id: str
    removal_method: str
    unit_pool: str
    requested_units: int
    removal_window_start: str
    removal_window_end: str
    status: str
    removal_fee_cents: int
    liquidation_recovery_cents: int
    net_settlement_cents: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict):
    id: str
    inventory_lot_id: str
    claim_type: str
    claimed_units: int
    evidence_document_count: int
    evidence_reference: str
    status: str
    filing_deadline_at: str
    resubmission_count: int
    eligible_units: int
    approved_units: int
    reimbursement_amount_cents: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MultiChannelOrder(TypedDict):
    id: str
    sku_listing_id: str
    units: int
    billable_weight_lb: float
    destination_zone: str
    fulfillment_channel: str
    self_fulfilled_cost_cents: int
    mcf_fee_cents: int
    is_peak_period: bool
    fee_advantage_cents: int
    recommended_channel: str
    order_status: str
    consumed_lot_allocations: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Append-only computation records — id + created_at only
# --------------------------------------------------------------------------- #
class StorageFeeAssessment(TypedDict):
    id: str
    inventory_lot_id: str
    billing_run_sequence: int
    assessed_at: str
    age_days_at_assessment: int
    aged_bucket: str
    billable_cubic_feet: float
    monthly_storage_fee_cents: int
    ltsf_surcharge_cents: int
    total_fee_cents: int
    created_at: str


class VelocityForecast(TypedDict):
    id: str
    sku_listing_id: str
    forecast_variant: str
    trailing_30_units_sold: int
    prior_year_same_period_units_sold: int
    seasonal_index: float
    coverage_target_days: int
    lead_time_days: int
    daily_velocity: float
    target_units: int
    in_flight_units: int
    quota_headroom_units: int
    recommended_replenishment_units: int
    stranded_risk_flag: bool
    created_at: str


class StorageBillingRunSummary(TypedDict):
    billing_run_sequence: int
    assessment_count: int
    total_assessed_cents: int
    downgraded_quota_count: int
    expired_quota_count: int
    closed_plan_count: int
