"""Domain types for the Heavy Equipment Auction API.

Entity TypedDicts, status enums and the role enum, named exactly as the PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CONSIGNOR = "Consignor"
    INTAKE_INSPECTOR = "IntakeInspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AUCTION_OPERATOR = "AuctionOperator"
    SETTLEMENT_OFFICER = "SettlementOfficer"
    BIDDER = "Bidder"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class SellerType(str, Enum):
    DEALER = "DEALER"
    FLEET_OWNER = "FLEET_OWNER"
    BANK_REPO = "BANK_REPO"
    GOVERNMENT = "GOVERNMENT"


class AgreementType(str, Enum):
    RESERVE = "RESERVE"
    UNRESERVED = "UNRESERVED"


class CommissionScheduleCode(str, Enum):
    RESERVE_STD = "RESERVE_STD"
    UNRESERVED_STD = "UNRESERVED_STD"


class ConsignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INTAKE_ACCEPTED = "INTAKE_ACCEPTED"
    CATALOGED = "CATALOGED"


class LotLifecycleStatus(str, Enum):
    INTAKE = "INTAKE"
    INSPECTED = "INSPECTED"
    CATALOG_READY = "CATALOG_READY"
    ASSIGNED = "ASSIGNED"
    HAMMERED = "HAMMERED"
    UNSOLD = "UNSOLD"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"
    REOFFER_QUEUED = "REOFFER_QUEUED"
    WITHDRAWN = "WITHDRAWN"


class LotTitleStatus(str, Enum):
    TITLE_PENDING = "TITLE_PENDING"
    LIEN_SEARCH_ORDERED = "LIEN_SEARCH_ORDERED"
    LIEN_CLEAR = "LIEN_CLEAR"
    LIEN_ENCUMBERED = "LIEN_ENCUMBERED"
    LIEN_RELEASED = "LIEN_RELEASED"


class GradeBand(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ConditionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class RefurbishmentOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    QA_REVIEW = "QA_REVIEW"
    REWORK = "REWORK"
    COMPLETED = "COMPLETED"


class AuctionKind(str, Enum):
    LIVE_ONSITE = "LIVE_ONSITE"
    TIMED_ONLINE = "TIMED_ONLINE"


class ReservePolicy(str, Enum):
    UNRESERVED = "UNRESERVED"
    RESERVE_ALLOWED = "RESERVE_ALLOWED"


class PremiumScheduleCode(str, Enum):
    STANDARD = "STANDARD"
    LOW_VALUE_FLAT = "LOW_VALUE_FLAT"


class AuctionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class CountryTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class PaymentTermsCode(str, Enum):
    PREPAY = "PREPAY"
    NET_7 = "NET_7"
    NET_30 = "NET_30"


class RegistrationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WINNING = "WINNING"
    LOSING = "LOSING"


class SaleStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONSIGNOR_COUNTERED = "CONSIGNOR_COUNTERED"
    CONFIRMED = "CONFIRMED"
    NO_SALE = "NO_SALE"
    SETTLED = "SETTLED"
    DEFAULTED = "DEFAULTED"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoicePaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    IN_DEFAULT = "IN_DEFAULT"
    WRITTEN_OFF = "WRITTEN_OFF"


class InvoiceReleaseStatus(str, Enum):
    HELD = "HELD"
    RELEASE_AUTHORIZED = "RELEASE_AUTHORIZED"
    LOADOUT_BOOKED = "LOADOUT_BOOKED"
    LOADED_OUT = "LOADED_OUT"
    ABANDONED = "ABANDONED"


class PaymentMethod(str, Enum):
    WIRE = "WIRE"
    CARD = "CARD"
    FINANCED_DRAW = "FINANCED_DRAW"


class PaymentStatus(str, Enum):
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ExportPacketStatus(str, Enum):
    PREPARING = "PREPARING"
    TITLE_ATTACHED = "TITLE_ATTACHED"
    CUSTOMS_FILED = "CUSTOMS_FILED"
    EXPORT_CLEARED = "EXPORT_CLEARED"
    CUSTOMS_REJECTED = "CUSTOMS_REJECTED"


class TransportMode(str, Enum):
    BUYER_ARRANGED = "BUYER_ARRANGED"
    HOUSE_BROKERED = "HOUSE_BROKERED"
    RAIL = "RAIL"
    OCEAN_CONTAINER = "OCEAN_CONTAINER"


class LoadoutSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ConsignorSettlementStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Entities carrying id / created_at / updated_at / version
# ---------------------------------------------------------------------------

class Yard(TypedDict):
    id: str
    code: str
    country_code: str
    teardown_buffer_minutes: int
    loadout_deadline_days: int
    currency_code: str
    created_at: str
    updated_at: str
    version: int


class LoadoutBay(TypedDict):
    id: str
    yard_id: str
    bay_number: int
    crane_capacity_kg: int
    is_active: bool
    reserved_tonnage_kg: int
    created_at: str
    updated_at: str
    version: int


class Consignor(TypedDict):
    id: str
    legal_name: str
    country_code: str
    seller_type: str
    unreserved_policy_ack: bool
    open_consignment_count: int
    lifetime_net_proceeds_cents: int
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict):
    id: str
    consignor_id: str
    agreement_type: str
    commission_schedule_code: str
    refurb_authorization_cap_cents: int
    advance_paid_cents: int
    advance_outstanding_cents: int
    status: str
    correction_note: Optional[str]
    unsold_lot_count: int
    reoffer_lot_count: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    consignment_id: str
    replacement_of_lot_id: Optional[str]
    auction_id: Optional[str]
    make: str
    model: str
    model_year: int
    serial_number: str
    hour_meter_reading: int
    weight_kg: int
    title_required: bool
    reserve_price_cents: Optional[int]
    sold_as_hours_unverified: bool
    lifecycle_status: str
    title_status: str
    lien_search_reference: Optional[str]
    lienholder_name: Optional[str]
    withdrawal_reason: Optional[str]
    high_bid_cents: int
    created_at: str
    updated_at: str
    version: int


class ConditionReport(TypedDict):
    id: str
    lot_id: str
    inspector_user_id: str
    structural_score: float
    powertrain_score: float
    hydraulics_score: float
    tires_score: float
    observed_hour_meter_reading: int
    hour_meter_verified: bool
    hour_meter_photo_ref: Optional[str]
    hour_meter_variance_pct: Optional[float]
    grade_score: float
    grade_band: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RefurbishmentOrder(TypedDict):
    id: str
    lot_id: str
    scope_note: str
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    qa_note: Optional[str]
    qa_signed_off_by_user_id: Optional[str]
    rework_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Auction(TypedDict):
    id: str
    yard_id: str
    kind: str
    reserve_policy: str
    premium_schedule_code: str
    window_start: str
    window_end: str
    loadout_deadline_at: str
    status: str
    assigned_lot_count: int
    sold_lot_count: int
    unsold_lot_count: int
    gross_hammer_cents: int
    created_at: str
    updated_at: str
    version: int


class Bidder(TypedDict):
    id: str
    legal_name: str
    country_code: str
    tax_id: str
    country_tier: str
    deposit_total_cents: int
    deposit_held_cents: int
    deposit_available_cents: int
    deposit_forfeited_cents: int
    open_exposure_cents: int
    default_strike_count: int
    lifetime_purchase_cents: int
    created_at: str
    updated_at: str
    version: int


class BidderRegistration(TypedDict):
    id: str
    bidder_id: str
    auction_id: str
    deposit_hold_cents: int
    financing_requested: bool
    paddle_number: int
    approved_credit_limit_cents: int
    financing_approved: bool
    payment_terms_code: Optional[str]
    leverage_multiplier: Optional[int]
    bid_cap_cents: int
    credit_approved_by_user_id: Optional[str]
    decline_reason: Optional[str]
    deposit_applied_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    lot_id: str
    auction_id: str
    winning_bid_id: str
    registration_id: str
    hammer_price_cents: int
    reserve_met: bool
    hammered_at: str
    counter_round: int
    counter_price_cents: Optional[int]
    reject_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    sale_id: str
    bidder_id: str
    registration_id: str
    settlement_variant: str
    hammer_price_cents: int
    is_cross_border: bool
    buyer_premium_cents: int
    documentation_fee_cents: int
    title_transfer_fee_cents: int
    financing_fee_cents: int
    subtotal_cents: int
    tax_rate_applied: float
    tax_cents: int
    chargeable_storage_days: int
    storage_fee_cents: int
    credit_memo_cents: int
    deposit_applied_cents: int
    total_due_cents: int
    amount_paid_cents: int
    outstanding_cents: int
    grace_end_at: str
    payment_due_at: str
    deficiency_claim_cents: int
    payment_status: str
    release_status: str
    created_at: str
    updated_at: str
    version: int


class ExportDocumentPacket(TypedDict):
    id: str
    invoice_id: str
    destination_country_code: str
    title_document_ref: Optional[str]
    customs_entry_ref: Optional[str]
    rejection_reason: Optional[str]
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadoutSlot(TypedDict):
    id: str
    invoice_id: str
    bay_id: str
    slot_start: str
    slot_end: str
    tonnage_kg: int
    transport_mode: str
    gate_pass_ref: Optional[str]
    supersedes_slot_id: Optional[str]
    cancel_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignorSettlement(TypedDict):
    id: str
    sale_id: str
    gross_proceeds_cents: int
    commission_cents: int
    refurb_recharge_cents: int
    house_absorbed_refurb_cents: int
    advance_recovery_cents: int
    no_sale_fee_cents: int
    net_proceeds_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only records: a Bid and a Payment carry only id and created_at
# ---------------------------------------------------------------------------

class Bid(TypedDict):
    id: str
    registration_id: str
    lot_id: str
    amount_cents: int
    placed_at: str
    status: str
    created_at: str


class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    currency_code: str
    status: str
    received_at: str
    created_at: str
