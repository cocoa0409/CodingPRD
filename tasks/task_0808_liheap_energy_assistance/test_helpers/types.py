"""Domain types: entity TypedDicts, status enums, role enum for the LIHEAP API."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum -------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    CASEWORKER = "Caseworker"
    VENDOR_AGENT = "VendorAgent"
    PROGRAM_ADMIN = "ProgramAdmin"


# --- Status / classification enums -----------------------------------------
class FundingPoolStatus(str, Enum):
    OPEN = "OPEN"
    LOW = "LOW"
    DEPLETED = "DEPLETED"
    CLOSED = "CLOSED"


class ProgramComponent(str, Enum):
    HEATING = "HEATING"
    COOLING = "COOLING"
    CRISIS = "CRISIS"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class BenefitTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    INELIGIBLE = "INELIGIBLE"


class BenefitVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class IncomeDocumentStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VendorStatus(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"


class PledgeStatus(str, Enum):
    PLEDGED = "PLEDGED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PledgeType(str, Enum):
    HEATING = "HEATING"
    COOLING = "COOLING"
    CRISIS = "CRISIS"
    RECONNECTION = "RECONNECTION"
    ARREARAGE = "ARREARAGE"


class CrisisBenefitStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    BREACHED = "BREACHED"


class CrisisType(str, Enum):
    NO_HEAT = "NO_HEAT"
    DISCONNECTION_NOTICE = "DISCONNECTION_NOTICE"
    OUT_OF_FUEL = "OUT_OF_FUEL"


class PaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    REMITTED = "REMITTED"
    RETURNED = "RETURNED"


class BillCreditStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    SCHEDULED = "SCHEDULED"


class ReferralPriority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReferralReason(str, Enum):
    HIGH_ENERGY_BURDEN = "HIGH_ENERGY_BURDEN"
    TIER_1_AUTO = "TIER_1_AUTO"
    VENDOR_REPORTED = "VENDOR_REPORTED"


# --- Entity TypedDicts (all entities carry id/created_at/updated_at/version) -
class FundingPool(TypedDict):
    id: str
    season_year: int
    program_component: str
    total_allocation_cents: int
    reserved_cents: int
    disbursed_cents: int
    available_cents: int
    depletion_threshold_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    primary_applicant_name: str
    household_size: int
    annual_income_cents: int
    state_code: str
    county: str
    has_elderly_or_disabled: bool
    has_child_under_6: bool
    heating_source: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    household_id: str
    season_year: int
    program_component: str
    fpl_pct: float
    income_eligible: bool
    benefit_tier: str
    benefit_amount_cents: int
    benefit_variant: str
    status: str
    submitted_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeDocument(TypedDict):
    id: str
    application_id: str
    doc_type: str
    reported_income_cents: int
    verified_income_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    vendor_type: str
    remittance_account: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityAccount(TypedDict):
    id: str
    household_id: str
    vendor_id: str
    account_number: str
    service_type: str
    current_balance_cents: int
    arrearage_cents: int
    lifetime_credited_cents: int
    is_disconnected: bool
    reconnection_eligible: bool
    original_obligation_cents: int
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict):
    id: str
    application_id: Optional[str]
    vendor_id: str
    funding_pool_id: str
    utility_account_id: str
    pledge_type: str
    pledged_amount_cents: int
    benefit_period_start: str
    benefit_period_end: str
    expected_pool_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrisisBenefit(TypedDict):
    id: str
    household_id: str
    utility_account_id: str
    funding_pool_id: str
    crisis_type: str
    reported_at: str
    resolve_by: str
    estimated_benefit_cents: int
    resolved_benefit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    pledge_id: str
    amount_cents: int
    status: str
    remitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillCredit(TypedDict):
    id: str
    payment_id: str
    utility_account_id: str
    credit_amount_cents: int
    applied_to_arrearage_cents: int
    applied_to_current_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherizationReferral(TypedDict):
    id: str
    household_id: str
    application_id: Optional[str]
    referral_reason: str
    priority: str
    status: str
    created_at: str
    updated_at: str
    version: int
