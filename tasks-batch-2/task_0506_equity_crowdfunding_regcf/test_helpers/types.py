"""Domain types: entity TypedDicts, status enums, role enum for the Equity Crowdfunding (Reg CF) Portal API."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    ISSUER = "Issuer"
    INVESTOR = "Investor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums (PRD §3) ---
class IssuerStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    VERIFIED = "VERIFIED"
    BARRED = "BARRED"


class EntityType(str, Enum):
    C_CORP = "C_CORP"
    LLC = "LLC"
    BENEFIT_CORP = "BENEFIT_CORP"


class Regulation(str, Enum):
    REG_CF = "REG_CF"
    REG_A_TIER_1 = "REG_A_TIER_1"
    REG_A_TIER_2 = "REG_A_TIER_2"


class SecurityType(str, Enum):
    EQUITY = "EQUITY"
    SAFE = "SAFE"


class FormCStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    FUNDED = "FUNDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AccreditationStatus(str, Enum):
    UNACCREDITED = "UNACCREDITED"
    ACCREDITED = "ACCREDITED"


class AccreditationMethod(str, Enum):
    INCOME = "INCOME"
    NET_WORTH = "NET_WORTH"
    THIRD_PARTY_LETTER = "THIRD_PARTY_LETTER"


class AccreditationRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class InvestmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    RECONFIRMED = "RECONFIRMED"
    ISSUED = "ISSUED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class Instrument(str, Enum):
    EQUITY = "EQUITY"
    SAFE = "SAFE"


class InvestorUpdateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


# --- Entity TypedDicts ---

# common_fields: true -> id + created_at + updated_at + version
class Issuer(TypedDict):
    id: str
    legal_name: str
    ein: str
    home_state_code: str
    entity_type: str
    bad_actor_flag: bool
    status: str
    total_raised_trailing_12mo_cents: int
    created_at: str
    updated_at: str
    version: int


class Offering(TypedDict):
    id: str
    issuer_id: str
    regulation: str
    security_type: str
    price_per_security_cents: Optional[int]
    min_target_cents: int
    max_target_cents: int
    per_investor_cap_cents: Optional[int]
    deadline_at: str
    live_at: Optional[str]
    form_c_status: str
    status: str
    committed_amount_cents: int
    swept_amount_cents: int
    secondary_listing_enabled: bool
    close_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict):
    id: str
    email: str
    legal_name: str
    annual_income_cents: int
    net_worth_cents: int
    accreditation_status: str
    annual_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class AccreditationRequest(TypedDict):
    id: str
    investor_id: str
    method: str
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investment(TypedDict):
    id: str
    offering_id: str
    investor_id: str
    amount_cents: int
    expected_offering_version: int
    status: str
    securities_issued: int
    refund_amount_cents: int
    reconfirm_required: bool
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict):
    id: str
    offering_id: str
    held_amount_cents: int
    disbursed_amount_cents: int
    refunded_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class InvestorUpdate(TypedDict):
    id: str
    offering_id: str
    title: str
    body: str
    supersedes_update_id: Optional[str]
    published_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> only id + created_at (no updated_at, no version)
class CapTableEntry(TypedDict):
    id: str
    offering_id: str
    investor_id: str
    investment_id: str
    instrument: str
    quantity: Optional[int]
    principal_cents: int
    created_at: str
