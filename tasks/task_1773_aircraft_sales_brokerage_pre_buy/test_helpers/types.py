"""Domain types: entity TypedDicts, status enums, role enum.

All nine resources carry the common system-managed fields id, created_at,
updated_at, and version (PRD common-resource-properties section).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    BROKER_PRINCIPAL = "BrokerPrincipal"
    LISTING_AGENT = "ListingAgent"
    BUYER_AGENT = "BuyerAgent"
    ESCROW_OFFICER = "EscrowOfficer"
    FACILITY_SCHEDULER = "FacilityScheduler"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    SOLD = "SOLD"


class ValuationStatus(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class QualificationStatus(str, Enum):
    UNQUALIFIED = "UNQUALIFIED"
    QUALIFIED = "QUALIFIED"


class CompStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class LoiStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DisclosureStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FULLY_ACKED = "FULLY_ACKED"


class TransactionStatus(str, Enum):
    OPENED = "OPENED"
    ESCROW_FUNDED = "ESCROW_FUNDED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    INSPECTION_COMPLETE = "INSPECTION_COMPLETE"
    DISCREPANCY_NEGOTIATION = "DISCREPANCY_NEGOTIATION"
    DELIVERY_PENDING = "DELIVERY_PENDING"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class EscrowStatus(str, Enum):
    AWAITING_FUNDS = "AWAITING_FUNDS"
    FUNDED = "FUNDED"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Severity(str, Enum):
    AIRWORTHINESS = "AIRWORTHINESS"
    NON_AIRWORTHINESS = "NON_AIRWORTHINESS"


class Resolution(str, Enum):
    REPAIR = "REPAIR"
    CREDIT = "CREDIT"
    WAIVED = "WAIVED"


class DiscrepancyStatus(str, Enum):
    RAISED = "RAISED"
    COUNTERED = "COUNTERED"
    RESOLVED = "RESOLVED"


class InspectionFacility(TypedDict):
    id: str
    name: str
    airport_code: str
    turnaround_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    tail_number: str
    make: str
    model: str
    year: int
    total_time_hours: int
    asking_price_usd: float
    seller_name: str
    market_value_estimate_usd: Optional[float]
    valuation_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    full_name: str
    email: str
    qualification_status: str
    qualified_budget_usd: Optional[float]
    proof_of_funds_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComparableSale(TypedDict):
    id: str
    make: str
    model: str
    year: int
    sale_price_usd: float
    sale_date: str
    total_time_hours: int
    comp_status: str
    source_listing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LOI(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    offer_price_usd: float
    current_price_usd: float
    deposit_amount_usd: float
    dual_agency: bool
    disclosure_status: str
    buyer_acked: bool
    seller_acked: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    loi_id: str
    listing_id: str
    buyer_id: str
    agreed_price_usd: float
    dual_agency: bool
    status: str
    logbook_complete: bool
    registration_docs_complete: bool
    tax_planning_notes: Optional[str]
    credits_total_usd: float
    commission_amount_usd: Optional[float]
    settlement_buyer_due_usd: Optional[float]
    settlement_seller_net_usd: Optional[float]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscrowDeposit(TypedDict):
    id: str
    transaction_id: str
    escrow_ref: str
    deposit_amount_usd: float
    status: str
    funding_reference: Optional[str]
    released_usd: float
    refunded_usd: float
    forfeited_usd: float
    created_at: str
    updated_at: str
    version: int


class InspectionBooking(TypedDict):
    id: str
    transaction_id: str
    facility_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DiscrepancyItem(TypedDict):
    id: str
    transaction_id: str
    inspection_booking_id: str
    description: str
    severity: str
    estimated_cost_usd: float
    proposed_credit_usd: Optional[float]
    credit_amount_usd: Optional[float]
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
