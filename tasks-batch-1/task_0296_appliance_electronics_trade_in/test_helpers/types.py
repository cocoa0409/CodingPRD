"""Domain types: entity TypedDicts, status enums, role enum.

All field names are PRD-exact (Appliance & Electronics Trade-In API).
Every persisted resource in this PRD carries the common fields
id + created_at + updated_at + version (PRD §2.6).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums (PRD §3) ────────────────────────────

class TradeInStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    KIT_SENT = "KIT_SENT"
    RECEIVED = "RECEIVED"
    INSPECTED = "INSPECTED"
    REQUOTED = "REQUOTED"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    RECYCLED = "RECYCLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    HONORED = "HONORED"


class QuoteKind(str, Enum):
    INITIAL = "INITIAL"
    REQUOTE = "REQUOTE"


class ShippingKitStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED_TO_HUB = "DELIVERED_TO_HUB"


class InspectionOutcome(str, Enum):
    MATCH = "MATCH"
    REQUOTE = "REQUOTE"
    RECYCLE = "RECYCLE"


class InspectionSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class PayoutStatus(str, Enum):
    PAID = "PAID"
    REVERSED = "REVERSED"


class PayoutMethod(str, Enum):
    STORE_CREDIT = "STORE_CREDIT"
    ACH = "ACH"
    CHECK = "CHECK"


class DataWipeMethod(str, Enum):
    CRYPTO_ERASE = "CRYPTO_ERASE"
    NIST_PURGE = "NIST_PURGE"
    PHYSICAL_DESTROY = "PHYSICAL_DESTROY"


class DataWipeResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DispositionKind(str, Enum):
    RETURN_TO_CUSTOMER = "RETURN_TO_CUSTOMER"
    RECYCLE = "RECYCLE"
    REFURBISH_INVENTORY = "REFURBISH_INVENTORY"


class DeviceCategory(str, Enum):
    SMARTPHONE = "SMARTPHONE"
    LAPTOP = "LAPTOP"
    TABLET = "TABLET"
    REFRIGERATOR = "REFRIGERATOR"
    WASHER = "WASHER"
    TV = "TV"
    WEARABLE = "WEARABLE"


class CosmeticGrade(str, Enum):
    FLAWLESS = "FLAWLESS"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class CampaignStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class DeviceModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class UserRole(str, Enum):
    CATALOG_ADMIN = "CatalogAdmin"
    CUSTOMER = "Customer"
    GRADING_AGENT = "GradingAgent"
    FINANCE_OPERATOR = "FinanceOperator"


# ─── Entity TypedDicts (PRD §3; all common_fields: true) ─────

class Catalog(TypedDict):
    id: str
    name: str
    currency: str
    price_lock_hours: int
    requote_tolerance_pct: float
    data_wipe_required_categories: List[str]
    recycle_floor_value_cents: int
    created_at: str
    updated_at: str
    version: int


class DeviceModel(TypedDict):
    id: str
    catalog_id: str
    manufacturer: str
    model_code: str
    category: str
    base_value_cents: int
    condition_multipliers: dict
    defect_deductions: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class PromotionCampaign(TypedDict):
    id: str
    catalog_id: str
    code: str
    category_scope: str
    effective_from: str
    effective_to: str
    bonus_pct: float
    bonus_flat_cents: int
    bonus_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    wallet_balance_cents: int
    lifetime_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    device_model_id: str
    promotion_campaign_id: Optional[str]
    locked_quote_id: Optional[str]
    declared_grade: str
    declared_defects: List[str]
    declared_powers_on: bool
    status: str
    final_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    trade_in_id: str
    kind: str
    graded_subtotal_cents: int
    promo_bonus_cents: int
    amount_cents: int
    lock_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShippingKit(TypedDict):
    id: str
    trade_in_id: str
    tracking_number: str
    label_url: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    trade_in_id: str
    graded_at: str
    verified_grade: str
    verified_defects: List[str]
    verified_powers_on: bool
    inspected_value_cents: int
    outcome: str
    created_at: str
    updated_at: str
    version: int


class InspectionSlot(TypedDict):
    id: str
    catalog_id: str
    lane_category: str
    slot_start: str
    slot_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    trade_in_id: str
    customer_id: str
    method: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DataWipeCertificate(TypedDict):
    id: str
    trade_in_id: str
    method: str
    result: str
    certificate_serial: str
    created_at: str
    updated_at: str
    version: int


class DispositionRecord(TypedDict):
    id: str
    trade_in_id: str
    disposition: str
    reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
