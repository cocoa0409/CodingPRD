"""Domain types: entity TypedDicts, status enums, role enum.

All money fields are integer counts of cents.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    BILLING_ADMIN = "BillingAdmin"
    CUSTOMER_SERVICE_AGENT = "CustomerServiceAgent"
    FIELD_TECHNICIAN = "FieldTechnician"
    SUBSCRIBER = "Subscriber"


# ─── Status / enum value sets ─────────────────────────────────────────────
class AccountLifecycleStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class AccountPromoStatus(str, Enum):
    NONE = "NONE"
    PROMO_ACTIVE = "PROMO_ACTIVE"
    ROLLED_BACK = "ROLLED_BACK"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DOWNGRADED = "DOWNGRADED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DROPPED = "DROPPED"


class AddOnDropReason(str, Enum):
    USER = "USER"
    INCOMPATIBLE_DOWNGRADE = "INCOMPATIBLE_DOWNGRADE"
    CANCELLED = "CANCELLED"


class EquipmentLeaseStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RETURNED = "RETURNED"
    UNRETURNED = "UNRETURNED"


class ServiceVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class VisitType(str, Enum):
    INSTALL = "INSTALL"
    SERVICE = "SERVICE"


class PromotionApplicationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"


class DiscountKind(str, Enum):
    PERCENT_OFF_PACKAGE = "PERCENT_OFF_PACKAGE"
    FLAT_OFF_TOTAL = "FLAT_OFF_TOTAL"
    EQUIPMENT_WAIVER = "EQUIPMENT_WAIVER"


class BillingStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class ProrationMode(str, Enum):
    FULL_CYCLE = "FULL_CYCLE"
    PRORATED = "PRORATED"


class TierCode(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class ChannelKind(str, Enum):
    PREMIUM = "PREMIUM"
    ADD_ON = "ADD_ON"


class EquipmentKind(str, Enum):
    BOX = "BOX"
    DVR = "DVR"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Catalog entities carrying id + created_at + updated_at + version.
class ChannelPackage(TypedDict):
    id: str
    tier_code: str
    name: str
    monthly_fee_cents: int
    channel_count: int
    rank: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class PremiumChannel(TypedDict):
    id: str
    code: str
    name: str
    kind: str
    monthly_fee_cents: int
    min_package_rank: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class EquipmentModel(TypedDict):
    id: str
    model_code: str
    kind: str
    monthly_lease_cents: int
    replacement_cost_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class PromotionOffer(TypedDict):
    id: str
    code: str
    discount_kind: str
    percent_off: float
    flat_off_cents: int
    promo_months: int
    requires_min_rank: int
    rollback_protected: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


# Reference-data catalog entities carrying ONLY id + created_at (no version/updated_at).
class Technician(TypedDict):
    id: str
    name: str
    home_state_code: str
    active: bool
    created_at: str


class RegionalSportsFeeRule(TypedDict):
    id: str
    state_code: str
    base_fee_cents: int
    premier_surcharge_cents: int
    active: bool
    created_at: str


# Aggregate root + children (all full resources with version).
class Account(TypedDict):
    id: str
    customer_name: str
    service_state_code: str
    tenure_months: int
    lifecycle_status: str
    promo_status: str
    active_package_id: Optional[str]
    contract_term_months: int
    regional_sports_fee_cents: int
    monthly_recurring_cents: int
    cancellation_effective_cycle: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    account_id: str
    package_id: str
    status: str
    base_fee_cents: int
    previous_subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddOnSubscription(TypedDict):
    id: str
    account_id: str
    premium_channel_id: str
    status: str
    fee_cents: int
    drop_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentLease(TypedDict):
    id: str
    account_id: str
    equipment_model_id: str
    quantity: int
    status: str
    monthly_lease_cents: int
    unreturned_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    account_id: str
    visit_type: str
    window_start: str
    window_end: str
    technician_id: str
    status: str
    truck_roll_fee_cents: int
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PromotionApplication(TypedDict):
    id: str
    account_id: str
    promotion_offer_id: str
    status: str
    applied_at_tenure: int
    rollback_at_tenure: int
    discount_cents_snapshot: int
    is_winback: bool
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict):
    id: str
    account_id: str
    cycle_index: int
    proration_mode: str
    days_in_cycle: int
    active_days: int
    status: str
    package_charge_cents: int
    addon_charge_cents: int
    equipment_charge_cents: int
    regional_sports_fee_cents: int
    visit_charge_cents: int
    promo_discount_cents: int
    etf_charge_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int
