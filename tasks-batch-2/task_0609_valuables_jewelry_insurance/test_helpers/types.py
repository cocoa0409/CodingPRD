"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are taken from the Valuables & Jewelry
Insurance PRD (§2, §3 entity narratives).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class PolicyholderStatus(str, Enum):
    ACTIVE = "ACTIVE"


class RepairShopStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PolicyCoverageStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class PolicyBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"


class ScheduledItemStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class AppraisalStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class EndorsementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ClaimStatus(str, Enum):
    FNOL = "FNOL"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class RepairOrderStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    REPAIRED = "REPAIRED"
    DEEMED_TOTAL_LOSS = "DEEMED_TOTAL_LOSS"
    CLOSED = "CLOSED"


class PremiumPaymentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    REVERSED = "REVERSED"


# ─── Enumerated input value sets ───────────────────────────────────────────

class CoverageType(str, Enum):
    ALL_RISK = "ALL_RISK"
    NAMED_PERIL = "NAMED_PERIL"


class ValuationBasis(str, Enum):
    AGREED_VALUE = "AGREED_VALUE"
    REPLACEMENT_COST = "REPLACEMENT_COST"


class DeductibleOption(str, Enum):
    ZERO = "ZERO"
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class InflationGuardMode(str, Enum):
    NONE = "NONE"
    SIMPLE = "SIMPLE"
    COMPOUND = "COMPOUND"


class ItemCategory(str, Enum):
    RING = "RING"
    NECKLACE = "NECKLACE"
    WATCH = "WATCH"
    LOOSE_STONE = "LOOSE_STONE"
    OTHER = "OTHER"


class Peril(str, Enum):
    THEFT = "THEFT"
    FIRE = "FIRE"
    FLOOD = "FLOOD"
    ACCIDENTAL_DAMAGE = "ACCIDENTAL_DAMAGE"
    MYSTERIOUS_DISAPPEARANCE = "MYSTERIOUS_DISAPPEARANCE"


class LossType(str, Enum):
    TOTAL_LOSS = "TOTAL_LOSS"
    PARTIAL_DAMAGE = "PARTIAL_DAMAGE"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class EndorsementType(str, Enum):
    ADD_ITEM = "ADD_ITEM"
    REMOVE_ITEM = "REMOVE_ITEM"
    CHANGE_DEDUCTIBLE = "CHANGE_DEDUCTIBLE"


# ─── Role enum ─────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    APPRAISER = "Appraiser"
    POLICYHOLDER = "Policyholder"
    REPAIR_SHOP = "RepairShop"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# common_fields: true -> id + created_at + updated_at + version

class Policyholder(TypedDict):
    id: str
    email: str
    full_name: str
    residence_zip: str
    status: str
    created_at: str
    updated_at: str
    version: int


# RiskZone: common_fields false -> id + created_at ONLY (immutable rate row)
class RiskZone(TypedDict):
    id: str
    zip_prefix: str
    risk_band: str
    rate_per_thousand_cents: int
    catastrophe_loaded: bool
    created_at: str


class RepairShop(TypedDict):
    id: str
    name: str
    service_zip: str
    in_network: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    policyholder_id: str
    coverage_type: str
    valuation_basis: str
    deductible_option: str
    worldwide_coverage: bool
    listed_perils: List[str]
    inflation_guard_mode: str
    inflation_guard_pct: float
    deductible_cents: int
    total_insured_value_cents: int
    annual_premium_cents: int
    coverage_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class ScheduledItem(TypedDict):
    id: str
    policy_id: str
    description: str
    category: str
    location_zip: str
    scheduled_value_cents: int
    current_value_cents: Optional[int]
    revaluation_epoch: int
    appraisal_id: Optional[str]
    item_status: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    policyholder_id: str
    appraiser_id: str
    appraised_value_cents: int
    effective_date_iso: str
    valid_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict):
    id: str
    policy_id: str
    endorsement_type: str
    target_item_id: Optional[str]
    new_deductible_option: Optional[str]
    premium_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    scheduled_item_id: str
    peril: str
    loss_type: str
    loss_zip: Optional[str]
    occurred_outside_country: bool
    claimed_amount_cents: int
    settlement_cents: int
    deductible_applied_cents: int
    info_request_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    claim_id: str
    repair_shop_id: str
    authorized_amount_cents: int
    actual_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumPayment(TypedDict):
    id: str
    policy_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
