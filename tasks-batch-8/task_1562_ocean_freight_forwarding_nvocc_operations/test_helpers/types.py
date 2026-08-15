"""Domain types: entity shapes, status enums, role enum.

Every resource carries the common system-managed fields from PRD §2.4:
id, created_at, updated_at, version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SHIPPER = "Shipper"
    BOOKING_COORDINATOR = "BookingCoordinator"
    DOCUMENTATION_OFFICER = "DocumentationOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_CONTROLLER = "FinanceController"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    OPERATIONS_MANAGER = "OperationsManager"


class ShipperStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TariffStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ContractStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class BondStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class VoyageStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BOOKING_OPEN = "BOOKING_OPEN"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    CLOSED = "CLOSED"
    BLANKED = "BLANKED"


class BookingStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    DOCUMENTATION_CLEARED = "DOCUMENTATION_CLEARED"
    LOADED = "LOADED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    ROLLED = "ROLLED"
    CANCELLED = "CANCELLED"


class ConsolidationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    TENDERED = "TENDERED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    STUFFED = "STUFFED"
    GATED_IN = "GATED_IN"
    LOADED = "LOADED"
    DISCHARGED = "DISCHARGED"
    GATED_OUT = "GATED_OUT"
    EMPTY_RETURNED = "EMPTY_RETURNED"
    CANCELLED = "CANCELLED"


class BlStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    SURRENDERED = "SURRENDERED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class FilingStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PenaltyStatus(str, Enum):
    NONE = "NONE"
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class CommodityType(str, Enum):
    GENERAL = "GENERAL"
    REEFER = "REEFER"
    HAZMAT = "HAZMAT"


class Mode(str, Enum):
    FCL = "FCL"
    LCL = "LCL"


class ContainerType(str, Enum):
    C20GP = "20GP"
    C40GP = "40GP"
    C40HC = "40HC"
    C40RF = "40RF"


class RateSource(str, Enum):
    CONTRACT = "CONTRACT"
    SPOT = "SPOT"


class Terms(str, Enum):
    PREPAID = "PREPAID"
    COLLECT = "COLLECT"


class CreditTerms(str, Enum):
    PREPAID_ONLY = "PREPAID_ONLY"
    NET_7 = "NET_7"
    NET_30 = "NET_30"


class FilingType(str, Enum):
    ISF = "ISF"
    AMS = "AMS"


class InvoiceType(str, Enum):
    FREIGHT = "FREIGHT"
    DEMURRAGE_DETENTION = "DEMURRAGE_DETENTION"
    CANCELLATION = "CANCELLATION"


class BlType(str, Enum):
    HOUSE = "HOUSE"
    MASTER = "MASTER"


class ReleaseMode(str, Enum):
    ORIGINAL = "ORIGINAL"
    SEAWAY = "SEAWAY"
    TELEX = "TELEX"


class CoverageType(str, Enum):
    ALL_RISK = "ALL_RISK"
    WA = "WA"
    FPA = "FPA"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"
    SHORTAGE = "SHORTAGE"
    DELAY = "DELAY"


class RolledReason(str, Enum):
    SHIPPER_REQUEST = "SHIPPER_REQUEST"
    BLANK_SAILING = "BLANK_SAILING"
    MISSED_DEPARTURE = "MISSED_DEPARTURE"


class InvoiceLine(TypedDict, total=False):
    line_type: str
    description: str
    quantity: float
    unit_rate_cents: int
    amount_cents: int


class Shipper(TypedDict, total=False):
    id: str
    legal_name: str
    credit_limit_cents: int
    credit_terms: str
    credit_exposure_posted_cents: int
    credit_exposure_forward_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Tariff(TypedDict, total=False):
    id: str
    tariff_code: str
    origin_port: str
    destination_port: str
    commodity_type: str
    mode: str
    container_type: Optional[str]
    rate_per_unit_cents: int
    minimum_charge_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_by_user_id: str
    published_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CarrierContract(TypedDict, total=False):
    id: str
    contract_number: str
    carrier_name: str
    service_lane: str
    container_rates: List[dict]
    demurrage_free_days: int
    detention_free_days: int
    demurrage_tiers: List[dict]
    detention_per_diem_cents: int
    service_start: str
    service_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SuretyBond(TypedDict, total=False):
    id: str
    bond_number: str
    surety_company: str
    coverage_amount_cents: int
    available_coverage_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Voyage(TypedDict, total=False):
    id: str
    vessel_name: str
    voyage_number: str
    carrier_contract_id: str
    origin_port: str
    destination_port: str
    etd: str
    eta: str
    isf_deadline: str
    ams_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    booking_number: str
    shipper_id: str
    voyage_id: str
    tariff_id: str
    rate_source: str
    spot_rate_per_unit_cents: Optional[int]
    mode: str
    container_type: Optional[str]
    container_count: Optional[int]
    commodity_type: str
    gross_weight_kg: float
    volume_cbm: float
    terms: str
    chargeable_weight_rt: float
    estimated_freight_cents: int
    rollover_count: int
    rolled_reason: Optional[str]
    pending_rollover_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Consolidation(TypedDict, total=False):
    id: str
    consolidation_number: str
    voyage_id: str
    cfs_location: str
    container_type: str
    max_weight_kg: float
    max_volume_cbm: float
    used_weight_kg: float
    used_volume_cbm: float
    stuffing_window_start: str
    stuffing_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContainerAssignment(TypedDict, total=False):
    id: str
    booking_id: str
    consolidation_id: Optional[str]
    assignment_mode: str
    container_number: str
    seal_number: Optional[str]
    stuffed_weight_kg: float
    stuffed_volume_cbm: float
    stuffed_at: str
    gated_in_at: Optional[str]
    discharged_at: Optional[str]
    gated_out_at: Optional[str]
    empty_returned_at: Optional[str]
    demurrage_days: int
    detention_days: int
    provisional_demurrage_cents: int
    provisional_detention_cents: int
    demurrage_charge_cents: int
    detention_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BillOfLading(TypedDict, total=False):
    id: str
    booking_id: str
    bl_number: str
    bl_type: str
    release_mode: str
    issued_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    amendment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceFiling(TypedDict, total=False):
    id: str
    booking_id: str
    filing_type: str
    deadline_at: str
    submitted_at: Optional[str]
    is_late: bool
    penalty_status: str
    penalty_amount_cents: int
    filed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    booking_id: str
    invoice_number: str
    invoice_type: str
    lines: List[InvoiceLine]
    total_cents: int
    paid_cents: int
    balance_cents: int
    issued_at: Optional[str]
    due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CargoInsurancePolicy(TypedDict, total=False):
    id: str
    booking_id: str
    policy_number: str
    coverage_type: str
    cargo_value_cents: int
    insured_value_cents: int
    freight_base_cents: int
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CargoClaim(TypedDict, total=False):
    id: str
    policy_id: str
    booking_id: str
    claim_number: str
    claim_type: str
    claimed_amount_cents: int
    description: Optional[str]
    deductible_cents: int
    settlement_amount_cents: int
    reviewed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    settled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
