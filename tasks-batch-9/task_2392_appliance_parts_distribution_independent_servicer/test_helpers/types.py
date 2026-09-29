"""Domain types for the appliance-parts distribution API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SERVICER = "Servicer"
    BRANCH_COUNTER_REP = "BranchCounterRep"
    CREDIT_MANAGER = "CreditManager"
    WARRANTY_ADMIN = "WarrantyAdmin"
    PRICING_ADMIN = "PricingAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------
class BranchStatus(str, Enum):
    OPEN = "OPEN"
    COUNT_FREEZE = "COUNT_FREEZE"
    CLOSED = "CLOSED"


class PartCategory(str, Enum):
    ELECTRICAL = "ELECTRICAL"
    MECHANICAL = "MECHANICAL"
    COSMETIC = "COSMETIC"
    SEALED_SYSTEM = "SEALED_SYSTEM"


class PartLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    OBSOLETE = "OBSOLETE"
    NLA = "NLA"


class CertLevel(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"
    SEALED_SYSTEM = "SEALED_SYSTEM"


class XrefSource(str, Enum):
    OEM_PUBLICATION = "OEM_PUBLICATION"
    MANUAL_ENTRY = "MANUAL_ENTRY"


class CreditTerms(str, Enum):
    PREPAY = "PREPAY"
    NET_15 = "NET_15"
    NET_30 = "NET_30"
    NET_45 = "NET_45"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    SUSPENDED = "SUSPENDED"


class CertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PriceFileStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"


class FulfillmentMode(str, Enum):
    WILL_CALL = "WILL_CALL"
    OVERNIGHT_DROP_SHIP = "OVERNIGHT_DROP_SHIP"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    HELD = "HELD"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class HoldReason(str, Enum):
    SUBSTITUTE_PENDING = "SUBSTITUTE_PENDING"
    CREDIT_HOLD = "CREDIT_HOLD"
    BACKORDER = "BACKORDER"


class SettlementStatus(str, Enum):
    PENDING_CREDIT = "PENDING_CREDIT"
    CREDIT_APPROVED = "CREDIT_APPROVED"
    CREDIT_DECLINED = "CREDIT_DECLINED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class PricingBasis(str, Enum):
    ORDER_DATE = "ORDER_DATE"
    SHIP_DATE = "SHIP_DATE"


class LineStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESOLVED = "RESOLVED"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    SUBSTITUTE_PENDING = "SUBSTITUTE_PENDING"
    SHIPPED = "SHIPPED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class SubstituteRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SubstituteRequestSource(str, Enum):
    CHAIN_TERMINAL_OBSOLETE = "CHAIN_TERMINAL_OBSOLETE"
    PRICE_FILE_OBSOLESCENCE = "PRICE_FILE_OBSOLESCENCE"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    OEM_INFO_REQUESTED = "OEM_INFO_REQUESTED"
    OEM_APPROVED = "OEM_APPROVED"
    OEM_DENIED = "OEM_DENIED"
    CREDITED = "CREDITED"
    VOID = "VOID"


class OemOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    INFO_REQUESTED = "INFO_REQUESTED"


class ReturnReasonCode(str, Enum):
    WRONG_PART = "WRONG_PART"
    DEFECTIVE_ON_ARRIVAL = "DEFECTIVE_ON_ARRIVAL"
    NO_LONGER_NEEDED = "NO_LONGER_NEEDED"
    CORE_RETURN = "CORE_RETURN"


class RaStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    CREDITED = "CREDITED"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    REJECT = "REJECT"


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------
class Branch(TypedDict):
    id: str
    code: str
    name: str
    region_code: str
    will_call_enabled: bool
    cutoff_hour_utc: int
    overnight_surcharge_cents: int
    branch_status: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    part_number: str
    oem_code: str
    description: str
    category: str
    lifecycle_status: str
    superseded_by_part_id: Optional[str]
    list_price_cents: int
    core_required: bool
    core_deposit_cents: int
    weight_grams: int
    cert_level_required: str
    is_returnable: bool
    created_at: str
    updated_at: str
    version: int


class ModelPartXref(TypedDict):
    """Immutable append-only configuration row.

    The PRD states these rows carry no `updated_at` and no `version`, so this
    TypedDict deliberately omits both.
    """
    id: str
    model_number: str
    part_id: str
    position_code: str
    xref_source: str
    created_at: str


class PricingTier(TypedDict):
    id: str
    tier_code: str
    name: str
    discount_pct_electrical: float
    discount_pct_mechanical: float
    discount_pct_cosmetic: float
    discount_pct_sealed_system: float
    min_annual_volume_cents: int
    created_at: str
    updated_at: str
    version: int


class ServicerAccount(TypedDict):
    id: str
    business_name: str
    oem_authorizations: List[str]
    credit_terms: str
    credit_limit_cents: int
    core_liability_limit_cents: int
    pricing_tier_id: str
    account_status: str
    credit_used_cents: int
    core_liability_cents: int
    delinquency_score: int
    rolling_12m_volume_cents: int
    created_at: str
    updated_at: str
    version: int


class TechnicianCertification(TypedDict):
    id: str
    servicer_account_id: str
    technician_name: str
    oem_code: str
    cert_level: str
    training_completed_at: str
    expires_at: str
    cert_status: str
    is_effective: bool
    created_at: str
    updated_at: str
    version: int


class InventoryRecord(TypedDict):
    id: str
    branch_id: str
    part_id: str
    on_hand_units: int
    reserved_units: int
    available_units: int
    reorder_point: int
    last_counted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceFile(TypedDict):
    id: str
    file_version: int
    effective_at: str
    effective_until: Optional[str]
    price_file_status: str
    line_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceFileLine(TypedDict):
    id: str
    price_file_id: str
    part_id: str
    new_list_price_cents: int
    new_core_deposit_cents: Optional[int]
    new_lifecycle_status: Optional[str]
    previous_list_price_cents: Optional[int]
    previous_core_deposit_cents: Optional[int]
    previous_lifecycle_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartOrder(TypedDict):
    id: str
    servicer_account_id: str
    fulfillment_mode: str
    pickup_branch_id: Optional[str]
    ship_to_zip: Optional[str]
    purchase_order_ref: Optional[str]
    fulfillment_status: str
    hold_reason: Optional[str]
    settlement_status: str
    pricing_basis: str
    credit_decided_by_user_id: Optional[str]
    subtotal_cents: int
    core_deposit_total_cents: int
    freight_cents: int
    total_cents: int
    invoiced_total_cents: Optional[int]
    price_variance_cents: int
    fulfilled_at: Optional[str]
    tracking_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    part_order_id: str
    requested_part_id: str
    resolved_part_id: str
    quantity: int
    supersession_hops: int
    unit_price_cents: int
    extended_price_cents: int
    invoiced_unit_price_cents: Optional[int]
    core_deposit_cents: int
    returned_units: int
    line_status: str
    allocation_branch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstituteRequest(TypedDict):
    id: str
    order_line_id: str
    obsolete_part_id: str
    proposed_substitute_part_id: Optional[str]
    request_status: str
    price_variance_pct: Optional[float]
    source: str
    created_by_price_file_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    servicer_account_id: str
    order_line_id: str
    oem_code: str
    defect_code: str
    appliance_model_number: str
    claim_status: str
    resubmission_count: int
    submitted_at: Optional[str]
    oem_reference: Optional[str]
    claim_amount_cents: Optional[int]
    credit_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict):
    id: str
    servicer_account_id: str
    order_line_id: str
    quantity: int
    reason_code: str
    return_branch_id: str
    ra_status: str
    days_since_fulfilled_at_request: int
    gross_return_cents: int
    restocking_fee_pct: Optional[float]
    restocking_fee_cents: int
    credit_amount_cents: int
    core_deposit_refund_cents: int
    fee_waived: bool
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditSummary(TypedDict):
    credit_limit_cents: int
    credit_used_cents: int
    available_credit_cents: int
    core_liability_cents: int
    core_liability_limit_cents: int
    delinquency_score_rolling: int
    delinquency_score_lifetime: int
    rolling_12m_volume_cents: int
    open_order_count: int
    effective_cert_count: int
