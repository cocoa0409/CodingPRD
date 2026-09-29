"""Domain types for the National Account Contract service: entity TypedDicts,
status enums and the role enum. Field names are exactly as the PRD names them."""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    NATIONAL_ACCOUNT_MANAGER = "NationalAccountManager"
    PRICING_ANALYST = "PricingAnalyst"
    OPERATOR_BUYER = "OperatorBuyer"
    MANUFACTURER_REP = "ManufacturerRep"
    REBATE_ACCOUNTANT = "RebateAccountant"
    CONTRACT_AUDITOR = "ContractAuditor"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class OperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ManufacturerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DistributionCenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class StockStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    AMENDING = "AMENDING"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class ContractTierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class DcCoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class DeviationAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    MANUFACTURER_APPROVED = "MANUFACTURER_APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    PRICE_CEILING_BREACHED = "PRICE_CEILING_BREACHED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SubstitutionRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PriceChangeNoticeStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class RebatePeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class OrderLinePricingStatus(str, Enum):
    DRAFT_PRICED = "DRAFT_PRICED"
    INVOICED = "INVOICED"
    REPRICED = "REPRICED"
    CREDITED = "CREDITED"


class OrderLineBillbackStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ACCRUED = "ACCRUED"
    CLAIMED = "CLAIMED"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class BillBackClaimStatus(str, Enum):
    ACCRUED = "ACCRUED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    DISPUTED = "DISPUTED"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class BillBackRemittanceStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class PricingDisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_AUDIT = "UNDER_AUDIT"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    WITHDRAWN = "WITHDRAWN"


# --------------------------------------------------------------------------
# Value enums
# --------------------------------------------------------------------------

class ProductClassCode(str, Enum):
    PROTEIN = "PROTEIN"
    PRODUCE = "PRODUCE"
    FROZEN = "FROZEN"
    DRY_GROCERY = "DRY_GROCERY"
    DISPOSABLES = "DISPOSABLES"
    BEVERAGE = "BEVERAGE"
    SPECIALTY = "SPECIALTY"


class CostBasis(str, Enum):
    LAST_COST = "LAST_COST"
    AVG_COST = "AVG_COST"
    REPLACEMENT_COST = "REPLACEMENT_COST"


class MarkupType(str, Enum):
    PERCENT_OF_COST = "PERCENT_OF_COST"
    DOLLARS_PER_CASE = "DOLLARS_PER_CASE"


class CoverageType(str, Enum):
    IN_MARKET = "IN_MARKET"
    OUT_OF_MARKET = "OUT_OF_MARKET"


class BillBackBasis(str, Enum):
    FIXED_NET_PRICE = "FIXED_NET_PRICE"
    COST_PLUS_PROTECTED = "COST_PLUS_PROTECTED"


class PriceProtectionMode(str, Enum):
    HOLD_CONTRACT_PRICE = "HOLD_CONTRACT_PRICE"
    SUBSTITUTE_OWN_PRICE = "SUBSTITUTE_OWN_PRICE"


class ComplianceBasis(str, Enum):
    DOLLAR_WEIGHTED = "DOLLAR_WEIGHTED"
    CASE_WEIGHTED = "CASE_WEIGHTED"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"


class RebateRemitMethod(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    CREDIT_MEMO = "CREDIT_MEMO"


class DisputeReason(str, Enum):
    TIER_MISAPPLIED = "TIER_MISAPPLIED"
    DEVIATION_NOT_APPLIED = "DEVIATION_NOT_APPLIED"
    COST_BASIS_WRONG = "COST_BASIS_WRONG"
    SERVICE_FEE_WRONG = "SERVICE_FEE_WRONG"


class ManufacturerDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"


class DisputeResolution(str, Enum):
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id, created_at, updated_at, version
# --------------------------------------------------------------------------

class Operator(TypedDict):
    id: str
    legal_name: str
    operator_code: str
    status: str
    rebate_remit_method: str
    created_at: str
    updated_at: str
    version: int


class Manufacturer(TypedDict):
    id: str
    name: str
    manufacturer_code: str
    status: str
    bill_back_terms_days: int
    open_claim_exposure_cents: int
    unapplied_credit_cents: int
    total_remitted_cents: int
    rebate_funding_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class DistributionCenter(TypedDict):
    id: str
    dc_code: str
    name: str
    in_market_state_codes: List[str]
    out_of_market_fee_per_case_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    description: str
    product_class_code: str
    manufacturer_id: str
    pack_size: int
    last_cost_cents: int
    avg_cost_cents: int
    replacement_cost_cents: int
    cost_effective_at: Optional[str]
    stock_status: str
    status: str
    substitution_group_code: Optional[str]
    is_market_indexed: bool
    index_baseline_value: Optional[float]
    index_baseline_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    operator_id: str
    contract_code: str
    rebate_funding_manufacturer_id: str
    effective_from: str
    effective_to: str
    notice_period_days: int
    contracted_purchase_pct_target: float
    compliance_basis: str
    allow_out_of_market: bool
    status: str
    compliance_posture: str
    deviation_breach_count: int
    rebate_payable_cents: int
    rebate_settled_total_cents: int
    amends_contract_id: Optional[str]
    signed_at: Optional[str]
    signed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractTier(TypedDict):
    id: str
    contract_id: str
    product_class_code: str
    cost_basis: str
    markup_type: str
    markup_value: float
    min_case_volume: int
    max_case_volume: Optional[int]
    counts_as_contracted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DcCoverage(TypedDict):
    id: str
    contract_id: str
    distribution_center_id: str
    coverage_type: str
    coverage_from: str
    coverage_to: str
    service_fee_waived: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DeviationAgreement(TypedDict):
    id: str
    contract_id: str
    product_id: str
    manufacturer_id: str
    bill_back_basis: str
    requested_net_price_cents: Optional[int]
    protected_discount_cents: Optional[int]
    deviated_price_cents: int
    max_operator_price_cents: int
    effective_from: str
    effective_to: str
    status: str
    revision_round: int
    price_revision_count: int
    submitted_by_user_id: Optional[str]
    manufacturer_decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionRule(TypedDict):
    id: str
    contract_id: str
    primary_product_id: str
    substitute_product_id: str
    rank: int
    price_protection_mode: str
    max_price_delta_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceChangeNotice(TypedDict):
    id: str
    contract_id: str
    product_id: str
    cost_basis: str
    proposed_cost_cents: Optional[int]
    published_index_value: Optional[float]
    new_cost_cents: int
    delta_pct: float
    notice_required_days: int
    submitted_at: str
    earliest_effective_at: str
    effective_at: str
    status: str
    dispute_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RebatePeriod(TypedDict):
    id: str
    contract_id: str
    period_start: str
    period_end: str
    status: str
    gross_purchases_cents: Optional[int]
    contracted_purchases_cents: Optional[int]
    qualifying_cases: Optional[int]
    contracted_cases: Optional[int]
    compliance_pct: Optional[float]
    rebate_rate_pct: Optional[float]
    operator_rebate_cents: Optional[int]
    manufacturer_funded_cents: Optional[int]
    distributor_funded_cents: Optional[int]
    settled_amount_cents: int
    reopen_count: int
    closed_at: Optional[str]
    settled_at: Optional[str]
    settled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    contract_id: str
    product_id: str
    distribution_center_id: str
    rebate_period_id: str
    quantity_cases: int
    order_date: str
    applied_tier_id: str
    cost_basis_snapshot_cents: int
    list_unit_price_cents: int
    invoiced_unit_price_cents: int
    extended_price_cents: int
    service_fee_cents: int
    invoice_total_cents: int
    is_contracted_item: bool
    deviation_agreement_id: Optional[str]
    substituted_from_product_id: Optional[str]
    substitution_rule_id: Optional[str]
    bill_back_claim_id: Optional[str]
    credited_amount_cents: int
    pricing_status: str
    billback_status: str
    created_at: str
    updated_at: str
    version: int


class BillBackClaim(TypedDict):
    id: str
    deviation_agreement_id: str
    manufacturer_id: str
    claim_period_start: str
    claim_period_end: str
    claimed_cases: int
    claimed_amount_cents: int
    recovered_amount_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    write_off_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillBackRemittance(TypedDict):
    id: str
    manufacturer_id: str
    remitted_amount_cents: int
    remittance_reference: str
    received_at: str
    applied_amount_cents: int
    unapplied_amount_cents: int
    applied_claim_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PricingDispute(TypedDict):
    id: str
    order_line_id: str
    contract_id: str
    claimed_correct_unit_price_cents: int
    dispute_reason: str
    status: str
    audited_correct_unit_price_cents: Optional[int]
    variance_cents_per_case: Optional[int]
    variance_pct: Optional[float]
    credit_amount_cents: Optional[int]
    opened_by_user_id: str
    audited_by_user_id: Optional[str]
    audit_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
