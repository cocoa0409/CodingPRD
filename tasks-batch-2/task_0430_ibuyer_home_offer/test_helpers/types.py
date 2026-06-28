"""Domain types for the iBuyer Home Offer API: entity TypedDicts, status enums, role enum.

All entities (Seller, Property, Offer, Assessment, RepairLineItem, Transaction,
Resale) carry the full common-field set id + created_at + updated_at + version
(PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SELLER = "Seller"
    PRICING_ANALYST = "PricingAnalyst"
    OPERATIONS_ADMIN = "OperationsAdmin"


class PayoutMethod(str, Enum):
    ACH = "ACH"
    WIRE = "WIRE"


class PropertyStatus(str, Enum):
    VALUED = "VALUED"
    UNDER_OFFER = "UNDER_OFFER"
    IN_TRANSACTION = "IN_TRANSACTION"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"


class OfferStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class TransactionStatus(str, Enum):
    PENDING_ASSESSMENT = "PENDING_ASSESSMENT"
    SCHEDULED = "SCHEDULED"
    INSPECTION = "INSPECTION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ResaleStatus(str, Enum):
    LISTED = "LISTED"
    SOLD = "SOLD"
    DELISTED = "DELISTED"


class ConditionScore(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class RepairCategory(str, Enum):
    ROOF = "ROOF"
    HVAC = "HVAC"
    FOUNDATION = "FOUNDATION"
    COSMETIC = "COSMETIC"
    OTHER = "OTHER"


# Ordered worst-to-best rank used by the worst-component condition score (PRD §3.4).
CONDITION_RANK = {"POOR": 0, "FAIR": 1, "GOOD": 2, "EXCELLENT": 3}


class Seller(TypedDict):
    id: str
    email: str
    full_name: str
    payout_method: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    seller_id: str
    address_line: str
    zip_code: str
    bedrooms: int
    living_area_sqft: int
    comp_median_value: float
    market_trend_pct: float
    avm_value: float
    revised_avm_value: Optional[float]
    condition_score: Optional[str]
    status: str
    active_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    property_id: str
    avm_value_snapshot: float
    service_fee_pct: float
    service_fee: float
    estimated_concession: float
    preliminary_net_proceeds: float
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    offer_id: str
    roof_condition: Optional[str]
    hvac_condition: Optional[str]
    foundation_condition: Optional[str]
    questionnaire_flags: List[str]
    condition_score: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairLineItem(TypedDict):
    id: str
    assessment_id: str
    category: str
    estimate_amount: float
    rounded_amount: float
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    offer_id: str
    property_id: str
    repair_credit: float
    final_concession: float
    retrade_amount: float
    close_date: Optional[str]
    leaseback_days: int
    leaseback_daily_rate: float
    leaseback_total: float
    final_net_proceeds: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Resale(TypedDict):
    id: str
    transaction_id: str
    list_price: float
    sold_price: Optional[float]
    resale_commission_pct: float
    projected_spread: float
    net_spread: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int
