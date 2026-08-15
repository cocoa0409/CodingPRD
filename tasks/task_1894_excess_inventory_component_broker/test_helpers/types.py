"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource narratives. Common resources carry
id + created_at + updated_at + version; the two append-only resources
(MarketPriceSnapshot, EscrowEntry) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    BROKER_OPS = "BrokerOps"
    INSPECTOR = "Inspector"
    FINANCE_ADMIN = "FinanceAdmin"
    SELLER = "Seller"
    CUSTOMER = "Customer"


class UrgencyTier(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"
    CRITICAL = "CRITICAL"


class BuyOfferStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNDER_INSPECTION = "UNDER_INSPECTION"
    INSPECTION_PASSED = "INSPECTION_PASSED"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    CONVERTED = "CONVERTED"
    RETURN_PENDING = "RETURN_PENDING"
    RETURNED = "RETURNED"


class InspectionResult(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    FAIL_COUNTERFEIT = "FAIL_COUNTERFEIT"
    FAIL_DAMAGED = "FAIL_DAMAGED"
    FAIL_DOCUMENTATION = "FAIL_DOCUMENTATION"


class AcquisitionMode(str, Enum):
    BROKER_OWNED = "BROKER_OWNED"
    CONSIGNMENT = "CONSIGNMENT"


class LotStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LISTED = "LISTED"
    FULLY_RESERVED = "FULLY_RESERVED"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class ConsignmentAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    WITHDRAWN = "WITHDRAWN"
    SOLD_OUT = "SOLD_OUT"


class SalesOrderStatus(str, Enum):
    PENDING_ESCROW = "PENDING_ESCROW"
    ESCROW_FUNDED = "ESCROW_FUNDED"
    FULFILLING = "FULFILLING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class EscrowEntryType(str, Enum):
    DEPOSIT = "DEPOSIT"
    CUSTOMER_REFUND = "CUSTOMER_REFUND"
    BROKER_FEE = "BROKER_FEE"
    SELLER_PAYOUT = "SELLER_PAYOUT"
    BROKER_REVENUE = "BROKER_REVENUE"


class ReturnCaseStatus(str, Enum):
    OPENED = "OPENED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REFUND_ISSUED = "REFUND_ISSUED"


class ReturnReason(str, Enum):
    COUNTERFEIT_SUSPECTED = "COUNTERFEIT_SUSPECTED"
    DAMAGED = "DAMAGED"
    WRONG_PART = "WRONG_PART"
    FAILED_INCOMING_INSPECTION = "FAILED_INCOMING_INSPECTION"


class Seller(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    payout_terms_days: int
    account_balance_cents: int
    total_payouts_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    urgency_tier: str
    credit_limit_cents: int
    open_order_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class StorageBin(TypedDict, total=False):
    id: str
    bin_code: str
    capacity_units: int
    occupied_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class BuyOffer(TypedDict, total=False):
    id: str
    seller_id: str
    mpn: str
    quantity: int
    ask_price_per_unit_cents: int
    provenance_doc_url: Optional[str]
    status: str
    agreed_unit_price_cents: Optional[int]
    acquisition_mode: Optional[str]
    inspection_result: str
    failure_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    buy_offer_id: str
    mpn: str
    storage_bin_id: str
    storage_mode: str
    quantity_received: int
    qty_available: int
    qty_reserved: int
    qty_sold: int
    qty_returned: int
    cost_basis_per_unit_cents: int
    received_at: str
    is_counterfeit_suspect: bool
    status: str
    carrying_value_straight_line_cents: int
    carrying_value_market_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ConsignmentAgreement(TypedDict, total=False):
    id: str
    seller_id: str
    lot_id: str
    effective_from: str
    effective_to: str
    broker_fee_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketPriceSnapshot(TypedDict, total=False):
    # Append-only record: id + created_at only; no updated_at, no version.
    id: str
    mpn: str
    spot_price_cents: int
    source: str
    observed_at: str
    created_at: str


class Listing(TypedDict, total=False):
    id: str
    lot_id: str
    asking_price_per_unit_cents: int
    recommended_price_per_unit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_id: str
    listing_id: str
    quantity: int
    urgency_tier_snapshot: str
    consignment_fee_bps_snapshot: Optional[int]
    provisional_unit_price_cents: int
    provisional_total_cents: int
    required_escrow_cents: int
    escrow_funded_cents: int
    final_unit_price_cents: Optional[int]
    final_total_cents: Optional[int]
    customer_refund_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowEntry(TypedDict, total=False):
    # Append-only record: id + created_at only; no updated_at, no version.
    id: str
    sales_order_id: str
    entry_type: str
    amount_cents: int
    note: str
    created_at: str


class ReturnCase(TypedDict, total=False):
    id: str
    sales_order_id: str
    reason: str
    status: str
    refund_amount_cents: Optional[int]
    rejection_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
