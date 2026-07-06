"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CASEWORKER = "Caseworker"
    PROVIDER_STAFF = "ProviderStaff"
    CLIENT = "Client"
    FUNDER_REPORTER = "FunderReporter"


class ReportingCurrency(str, Enum):
    USD = "USD"
    CAD = "CAD"
    EUR = "EUR"


class ProgramCategory(str, Enum):
    FOOD = "FOOD"
    HOUSING = "HOUSING"
    HEALTHCARE = "HEALTHCARE"
    MENTAL_HEALTH = "MENTAL_HEALTH"
    EMPLOYMENT = "EMPLOYMENT"
    TRANSPORT = "TRANSPORT"
    LEGAL_AID = "LEGAL_AID"
    CHILDCARE = "CHILDCARE"


class AccessibilityFeature(str, Enum):
    WHEELCHAIR = "WHEELCHAIR"
    HEARING_LOOP = "HEARING_LOOP"
    ASL_INTERPRETER = "ASL_INTERPRETER"
    LARGE_PRINT = "LARGE_PRINT"


class Language(str, Enum):
    EN = "EN"
    ES = "ES"
    FR = "FR"
    ZH = "ZH"
    VI = "VI"
    AR = "AR"


class Urgency(str, Enum):
    ROUTINE = "ROUTINE"
    PRIORITY = "PRIORITY"
    EMERGENCY = "EMERGENCY"


class TransportMode(str, Enum):
    PUBLIC_TRANSIT = "PUBLIC_TRANSIT"
    CAR = "CAR"
    WALKING = "WALKING"
    AGENCY_SHUTTLE = "AGENCY_SHUTTLE"


class TransportPlanMode(str, Enum):
    AGENCY_SHUTTLE = "AGENCY_SHUTTLE"
    RIDESHARE_VOUCHER = "RIDESHARE_VOUCHER"


class ConsentScope(str, Enum):
    BASIC_CONTACT = "BASIC_CONTACT"
    FULL_CASE_FILE = "FULL_CASE_FILE"
    HEALTHCARE_HIPAA = "HEALTHCARE_HIPAA"


class IntakeStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENED = "SCREENED"
    CLOSED = "CLOSED"


class ConsentGrantStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ReferralStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SERVICE_IN_PROGRESS = "SERVICE_IN_PROGRESS"
    COMPLETED_SUCCESS = "COMPLETED_SUCCESS"
    COMPLETED_UNSUCCESSFUL = "COMPLETED_UNSUCCESSFUL"
    WITHDRAWN = "WITHDRAWN"


class TransportPlanStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class OutcomeReportStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"


class OutcomeClass(str, Enum):
    SUCCESS = "SUCCESS"
    UNSUCCESSFUL = "UNSUCCESSFUL"


class Outcome(str, Enum):
    FULLY_MET = "FULLY_MET"
    PARTIALLY_MET = "PARTIALLY_MET"
    UNMET = "UNMET"


class ProgramIntakePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class ProgramFunderReportingPosture(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# Entity TypedDicts. common_fields: true -> id, created_at, updated_at, version.
# common_fields: false -> id, created_at only (FunderReport only).
# ---------------------------------------------------------------------------


class Funder(TypedDict):
    id: str
    name: str
    fiscal_year_start_month: int
    grant_cents_total: int
    grant_cents_remaining: int
    reporting_currency: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    legal_name: str
    location_lat: float
    location_lng: float
    accessibility_features: List[str]
    languages_supported: List[str]
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    provider_id: str
    funder_id: str
    category: str
    eligibility_income_max_cents: int
    eligibility_age_min: int
    eligibility_age_max: int
    unit_cost_cents: int
    capacity_slots_total: int
    capacity_slots_taken: int
    intake_posture: str
    funder_reporting_posture: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityWindow(TypedDict):
    id: str
    program_id: str
    start_ts: str
    end_ts: str
    max_slots: int
    created_at: str
    updated_at: str
    version: int


class Client_(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    monthly_income_cents: int
    home_lat: float
    home_lng: float
    preferred_language: str
    accessibility_needs: List[str]
    created_at: str
    updated_at: str
    version: int


class Intake(TypedDict):
    id: str
    client_id: str
    presenting_needs: List[str]
    urgency: str
    household_size: int
    disability_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentGrant(TypedDict):
    id: str
    client_id: str
    provider_id: str
    scope: str
    granted_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    intake_id: str
    program_id: str
    consent_grant_id: str
    transport_mode: str
    travel_burden_naive_min: float
    travel_burden_routed_min: float
    eligibility_score: float
    provisional_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportPlan(TypedDict):
    id: str
    referral_id: str
    pickup_start_ts: str
    pickup_end_ts: str
    mode: str
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeReport(TypedDict):
    id: str
    referral_id: str
    outcome: str
    service_hours: float
    follow_up_needed: bool
    service_cost_final_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> ONLY id + created_at.
class FunderReport(TypedDict):
    id: str
    funder_id: str
    reporting_period_start: str
    reporting_period_end: str
    rounding_variant: str
    total_referrals: int
    total_completions: int
    total_disbursement_cents: int
    language_breakdown: Dict[str, int]
    created_at: str
