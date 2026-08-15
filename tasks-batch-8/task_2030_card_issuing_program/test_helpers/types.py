"""Domain types: entity TypedDicts, status enums, role enum.

Field sets and state names are derived from the PRD's entity narratives.
Entities that are append-only (AuthorizationEvent, Settlement) carry ONLY
id + created_at — no updated_at, no version.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROGRAM_MANAGER = "ProgramManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    OPERATIONS_ANALYST = "OperationsAnalyst"
    FINANCE_CONTROLLER = "FinanceController"
    CARDHOLDER_OPS = "CardholderOps"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class ProgramPosture(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    SUNSETTING = "SUNSETTING"
    TERMINATED = "TERMINATED"


class TerminationReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    NETWORK_DIRECTIVE = "NETWORK_DIRECTIVE"
    PORTFOLIO_CONVERSION = "PORTFOLIO_CONVERSION"


class ProductClass(str, Enum):
    CONSUMER_PREPAID = "CONSUMER_PREPAID"
    CORPORATE_FLEET = "CORPORATE_FLEET"
    DEBIT_CONSUMER = "DEBIT_CONSUMER"
    COMMERCIAL_CREDIT = "COMMERCIAL_CREDIT"


class Network(str, Enum):
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    STAR = "STAR"
    PULSE = "PULSE"


class BinRangeStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    FROZEN = "FROZEN"
    RETIRED = "RETIRED"


class ProductionBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    SUBMITTED = "SUBMITTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class AccountLifecycle(str, Enum):
    ONBOARDING = "ONBOARDING"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    CONVERTED_OUT = "CONVERTED_OUT"


class AccountClass(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"
    FLEET_POOL = "FLEET_POOL"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    RESTRICTED = "RESTRICTED"


class CardLifecycle(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    COMPROMISED = "COMPROMISED"


class PinStatus(str, Enum):
    UNSET = "UNSET"
    SET = "SET"
    BLOCKED = "BLOCKED"
    RESET_PENDING = "RESET_PENDING"


class FormFactor(str, Enum):
    PHYSICAL = "PHYSICAL"
    VIRTUAL = "VIRTUAL"


class ActivationTokenStatus(str, Enum):
    PENDING = "PENDING"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class RuleKind(str, Enum):
    VELOCITY = "VELOCITY"
    MCC_ALLOW = "MCC_ALLOW"
    MCC_BLOCK = "MCC_BLOCK"
    GEO_BLOCK = "GEO_BLOCK"


class SubjectKind(str, Enum):
    PROGRAM = "PROGRAM"
    ACCOUNT = "ACCOUNT"


class RuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MandateStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    EFFECTIVE = "EFFECTIVE"
    RETIRED = "RETIRED"


class MandateSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    REQUIRED = "REQUIRED"
    EMERGENCY = "EMERGENCY"


class MandateAckStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AuthDecision(str, Enum):
    APPROVED = "APPROVED"
    DECLINED_LIMIT = "DECLINED_LIMIT"
    DECLINED_RULE = "DECLINED_RULE"
    DECLINED_STATE = "DECLINED_STATE"
    DECLINED_VELOCITY = "DECLINED_VELOCITY"


class QualificationTier(str, Enum):
    QUALIFIED = "QUALIFIED"
    MID_QUALIFIED = "MID_QUALIFIED"
    NON_QUALIFIED = "NON_QUALIFIED"


class CampaignKind(str, Enum):
    EXPIRY_SWEEP = "EXPIRY_SWEEP"
    COMPROMISE_BLAST = "COMPROMISE_BLAST"
    NETWORK_MANDATE_REISSUE = "NETWORK_MANDATE_REISSUE"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ConversionJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class CardProgram(TypedDict, total=False):
    id: str
    program_code: str
    product_class: str
    network: str
    currency_code: str
    daily_spend_cap_cents: int
    authorization_rules_locked: bool
    open_card_count: int
    posture: str
    terminated_at: Optional[str]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BinRange(TypedDict, total=False):
    id: str
    program_id: str
    bin_prefix: str
    range_size: int
    pans_allocated: int
    pans_available: int
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionVendor(TypedDict, total=False):
    id: str
    vendor_code: str
    capability_flags: List[str]
    daily_capacity_cards: int
    supported_networks: List[str]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict, total=False):
    id: str
    program_id: str
    vendor_id: str
    scheduled_for_utc_date: str
    requested_card_count: int
    fulfilled_card_count: int
    unit_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CardAccount(TypedDict, total=False):
    id: str
    program_id: str
    external_account_ref: str
    account_class: str
    currency_code: str
    credit_limit_cents: int
    available_balance_cents: int
    lifecycle_status: str
    risk_tier: str
    daily_spend_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Card(TypedDict, total=False):
    id: str
    account_id: str
    bin_range_id: str
    pan_token: str
    last4: str
    expiry_month: int
    expiry_year: int
    form_factor: str
    lifecycle_status: str
    pin_status: str
    replaced_by_card_id: Optional[str]
    replaced_from_card_id: Optional[str]
    reissue_campaign_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActivationToken(TypedDict, total=False):
    id: str
    card_id: str
    token_value: str
    issued_at: str
    expires_at: str
    consumed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuthorizationRule(TypedDict, total=False):
    id: str
    subject_kind: str
    subject_ref: str
    rule_kind: str
    window_seconds: Optional[int]
    max_txn_count: Optional[int]
    max_amount_cents: Optional[int]
    mcc_list: Optional[List[str]]
    country_code_list: Optional[List[str]]
    priority_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Mandate(TypedDict, total=False):
    id: str
    network: str
    mandate_code: str
    title: str
    effective_at: str
    compliance_deadline: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MandateAck(TypedDict, total=False):
    id: str
    mandate_id: str
    program_id: str
    implementation_notes: str
    submitted_by_role: Optional[str]
    submitted_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: NO updated_at, NO version (PRD §2.4)
class AuthorizationEvent(TypedDict, total=False):
    id: str
    card_id: str
    account_id: str
    program_id: str
    amount_cents: int
    mcc: str
    country_code: str
    decision: str
    decision_reason: str
    applied_rule_id: Optional[str]
    authorized_at: str
    created_at: str


# Append-only: NO updated_at, NO version (PRD §2.4)
class Settlement(TypedDict, total=False):
    id: str
    authorization_event_id: str
    card_id: str
    account_id: str
    settled_amount_cents: int
    interchange_cents: int
    qualification_tier: str
    settled_at: str
    created_at: str


class ReissueCampaign(TypedDict, total=False):
    id: str
    program_id: str
    campaign_kind: str
    scheduled_for: str
    selection_filter: Dict[str, Any]
    targeted_unit_fee_cents: Optional[int]
    blanket_unit_fee_cents: Optional[int]
    estimated_card_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConversionJob(TypedDict, total=False):
    id: str
    source_program_id: str
    target_program_id: str
    execution_at: str
    accounts_planned: int
    accounts_converted: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramEconomics(TypedDict, total=False):
    month: str
    variant: str
    interchange_revenue_cents: int
    production_cost_cents: int
    reissue_fee_cents: int
    net_economics_cents: int
