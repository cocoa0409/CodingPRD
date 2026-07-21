"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Rare & Used Bookstore PRD (§3 resource narratives, §2.1 roles).
All resources carry id/created_at/updated_at/version per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PATRON = "Patron"
    APPRAISER = "Appraiser"
    STORE_CLERK = "StoreClerk"
    MANAGER = "Manager"


class PatronStatus(str, Enum):
    ACTIVE = "ACTIVE"


class IntakeLotStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class AcquisitionChannel(str, Enum):
    BUYBACK = "BUYBACK"
    CONSIGNMENT = "CONSIGNMENT"
    PURCHASE = "PURCHASE"
    FAIR = "FAIR"


class BookItemStatus(str, Enum):
    INTAKE = "INTAKE"
    GRADED = "GRADED"
    APPRAISED = "APPRAISED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"


class ConditionGrade(str, Enum):
    POOR = "POOR"
    GOOD = "GOOD"
    VERY_GOOD = "VERY_GOOD"
    FINE = "FINE"
    AS_NEW = "AS_NEW"


class AppraisalBasis(str, Enum):
    FAIR_MARKET = "FAIR_MARKET"
    RETAIL_REPLACEMENT = "RETAIL_REPLACEMENT"


class AppraisalStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class FeeModel(str, Enum):
    GROSS_COMMISSION = "GROSS_COMMISSION"
    NET_COMMISSION = "NET_COMMISSION"


class ConsignmentAgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AMENDED = "AMENDED"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"


class OnlineStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    SOLD = "SOLD"
    DELISTED = "DELISTED"


class ShopStatus(str, Enum):
    DRAFT = "DRAFT"
    ON_SHELF = "ON_SHELF"
    SOLD = "SOLD"
    PULLED = "PULLED"


class SoldChannel(str, Enum):
    ONLINE = "ONLINE"
    SHOP = "SHOP"


class BuybackOfferStatus(str, Enum):
    PENDING = "PENDING"
    AUTO_APPROVED = "AUTO_APPROVED"
    ACCEPTED = "ACCEPTED"
    VOIDED = "VOIDED"


class SaleChannel(str, Enum):
    ONLINE = "ONLINE"
    SHOP = "SHOP"


class SaleOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    REFUNDED = "REFUNDED"


class BoothSlotStatus(str, Enum):
    RESERVED = "RESERVED"


class ShipmentStatus(str, Enum):
    PACKED = "PACKED"


# ── Entity TypedDicts (all carry the common id/created_at/updated_at/version) ──

class Patron(TypedDict):
    id: str
    display_name: str
    email: str
    default_commission_pct: float
    store_credit_cents: int
    consignor_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IntakeLot(TypedDict):
    id: str
    consignor_id: Optional[str]
    acquisition_channel: str
    item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BookItem(TypedDict):
    id: str
    intake_lot_id: str
    consignor_id: Optional[str]
    title: str
    author: str
    printing_number: int
    stated_first_edition: bool
    comp_median_cents: int
    condition_grade: Optional[str]
    is_first_edition: bool
    appraised_value_cents: Optional[int]
    provenance: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    book_item_id: str
    basis: str
    fair_market_value_cents: int
    retail_replacement_value_cents: int
    final_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentAgreement(TypedDict):
    id: str
    patron_id: str
    book_item_id: str
    commission_pct: float
    fee_model: str
    flat_fee_cents: int
    amendment_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CatalogListing(TypedDict):
    id: str
    book_item_id: str
    list_price_cents: int
    online_status: str
    shop_status: str
    sold_channel: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuybackOffer(TypedDict):
    id: str
    patron_id: str
    book_item_id: Optional[str]
    offer_value_cents: int
    credit_amount_cents: int
    auto_approved: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FairEvent(TypedDict):
    id: str
    name: str
    table_capacity: int
    reserved_display_count: int
    created_at: str
    updated_at: str
    version: int


class BoothSlot(TypedDict):
    id: str
    fair_event_id: str
    booth_table: str
    window_start: str
    window_end: str
    display_item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SaleOrder(TypedDict):
    id: str
    buyer_patron_id: Optional[str]
    channel: str
    line_items: List[dict]
    tax_pct: float
    store_credit_applied_cents: int
    subtotal_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    sale_order_id: str
    packing_station_label: str
    weight_grams: int
    zone: int
    declared_value_cents: int
    insured: bool
    pack_start: str
    pack_end: str
    shipping_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
