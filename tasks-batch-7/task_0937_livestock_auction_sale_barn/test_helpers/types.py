"""Domain types for the Livestock Auction Sale Barn API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    BARN_ADMIN = "BarnAdmin"
    YARD_OPERATOR = "YardOperator"
    AUCTIONEER = "Auctioneer"
    RING_CLERK = "RingClerk"
    SETTLEMENT_CLERK = "SettlementClerk"
    INSPECTOR = "Inspector"
    CONSIGNOR = "Consignor"
    BUYER = "Buyer"
    CARRIER = "Carrier"


class PartyType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FARM = "FARM"
    DEALER = "DEALER"
    PACKER = "PACKER"
    CARRIER = "CARRIER"


class PartyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SaleDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECK_IN_OPEN = "CHECK_IN_OPEN"
    RINGING = "RINGING"
    BIDDING_CLOSED = "BIDDING_CLOSED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SpeciesClass(str, Enum):
    CATTLE = "CATTLE"
    SWINE = "SWINE"
    SHEEP_GOAT = "SHEEP_GOAT"
    HORSE = "HORSE"


class PenType(str, Enum):
    RECEIVING = "RECEIVING"
    HOLDING = "HOLDING"
    BUYER_PEN = "BUYER_PEN"
    SICK_BAY = "SICK_BAY"


class PenStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ScaleStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"


class DutyStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    ON_DUTY = "ON_DUTY"
    ON_BREAK = "ON_BREAK"


class WeighBasis(str, Enum):
    PENCIL_SHRINK = "PENCIL_SHRINK"
    STAND_ACTUAL = "STAND_ACTUAL"


class YardageBasis(str, Enum):
    PER_HEAD_DAY = "PER_HEAD_DAY"
    FLAT_PER_HEAD = "FLAT_PER_HEAD"


class CommissionBasis(str, Enum):
    TIERED_VALUE = "TIERED_VALUE"
    FLAT_PER_HEAD = "FLAT_PER_HEAD"


class RationType(str, Enum):
    NONE = "NONE"
    STARTER = "STARTER"
    GROWER = "GROWER"
    HAY = "HAY"


class ConsignmentStatus(str, Enum):
    INTAKE = "INTAKE"
    CHECKED_IN = "CHECKED_IN"
    SORTED = "SORTED"
    RECONCILED = "RECONCILED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class LivestockClass(str, Enum):
    FEEDER_STEER = "FEEDER_STEER"
    FEEDER_HEIFER = "FEEDER_HEIFER"
    BREEDING_BULL = "BREEDING_BULL"
    BREEDING_FEMALE = "BREEDING_FEMALE"
    CULL_COW = "CULL_COW"
    CALF = "CALF"


class BidBasis(str, Enum):
    PER_CWT = "PER_CWT"
    PER_HEAD = "PER_HEAD"


class LotSaleStatus(str, Enum):
    DRAFT = "DRAFT"
    PENNED = "PENNED"
    READY = "READY"
    IN_RING = "IN_RING"
    SOLD = "SOLD"
    NO_SALE = "NO_SALE"
    WITHDRAWN = "WITHDRAWN"


class LotCustodyStatus(str, Enum):
    BARN = "BARN"
    BUYER_PEN = "BUYER_PEN"
    LOADED = "LOADED"
    RELEASED = "RELEASED"


class WeightClass(str, Enum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    MEDIUM = "MEDIUM"
    HEAVY = "HEAVY"


class WeighTicketStatus(str, Enum):
    OPEN = "OPEN"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class PenMoveStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class BondType(str, Enum):
    BONDED = "BONDED"
    UNSECURED = "UNSECURED"
    CASH_ONLY = "CASH_ONLY"


class BuyerRegistrationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CREDIT_HOLD = "CREDIT_HOLD"
    REVOKED = "REVOKED"


class BidStatus(str, Enum):
    WINNING = "WINNING"
    OUTBID = "OUTBID"
    HAMMERED = "HAMMERED"
    VOIDED = "VOIDED"


class PurchaseStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    INVOICED = "INVOICED"
    ADJUSTED = "ADJUSTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class BuyerInvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    HELD = "HELD"
    RELEASED = "RELEASED"
    ADJUSTED = "ADJUSTED"


class HoldReason(str, Enum):
    NONE = "NONE"
    AWAITING_FUNDS = "AWAITING_FUNDS"


class ChargeType(str, Enum):
    COMMISSION = "COMMISSION"
    YARDAGE = "YARDAGE"
    FEED = "FEED"
    CHECKOFF_STATE = "CHECKOFF_STATE"
    CHECKOFF_NATIONAL = "CHECKOFF_NATIONAL"
    BRAND_FEE = "BRAND_FEE"
    INDEMNITY_FEE = "INDEMNITY_FEE"
    BUYER_FEE = "BUYER_FEE"
    HAUL = "HAUL"
    DOA_CREDIT = "DOA_CREDIT"


class ChargeSide(str, Enum):
    SELLER = "SELLER"
    BUYER = "BUYER"


class RevenueClass(str, Enum):
    BARN_REVENUE = "BARN_REVENUE"
    STATUTORY_REMITTANCE = "STATUTORY_REMITTANCE"
    PASS_THROUGH = "PASS_THROUGH"


class InspectionType(str, Enum):
    CVI = "CVI"
    BRAND = "BRAND"
    TRICH_TEST = "TRICH_TEST"
    BRUCELLOSIS_TEST = "BRUCELLOSIS_TEST"


class InspectionStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class InspectionResult(str, Enum):
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    RETEST = "RETEST"


class HaulBasis(str, Enum):
    PER_MILE = "PER_MILE"
    PER_HEAD_FLAT = "PER_HEAD_FLAT"


class ProrationBasis(str, Enum):
    BY_WEIGHT = "BY_WEIGHT"
    BY_HEAD = "BY_HEAD"


class LoadManifestStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"


class LossType(str, Enum):
    DEAD = "DEAD"
    CONDEMNED = "CONDEMNED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Entity shapes. Resources that carry id + created_at + updated_at + version
# are marked so; ChargeLine and LoadLine carry only id and created_at.
# ---------------------------------------------------------------------------


class Party(TypedDict):
    id: str
    legal_name: str
    party_type: str
    origin_state_code: str
    origin_county: str
    tax_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SaleDay(TypedDict):
    id: str
    sale_date: str
    barn_code: str
    barn_state_code: str
    status: str
    next_ring_order: int
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    consignment_id: str
    sale_day_id: str
    head_count: int
    livestock_class: str
    bid_basis: str
    opening_bid: float
    reserve_price: float
    sale_status: str
    custody_status: str
    pen_id: Optional[str]
    settle_weight_lb: Optional[int]
    avg_weight_lb: Optional[float]
    weight_class: str
    created_at: str
    updated_at: str
    version: int


class ChargeLine(TypedDict):
    """Append-and-regenerate artifact: no updated_at, no version."""

    id: str
    sale_day_id: str
    settlement_id: Optional[str]
    buyer_invoice_id: Optional[str]
    lot_id: Optional[str]
    charge_type: str
    side: str
    revenue_class: str
    head: int
    days: int
    unit_rate: float
    amount: float
    created_at: str


class LoadLine(TypedDict):
    """Append-and-regenerate artifact: no updated_at, no version."""

    id: str
    load_manifest_id: str
    lot_id: str
    head: int
    weight_lb: int
    prorated_haul_amount: float
    created_at: str
