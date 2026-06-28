"""Domain types: entity TypedDicts, status enums, role enum (Flood Insurance API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    POLICY_HOLDER = "PolicyHolder"
    UNDERWRITER = "Underwriter"
    ADJUSTER = "Adjuster"
    FEMA_ADMIN = "FemaAdmin"


# --- Status enums ---
class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    TRANSFERRED = "TRANSFERRED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ProofOfLossReviewStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class FloodZone(str, Enum):
    VE = "VE"
    AE = "AE"
    X = "X"


class Occupancy(str, Enum):
    PRIMARY_RESIDENCE = "PRIMARY_RESIDENCE"
    NON_PRIMARY = "NON_PRIMARY"


class RatingMethod(str, Enum):
    RISK_RATING_2_0 = "RISK_RATING_2_0"
    LEGACY_SUBSIDIZED = "LEGACY_SUBSIDIZED"


class ComplianceStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    COMPLIANT = "COMPLIANT"
    LAPSED = "LAPSED"


# --- Entity TypedDicts ---
# Community: common_fields true -> id, created_at, updated_at, version
class Community(TypedDict):
    id: str
    name: str
    county_code: str
    participating: bool
    crs_class: int
    crs_discount_pct: float
    created_at: str
    updated_at: str
    version: int


# Property: common_fields true
class Property(TypedDict):
    id: str
    community_id: str
    owner_id: str
    address: str
    flood_zone: str
    is_sfha: bool
    occupancy: str
    base_flood_elevation_ft: float
    has_active_mortgage: bool
    loss_history_count: int
    is_repetitive_loss: bool
    compliance_status: str
    active_policy_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ElevationCertificate: common_fields FALSE -> immutable evidence; only id + created_at
class ElevationCertificate(TypedDict):
    id: str
    property_id: str
    surveyor_license: str
    lowest_floor_elevation_ft: float
    freeboard_ft: float
    superseded: bool
    created_at: str


# Policy: common_fields true
class Policy(TypedDict):
    id: str
    property_id: str
    holder_id: str
    rating_method: str
    building_coverage: float
    contents_coverage: float
    building_deductible: float
    contents_deductible: float
    is_lender_required: bool
    status: str
    quoted_premium: float
    bind_date: Optional[str]
    effective_date: Optional[str]
    expiration_date: Optional[str]
    earned_premium: float
    premium_credit_balance: float
    total_claims_paid: float
    created_at: str
    updated_at: str
    version: int


# Claim: common_fields true
class Claim(TypedDict):
    id: str
    policy_id: str
    claimant_id: str
    date_of_loss: str
    building_loss: float
    contents_loss: float
    depreciation_pct: float
    substantial_damage: bool
    icc_eligible_cost: float
    status: str
    settlement_total: float
    building_payable: float
    contents_payable: float
    icc_payable: float
    created_at: str
    updated_at: str
    version: int


# ProofOfLoss: common_fields true
class ProofOfLoss(TypedDict):
    id: str
    claim_id: str
    documented_building_loss: float
    documented_contents_loss: float
    filed_at: str
    days_after_loss: int
    review_status: str
    created_at: str
    updated_at: str
    version: int


# PolicyTransfer: common_fields true
class PolicyTransfer(TypedDict):
    id: str
    from_policy_id: str
    new_owner_id: str
    superseded_policy_id: Optional[str]
    credited_amount: float
    effective_at: str
    created_at: str
    updated_at: str
    version: int
