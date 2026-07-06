"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    RIGHT_OF_WAY_AGENT = "RightOfWayAgent"
    APPRAISER = "Appraiser"
    PROPERTY_OWNER = "PropertyOwner"
    ESCROW_OFFICER = "EscrowOfficer"
    UTILITY_COORDINATOR = "UtilityCoordinator"


class ParcelResearchStatus(str, Enum):
    RESEARCHING = "RESEARCHING"
    OWNERSHIP_CLEARED = "OWNERSHIP_CLEARED"


class ParcelAcquisitionStatus(str, Enum):
    PENDING = "PENDING"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    AGREED = "AGREED"
    IN_CONDEMNATION = "IN_CONDEMNATION"
    POSSESSED = "POSSESSED"
    ACQUIRED = "ACQUIRED"


class TakeType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class InterestType(str, Enum):
    FEE_OWNER = "FEE_OWNER"
    LIENHOLDER = "LIENHOLDER"
    TENANT = "TENANT"
    EASEMENT_HOLDER = "EASEMENT_HOLDER"


class AppraisalStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class NegotiationStatus(str, Enum):
    AGENCY_OFFERED = "AGENCY_OFFERED"
    OWNER_COUNTERED = "OWNER_COUNTERED"
    AGREED = "AGREED"
    IMPASSE = "IMPASSE"


class OfferParty(str, Enum):
    AGENCY = "AGENCY"
    OWNER = "OWNER"


class OfferAction(str, Enum):
    OFFER = "OFFER"
    COUNTER = "COUNTER"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class OccupantType(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    BUSINESS = "BUSINESS"


class RelocationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class CondemnationStatus(str, Enum):
    FILED = "FILED"
    DEPOSIT_MADE = "DEPOSIT_MADE"
    POSSESSED = "POSSESSED"
    AWARDED = "AWARDED"


class UtilityType(str, Enum):
    WATER = "WATER"
    GAS = "GAS"
    ELECTRIC = "ELECTRIC"
    TELECOM = "TELECOM"
    SEWER = "SEWER"


class UtilityStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    SCHEDULED = "SCHEDULED"
    RELOCATED = "RELOCATED"


class EscrowSource(str, Enum):
    NEGOTIATED = "NEGOTIATED"
    CONDEMNATION = "CONDEMNATION"


class EscrowStatus(str, Enum):
    OPENED = "OPENED"
    FUNDED = "FUNDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# ---- Full entities (id + created_at + updated_at + version) ---------------

class Project(TypedDict):
    id: str
    name: str
    agency_name: str
    total_budget_cents: int
    committed_cents: int
    disbursed_cents: int
    acquired_area_sqft: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    project_id: str
    apn: str
    total_area_sqft: int
    take_area_sqft: int
    take_type: str
    research_status: str
    acquisition_status: str
    appraised_value_cents: int
    created_at: str
    updated_at: str
    version: int


class OwnershipInterest(TypedDict):
    id: str
    parcel_id: str
    interest_type: str
    holder_name: str
    ownership_pct: float
    lien_priority: int
    lien_balance_cents: int
    is_occupant: bool
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    parcel_id: str
    appraiser_name: str
    land_value_cents: int
    improvements_value_cents: int
    severance_damages_cents: int
    special_benefits_cents: int
    just_compensation_cents: int
    condemnation_basis_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionAppointment(TypedDict):
    id: str
    appraisal_id: str
    appraiser_name: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Negotiation(TypedDict):
    id: str
    parcel_id: str
    status: str
    initial_offer_cents: int
    current_amount_cents: int
    round_count: int
    agreed_amount_cents: int
    prompt_bonus_cents: int
    settlement_total_cents: int
    created_at: str
    updated_at: str
    version: int


class RelocationBenefit(TypedDict):
    id: str
    parcel_id: str
    claimant_name: str
    occupant_type: str
    comparable_replacement_cost_cents: int
    acquired_dwelling_price_cents: int
    moving_expense_cents: int
    reestablishment_cost_cents: int
    benefit_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Condemnation(TypedDict):
    id: str
    parcel_id: str
    just_compensation_snapshot_cents: int
    deposit_amount_cents: int
    final_award_cents: int
    statutory_interest_cents: int
    settlement_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityRelocation(TypedDict):
    id: str
    parcel_id: str
    utility_type: str
    crew_name: str
    possession_cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Escrow(TypedDict):
    id: str
    parcel_id: str
    source: str
    agreed_amount_cents: int
    funded_amount_cents: int
    disbursed_total_cents: int
    disbursements: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---- Append-only event entity (id + created_at only) ----------------------

class OfferRound(TypedDict):
    id: str
    negotiation_id: str
    round_no: int
    party: str
    action: str
    amount_cents: int
    created_at: str
