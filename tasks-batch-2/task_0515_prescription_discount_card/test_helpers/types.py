"""Domain types: entity TypedDicts, status enums, role enum.

All monetary amounts are integer cents (PRD §2.5). Most entities carry the full
audit set (id, created_at, updated_at, version); InsuranceEstimate is immutable
and carries only id + created_at (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ────────────────────────────────────────────────────
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    PHARMACY_OPERATOR = "PharmacyOperator"
    COPAY_CARD_SPONSOR = "CopayCardSponsor"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums (PRD §3) ───────────────────────────────────────────────────
class PharmacyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PriceQuoteStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    EXPIRED = "EXPIRED"


class GoldBillingStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"


class GoldAccessStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class GoldTier(str, Enum):
    GOLD_INDIVIDUAL = "GOLD_INDIVIDUAL"
    GOLD_FAMILY = "GOLD_FAMILY"


class DiscountCardStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    VOID = "VOID"


class PricingBasis(str, Enum):
    DISCOUNT = "DISCOUNT"
    GOLD = "GOLD"


class PriceComparisonStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    NO_RESULTS = "NO_RESULTS"
    CONVERTED = "CONVERTED"


class RecommendedPath(str, Enum):
    DISCOUNT = "DISCOUNT"
    INSURANCE = "INSURANCE"
    TIE_DISCOUNT = "TIE_DISCOUNT"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    REVERSED = "REVERSED"
    REJECTED = "REJECTED"


class CopayCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    WITHDRAWN = "WITHDRAWN"


class CopayLinkStatus(str, Enum):
    LINKED = "LINKED"
    APPLIED = "APPLIED"
    RELEASED = "RELEASED"


class MailOrderStatus(str, Enum):
    PLACED = "PLACED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TelehealthStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DrugForm(str, Enum):
    TABLET = "TABLET"
    CAPSULE = "CAPSULE"
    LIQUID = "LIQUID"
    INJECTION = "INJECTION"


class TelehealthReason(str, Enum):
    NO_RESULTS = "NO_RESULTS"
    PRICE_TOO_HIGH = "PRICE_TOO_HIGH"
    NEW_PRESCRIPTION = "NEW_PRESCRIPTION"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# Full-audit entities (id + created_at + updated_at + version).

class Drug(TypedDict):
    id: str
    name: str
    ndc: str
    dosage_mg: float
    form: str
    is_controlled: bool
    awp_cents: int
    created_at: str
    updated_at: str
    version: int


class Pharmacy(TypedDict):
    id: str
    name: str
    chain_code: str
    state_code: str
    is_mail_order: bool
    dispense_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceQuote(TypedDict):
    id: str
    drug_id: str
    pharmacy_id: str
    cash_price_cents: int
    discount_price_cents: int
    gold_price_cents: int
    effective_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    has_insurance: bool
    lifetime_savings_cents: int
    active_gold_membership_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GoldMembership(TypedDict):
    id: str
    member_id: str
    tier: str
    monthly_fee_cents: int
    billing_status: str
    access_status: str
    covered_member_ids: List[str]
    coverage_start: str
    coverage_end: str
    created_at: str
    updated_at: str
    version: int


class DiscountCard(TypedDict):
    id: str
    member_id: str
    drug_id: str
    comparison_id: str
    pharmacy_id: str
    bin: str
    pcn: str
    group_code: str
    member_code: str
    pricing_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceComparison(TypedDict):
    id: str
    member_id: str
    drug_id: str
    state_code: str
    selected_pharmacy_id: Optional[str]
    best_price_cents: Optional[int]
    candidate_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    discount_card_id: str
    pharmacy_id: str
    drug_id: str
    quantity: int
    gross_cents: int
    net_cents: int
    savings_cents: int
    copay_offset_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CopayCard(TypedDict):
    id: str
    sponsor_name: str
    drug_id: str
    max_benefit_cents: int
    per_fill_cap_cents: int
    remaining_benefit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CopayLink(TypedDict):
    id: str
    copay_card_id: str
    member_id: str
    claim_id: Optional[str]
    applied_offset_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MailOrderFulfillment(TypedDict):
    id: str
    discount_card_id: str
    pharmacy_id: str
    member_id: str
    quantity: int
    ship_to_state: str
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TelehealthReferral(TypedDict):
    id: str
    member_id: str
    comparison_id: str
    drug_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only / immutable entity (id + created_at only) — PRD §2.4.
class InsuranceEstimate(TypedDict):
    id: str
    comparison_id: str
    member_id: str
    copay_cents: int
    deductible_remaining_cents: int
    recommended_path: str
    created_at: str
