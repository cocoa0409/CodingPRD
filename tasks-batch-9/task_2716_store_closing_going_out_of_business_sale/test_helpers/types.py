"""Domain types for the store-closing liquidation service.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    LIQUIDATION_CONSULTANT = "LiquidationConsultant"
    RETAILER_CONTROLLER = "RetailerController"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    STORE_MANAGER = "StoreManager"
    SYSTEM_OPERATOR = "SystemOperator"


# --------------------------------------------------------------------------
# Status vocabularies
# --------------------------------------------------------------------------

class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_RETAILER_APPROVAL = "PENDING_RETAILER_APPROVAL"
    ACTIVE = "ACTIVE"
    WIND_DOWN = "WIND_DOWN"
    CLOSED = "CLOSED"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class EconomicsModel(str, Enum):
    GUARANTEED = "GUARANTEED"
    FEE_BASED = "FEE_BASED"
    HYBRID = "HYBRID"


class ExpenseResponsibility(str, Enum):
    LIQUIDATOR = "LIQUIDATOR"
    RETAILER = "RETAILER"
    SHARED = "SHARED"


class StoreStatus(str, Enum):
    PLANNED = "PLANNED"
    LICENSE_PENDING = "LICENSE_PENDING"
    SELLING = "SELLING"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    SURRENDERED = "SURRENDERED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    LICENSE_REVOKED = "LICENSE_REVOKED"
    LICENSE_EXPIRED = "LICENSE_EXPIRED"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"


class LicenseStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LotStatus(str, Enum):
    ON_FLOOR = "ON_FLOOR"
    SOLD_OUT = "SOLD_OUT"
    RETURNED_TO_SUPPLIER = "RETURNED_TO_SUPPLIER"


class LotSource(str, Enum):
    ORIGINAL = "ORIGINAL"
    AUGMENTATION = "AUGMENTATION"


class MerchandiseCategory(str, Enum):
    APPAREL = "APPAREL"
    FOOTWEAR = "FOOTWEAR"
    HOME = "HOME"
    ELECTRONICS = "ELECTRONICS"
    JEWELRY = "JEWELRY"
    SEASONAL = "SEASONAL"


class ConsignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DISCLOSURE_FILED = "DISCLOSURE_FILED"
    RECEIVED = "RECEIVED"
    RETURNED = "RETURNED"
    SOLD_OUT = "SOLD_OUT"


class StageStatus(str, Enum):
    ARMED = "ARMED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class StageClosedReason(str, Enum):
    ON_SCHEDULE = "ON_SCHEDULE"
    ESCALATED = "ESCALATED"
    SUPERSEDED = "SUPERSEDED"
    STORE_CLOSED = "STORE_CLOSED"
    LICENSE_LOST = "LICENSE_LOST"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    TERMINATED_INVOLUNTARY = "TERMINATED_INVOLUNTARY"
    TERMINATED_VOLUNTARY = "TERMINATED_VOLUNTARY"


class BonusStatus(str, Enum):
    PENDING = "PENDING"
    EARNED = "EARNED"
    PRORATED_EARNED = "PRORATED_EARNED"
    FORFEITED = "FORFEITED"
    PAID = "PAID"


class DayStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    POSTED = "POSTED"
    REJECTED = "REJECTED"


class ExpenseCategory(str, Enum):
    OCCUPANCY = "OCCUPANCY"
    ADVERTISING = "ADVERTISING"
    PAYROLL = "PAYROLL"
    SECURITY = "SECURITY"
    SUPPLIES = "SUPPLIES"
    PROFESSIONAL_FEES = "PROFESSIONAL_FEES"


class ExpenseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"
    SETTLED = "SETTLED"


class DispositionStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFER_SENT = "OFFER_SENT"
    LANDLORD_COUNTERED = "LANDLORD_COUNTERED"
    AGREED = "AGREED"
    REJECTED_FINAL = "REJECTED_FINAL"
    SURRENDERED = "SURRENDERED"


class SettlementBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class AdvertisingClaimCode(str, Enum):
    LOWEST_PRICES_EVER = "LOWEST_PRICES_EVER"
    EVERYTHING_MUST_GO = "EVERYTHING_MUST_GO"
    LOST_OUR_LEASE = "LOST_OUR_LEASE"
    BELOW_COST = "BELOW_COST"
    FINAL_DAYS = "FINAL_DAYS"
    AUGMENTED_MERCHANDISE_DISCLOSURE = "AUGMENTED_MERCHANDISE_DISCLOSURE"


# --------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id, created_at, updated_at, version
# --------------------------------------------------------------------------

class Jurisdiction(TypedDict):
    id: str
    code: str
    name: str
    gob_license_required: bool
    max_sale_days: int
    license_cooling_off_days: int
    max_augmentation_ratio: float
    augmentation_disclosure_required: bool
    augmentation_prohibited: bool
    prohibited_claim_codes: List[str]
    advertising_disclosure_required: bool
    surrender_notice_days: int
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    retailer_name: str
    liquidator_name: str
    economics_model: str
    guaranty_pct: float
    hybrid_retailer_excess_pct: float
    expense_responsibility: str
    shared_expense_liquidator_pct: float
    sale_start_date: str
    target_end_date: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    engagement_status: str
    compliance_strike_count: int
    compliance_posture: str
    original_cost_value_cents: int
    guaranty_amount_cents: int
    projected_gross_recovery_cents: int
    projected_shortfall_cents: int
    original_net_sales_cents: int
    augmentation_net_sales_cents: int
    gross_recovery_cents: int
    expense_total_cents: int
    expense_liquidator_share_cents: int
    expense_retailer_share_cents: int
    retention_accrual_cents: int
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    engagement_id: str
    jurisdiction_id: str
    store_code: str
    address_line: str
    store_status: str
    suspension_reason: str
    selling_start_date: Optional[str]
    selling_end_date: Optional[str]
    original_cost_value_cents: int
    augmentation_cost_value_cents: int
    units_initial_total: int
    units_sold_total: int
    realized_sell_through_pct: float
    planned_avg_discount_pct: float
    projected_gross_recovery_cents: int
    projected_recovery_ratio: float
    realized_gross_recovery_cents: int
    realized_recovery_ratio: float
    augmentation_units_accounted: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    store_id: str
    consignment_id: Optional[str]
    category: str
    source: str
    units_initial: int
    units_on_hand: int
    units_sold: int
    units_returned: int
    unit_cost_cents: int
    unit_retail_cents: int
    cost_value_cents: int
    retail_value_cents: int
    lot_status: str
    projected_recovery_cents: int
    created_at: str
    updated_at: str
    version: int


class AugmentationConsignment(TypedDict):
    id: str
    store_id: str
    supplier_name: str
    category: str
    units_supplied: int
    unit_cost_cents: int
    unit_retail_cents: int
    cost_value_cents: int
    delivery_window_start_date: str
    delivery_window_end_date: str
    consignment_status: str
    disclosure_reference: Optional[str]
    disclosure_filed_at: Optional[str]
    units_returned: int
    created_at: str
    updated_at: str
    version: int


class MarkdownStage(TypedDict):
    id: str
    store_id: str
    stage_index: int
    discount_pct: float
    sell_through_target_pct: float
    window_start_date: str
    window_end_date: str
    stage_status: str
    closed_reason: Optional[str]
    checkpoint_sell_through_pct: Optional[float]
    escalation_applied_pct: float
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GobLicense(TypedDict):
    id: str
    store_id: str
    license_number: str
    period_start_date: str
    period_end_date: str
    requested_days: int
    advertising_claim_codes: List[str]
    license_status: str
    applied_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    store_id: str
    employee_code: str
    employment_status: str
    bonus_status: str
    retention_bonus_cents: int
    retention_start_date: str
    retention_target_date: str
    attendance_rate: float
    served_days: int
    earned_bonus_cents: int
    notice_given_date: Optional[str]
    termination_date: Optional[str]
    bonus_paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesDay(TypedDict):
    id: str
    store_id: str
    business_date: str
    original_net_sales_cents: int
    augmentation_net_sales_cents: int
    original_units_sold: int
    augmentation_units_sold: int
    net_sales_cents: int
    day_status: str
    posted_at: Optional[str]
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    allocation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpenseItem(TypedDict):
    id: str
    engagement_id: str
    store_id: Optional[str]
    expense_category: str
    amount_cents: int
    incurred_date: str
    expense_status: str
    liquidator_share_cents: int
    retailer_share_cents: int
    auto_generated: bool
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeaseDisposition(TypedDict):
    id: str
    store_id: str
    landlord_name: str
    surrender_deadline_date: str
    daily_holdover_rate_cents: int
    rent_arrears_cents: int
    cam_arrears_cents: int
    restoration_cost_cents: int
    fixture_reserve_price_cents: int
    surrender_credit_cents: int
    disposition_status: str
    negotiation_round: int
    offered_surrender_payment_cents: Optional[int]
    landlord_counter_amount_cents: Optional[int]
    agreed_surrender_payment_cents: Optional[int]
    landlord_agreed_date: Optional[str]
    fixture_sale_price_cents: Optional[int]
    holdover_days: Optional[int]
    holdover_penalty_cents: Optional[int]
    allocated_rent_cents: Optional[int]
    allocated_cam_cents: Optional[int]
    allocated_restoration_cents: Optional[int]
    allocated_holdover_cents: Optional[int]
    unpaid_landlord_balance_cents: Optional[int]
    residual_to_retailer_cents: Optional[int]
    surrendered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    engagement_id: str
    settlement_basis: str
    settlement_status: str
    gross_recovery_cents: Optional[int]
    original_net_sales_cents: Optional[int]
    recovery_ratio: Optional[float]
    fee_rate: Optional[float]
    liquidator_fee_cents: Optional[int]
    guaranty_amount_cents: Optional[int]
    expense_total_cents: Optional[int]
    liquidator_expense_cents: Optional[int]
    retailer_expense_cents: Optional[int]
    retailer_proceeds_cents: Optional[int]
    liquidator_proceeds_cents: Optional[int]
    retention_accrual_cents: Optional[int]
    dispute_reason: Optional[str]
    dispute_round: int
    computed_at: Optional[str]
    proposed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
