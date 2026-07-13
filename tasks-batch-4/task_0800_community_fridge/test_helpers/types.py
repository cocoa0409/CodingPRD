"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted resource in the Community Fridge API carries the common
system-managed fields id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    STEWARD = "Steward"
    DONOR_AGENT = "DonorAgent"
    SPONSOR_AGENT = "SponsorAgent"
    MEMBER = "Member"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class FridgeSafetyPosture(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    RESTRICTED = "RESTRICTED"
    QUARANTINED = "QUARANTINED"


class StewardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DonorType(str, Enum):
    RESTAURANT = "RESTAURANT"
    GROCER = "GROCER"
    INDIVIDUAL = "INDIVIDUAL"


class SponsorGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class StewardShiftKind(str, Enum):
    COVERAGE = "COVERAGE"
    CLEANING = "CLEANING"


class StewardShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class SurplusOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"


class FoodCategory(str, Enum):
    PRODUCE = "PRODUCE"
    BAKERY = "BAKERY"
    DAIRY = "DAIRY"
    PREPARED = "PREPARED"
    PACKAGED = "PACKAGED"


class StorageType(str, Enum):
    COLD_CHAIN = "COLD_CHAIN"
    AMBIENT = "AMBIENT"


class DonationBatchStatus(str, Enum):
    STOCKED = "STOCKED"
    HELD = "HELD"
    RECALLED = "RECALLED"
    EXPIRED = "EXPIRED"
    DISCARDED = "DISCARDED"
    CLAIMED_OUT = "CLAIMED_OUT"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class NeedPostingStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


# --------------------------------------------------------------------------
# Entity TypedDicts — all nine resources carry the four common fields (§2.4)
# --------------------------------------------------------------------------
class Fridge(TypedDict):
    id: str
    name: str
    location_label: str
    capacity_slots: int
    current_temp_c: float
    last_cleaned_at: str
    ops_run_index: int
    active_recall_count: int
    stock_slots_used: int
    free_slots: int
    safety_posture: str
    budget_granted_cents: int
    budget_committed_cents: int
    budget_available_cents: int
    total_meals_provided: int
    created_at: str
    updated_at: str
    version: int


class Steward(TypedDict):
    id: str
    name: str
    email: str
    status: str
    missed_count: int
    completed_count: int
    reliability_actual: float
    reliability_projected: float
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict):
    id: str
    name: str
    donor_type: str
    contact: str
    created_at: str
    updated_at: str
    version: int


class SponsorGrant(TypedDict):
    id: str
    fridge_id: str
    sponsor_name: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StewardShift(TypedDict):
    id: str
    fridge_id: str
    steward_id: str
    kind: str
    start_at: str
    end_at: str
    status: str
    miles_traveled: float
    handled_cold_chain: bool
    reimbursement_amount_cents: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurplusOffer(TypedDict):
    id: str
    donor_id: str
    fridge_id: str
    description: str
    estimated_quantity_kg: float
    pickup_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationBatch(TypedDict):
    id: str
    fridge_id: str
    steward_id: str
    surplus_offer_id: Optional[str]
    food_category: str
    storage_type: str
    declared_quantity_kg: float
    slot_footprint: int
    intake_temp_c: float
    use_by: str
    allergens: List[str]
    status: str
    available_quantity_kg: float
    realized_quantity_kg: float
    provisional_meals: int
    realized_meals: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    donation_batch_id: str
    fridge_id: str
    quantity_kg: float
    recipient_label: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NeedPosting(TypedDict):
    id: str
    fridge_id: str
    item_description: str
    quantity_needed: int
    needed_by: str
    status: str
    created_at: str
    updated_at: str
    version: int
