"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD's Rent Board & Rent-Stabilization contract exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    LANDLORD = "Landlord"
    TENANT = "Tenant"
    HEARING_OFFICER = "HearingOfficer"
    RENT_BOARD_CLERK = "RentBoardClerk"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --------------------------------------------------------------------------
# Status / enum value sets
# --------------------------------------------------------------------------
class UnitStabilizationStatus(str, Enum):
    STABILIZED = "STABILIZED"
    EXEMPT = "EXEMPT"
    DECONTROLLED = "DECONTROLLED"


class RegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class TenancyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class PetitionType(str, Enum):
    CAPITAL_IMPROVEMENT = "CAPITAL_IMPROVEMENT"
    HARDSHIP = "HARDSHIP"


class PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    GRANTED = "GRANTED"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"


class HearingDecision(str, Enum):
    GRANT = "GRANT"
    PARTIAL = "PARTIAL"
    DENY = "DENY"


class ClaimType(str, Enum):
    HEAT = "HEAT"
    WATER = "WATER"
    MAINTENANCE = "MAINTENANCE"
    PEST = "PEST"


class Severity(str, Enum):
    MINOR = "MINOR"
    SUBSTANTIAL = "SUBSTANTIAL"


class ServiceClaimStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"
    RESTORED = "RESTORED"


class BuyoutStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    RESCINDED = "RESCINDED"
    COMPLETED = "COMPLETED"


class ExemptionType(str, Enum):
    SUBSTANTIAL_REHAB = "SUBSTANTIAL_REHAB"
    OWNER_OCCUPIED = "OWNER_OCCUPIED"
    VACANCY_DECONTROL = "VACANCY_DECONTROL"
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"


class ExemptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PenaltyType(str, Enum):
    OVERCHARGE = "OVERCHARGE"
    LATE_REGISTRATION = "LATE_REGISTRATION"
    FAILURE_TO_FILE = "FAILURE_TO_FILE"


class PenaltyStatus(str, Enum):
    ASSESSED = "ASSESSED"
    CONFIRMED = "CONFIRMED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id, created_at, updated_at, version
# common_fields: false -> id, created_at only  (AGADetermination)
# --------------------------------------------------------------------------
class Landlord(TypedDict):
    id: str
    name: str
    email: str
    business_license_no: str
    escrow_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    name: str
    email: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class HearingOfficer(TypedDict):
    id: str
    name: str
    email: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    landlord_id: str
    address: str
    bedrooms: int
    base_rent_cents: int
    current_lawful_rent_cents: int
    banked_pct: float
    stabilization_status: str
    decrease_active: bool
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    unit_id: str
    registration_year: int
    declared_rent_cents: int
    status: str
    filed_by: str
    created_at: str
    updated_at: str
    version: int


class Tenancy(TypedDict):
    id: str
    unit_id: str
    tenant_id: str
    start_date: str
    end_date: Optional[str]
    monthly_rent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# AGADetermination: common_fields false -> only id + created_at (immutable)
class AGADetermination(TypedDict):
    id: str
    effective_year: int
    cpi_pct: float
    aga_pct: float
    effective_from: str
    effective_to: str
    created_at: str


class Petition(TypedDict):
    id: str
    unit_id: str
    landlord_id: str
    petition_type: str
    requested_cost_cents: Optional[int]
    amortization_months: Optional[int]
    requested_pct: Optional[float]
    status: str
    granted_amount_cents: int
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    petition_id: str
    officer_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    decision: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceClaim(TypedDict):
    id: str
    unit_id: str
    tenant_id: str
    claim_type: str
    severity: str
    status: str
    ordered_decrease_pct: Optional[float]
    decrease_amount_cents: int
    pre_decrease_rent_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Buyout(TypedDict):
    id: str
    unit_id: str
    landlord_id: str
    tenant_id: str
    offer_amount_cents: int
    relocation_amount_cents: int
    disclosure_acknowledged: bool
    status: str
    filed_at: Optional[str]
    rescind_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Exemption(TypedDict):
    id: str
    unit_id: str
    exemption_type: str
    status: str
    effective_date: Optional[str]
    vacancy_rent_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Penalty(TypedDict):
    id: str
    unit_id: str
    landlord_id: str
    penalty_type: str
    months_overcharged: Optional[int]
    monthly_overcharge_cents: Optional[int]
    willful: bool
    assessed_amount_cents: int
    status: str
    assessed_by: str
    confirmed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
