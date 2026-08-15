"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the common properties of PRD §2.4 (id, created_at,
updated_at, version) — there are no append-only exceptions in this system.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    DEVELOPER_OPERATOR = "DeveloperOperator"
    BUILDER_REP = "BuilderRep"
    LENDER_OFFICER = "LenderOfficer"
    MUNICIPAL_CLERK = "MunicipalClerk"
    HOA_MANAGER = "HOAManager"


class AbsorptionMethod(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    TRAILING_WEIGHTED = "TRAILING_WEIGHTED"


class ParcelStatus(str, Enum):
    DRAFT = "DRAFT"
    CONTINGENCY_ACTIVE = "CONTINGENCY_ACTIVE"
    ACQUIRED = "ACQUIRED"
    TERMINATED = "TERMINATED"
    SOLD_OUT = "SOLD_OUT"


class PhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    PLAT_SUBMITTED = "PLAT_SUBMITTED"
    PLAT_REJECTED = "PLAT_REJECTED"
    PLAT_APPROVED = "PLAT_APPROVED"
    PLAT_RECORDED = "PLAT_RECORDED"
    ACTIVE = "ACTIVE"
    SELLOUT = "SELLOUT"


class LotType(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ESTATE = "ESTATE"


class BondStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    BID_FINAL = "BID_FINAL"
    POSTED = "POSTED"
    PARTIALLY_REDUCED = "PARTIALLY_REDUCED"
    WORK_ACCEPTED = "WORK_ACCEPTED"
    RELEASED = "RELEASED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class LotSalesStatus(str, Enum):
    PLATTED = "PLATTED"
    RESERVED = "RESERVED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"


class LotLienStatus(str, Enum):
    ENCUMBERED = "ENCUMBERED"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"


class ClosingStatus(str, Enum):
    PENDING = "PENDING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LoanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"


class DrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FUNDED = "FUNDED"
    REVERSED = "REVERSED"


class HOAStatus(str, Enum):
    FORMATION_PENDING = "FORMATION_PENDING"
    DECLARANT_CONTROL = "DECLARANT_CONTROL"
    TRANSITIONING = "TRANSITIONING"
    HOMEOWNER_CONTROL = "HOMEOWNER_CONTROL"


class UtilityType(str, Enum):
    WATER = "WATER"
    SEWER = "SEWER"
    ELECTRIC = "ELECTRIC"


class ConnectionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    CONNECTED = "CONNECTED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry the §2.4 common properties)
# ---------------------------------------------------------------------------

class Parcel(TypedDict, total=False):
    id: str
    parcel_name: str
    county: str
    earnest_money_cents: int
    planned_sellout_months: int
    absorption_method: str
    status: str
    contingency_end_date: Optional[str]
    acquisition_close_date: Optional[str]
    earnest_money_refunded: bool
    total_lots_planned: int
    lots_closed_count: int
    lots_available_count: int
    closed_pct: float
    straight_line_pace_pm: float
    trailing_weighted_pace_pm: float
    selected_pace_pm: float
    projected_months_to_sellout: Optional[float]
    next_phase_release_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Phase(TypedDict, total=False):
    id: str
    parcel_id: str
    phase_name: str
    sequence_number: int
    planned_lot_count: int
    selling_window_start: str
    selling_window_end: str
    plat_lot_count: int
    lot_type: str
    plat_revision: int
    plat_rejection_reason: Optional[str]
    recorded_at: Optional[str]
    recorded_lot_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InfrastructureBond(TypedDict, total=False):
    id: str
    phase_id: str
    engineer_estimate_cents: int
    awarded_bid_cents: Optional[int]
    required_bond_cents: int
    posted_bond_cents: int
    work_accepted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Builder(TypedDict, total=False):
    id: str
    builder_name: str
    license_number: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class TakedownAgreement(TypedDict, total=False):
    id: str
    parcel_id: str
    builder_id: str
    effective_date: str
    base_lot_price_cents: int
    escalator_rate_bp_per_quarter: int
    price_cap_bp: int
    min_lots_per_quarter: int
    scheduled_lot_count: int
    closed_lot_count: int
    default_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    phase_id: str
    lot_number: int
    lot_type: str
    sales_status: str
    lien_status: str
    reserved_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotClosing(TypedDict, total=False):
    id: str
    lot_id: str
    agreement_id: str
    loan_id: str
    contract_price_cents: int
    release_price_cents: int
    payment_applied_cents: int
    finalized_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DevelopmentLoan(TypedDict, total=False):
    id: str
    parcel_id: str
    commitment_amount_cents: int
    release_price_floor_bp: int
    outstanding_balance_cents: int
    total_drawn_cents: int
    total_release_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DrawLineItem(TypedDict):
    description: str
    amount_cents: int


class LoanDraw(TypedDict, total=False):
    id: str
    loan_id: str
    requested_by_user_id: str
    line_items: List[DrawLineItem]
    gross_amount_cents: int
    retainage_cents: int
    draw_fee_cents: int
    net_disbursed_cents: int
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HOAAssociation(TypedDict, total=False):
    id: str
    parcel_id: str
    hoa_name: str
    control_transfer_pct_bp: int
    statutory_control_end: str
    board_seated_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityProvider(TypedDict, total=False):
    id: str
    provider_name: str
    utility_type: str
    max_connections_per_day: int
    created_at: str
    updated_at: str
    version: int


class UtilityConnection(TypedDict, total=False):
    id: str
    lot_id: str
    provider_id: str
    scheduled_date: str
    impact_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
