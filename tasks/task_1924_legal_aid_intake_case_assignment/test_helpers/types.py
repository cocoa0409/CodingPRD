"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DOCS_REQUESTED = "DOCS_REQUESTED"
    SCREENED = "SCREENED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    WAITLISTED = "WAITLISTED"
    OPENED = "OPENED"
    WITHDRAWN = "WITHDRAWN"


class ConflictResult(str, Enum):
    CLEAR = "CLEAR"
    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"
    CONFIRMED_CONFLICT = "CONFIRMED_CONFLICT"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class CaseStatus(str, Enum):
    PENDING_ASSIGNMENT = "PENDING_ASSIGNMENT"
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    GRANT_RESERVED = "GRANT_RESERVED"
    GRANT_FROZEN = "GRANT_FROZEN"
    GRANT_SPENT = "GRANT_SPENT"
    GRANT_RELEASED = "GRANT_RELEASED"


class ServiceLevel(str, Enum):
    ADVICE_ONLY = "ADVICE_ONLY"
    EXTENDED = "EXTENDED"


class Placement(str, Enum):
    INTERNAL = "INTERNAL"
    PRO_BONO = "PRO_BONO"


class StaffType(str, Enum):
    ATTORNEY = "ATTORNEY"
    PARALEGAL = "PARALEGAL"
    INTAKE_SPECIALIST = "INTAKE_SPECIALIST"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    SEPARATED = "SEPARATED"


class PanelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class ReferralStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class CaseType(str, Enum):
    EVICTION_DEFENSE = "EVICTION_DEFENSE"
    FAMILY_DV = "FAMILY_DV"
    BENEFITS_APPEAL = "BENEFITS_APPEAL"
    CONSUMER_DEBT = "CONSUMER_DEBT"
    IMMIGRATION_RELIEF = "IMMIGRATION_RELIEF"
    EXPUNGEMENT = "EXPUNGEMENT"


class Venue(str, Enum):
    SUPERIOR_COURT = "SUPERIOR_COURT"
    HOUSING_COURT = "HOUSING_COURT"
    FAMILY_COURT = "FAMILY_COURT"
    MUNICIPAL_COURT = "MUNICIPAL_COURT"
    ADMIN_TRIBUNAL = "ADMIN_TRIBUNAL"
    FEDERAL_TRIBUNAL = "FEDERAL_TRIBUNAL"


class OutcomeCode(str, Enum):
    FULL_WIN = "FULL_WIN"
    PARTIAL_WIN = "PARTIAL_WIN"
    SETTLEMENT = "SETTLEMENT"
    ADVICE_GIVEN = "ADVICE_GIVEN"
    REFERRED_OUT = "REFERRED_OUT"
    WITHDRAWN_BY_CLIENT = "WITHDRAWN_BY_CLIENT"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class ReasonCode(str, Enum):
    OVER_INCOME = "OVER_INCOME"
    NO_EXTENDED_CAPACITY = "NO_EXTENDED_CAPACITY"
    CONFLICT_CONFIRMED = "CONFLICT_CONFIRMED"
    CLIENT_WITHDRAWN = "CLIENT_WITHDRAWN"


class ActivityCode(str, Enum):
    RESEARCH = "RESEARCH"
    CLIENT_MEETING = "CLIENT_MEETING"
    COURT_APPEARANCE = "COURT_APPEARANCE"
    DRAFTING = "DRAFTING"
    ADMIN = "ADMIN"


class UserRole(str, Enum):
    INTAKE_SPECIALIST = "IntakeSpecialist"
    SUPERVISING_ATTORNEY = "SupervisingAttorney"
    STAFF_ATTORNEY = "StaffAttorney"
    PARALEGAL = "Paralegal"
    ETHICS_OFFICER = "EthicsOfficer"
    GRANTS_MANAGER = "GrantsManager"
    PROGRAM_DIRECTOR = "ProgramDirector"


# ---- Entity TypedDicts ----
# Nine primary resources carry id + created_at + updated_at + version.


class Client(TypedDict, total=False):
    id: str
    full_name: str
    residence_county: str
    household_size: int
    annual_gross_income_cents: int
    annual_countable_income_cents: int
    receives_means_tested_benefits: bool
    vulnerability_factors: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IntakeApplication(TypedDict, total=False):
    id: str
    client_id: str
    case_type: str
    opposing_party_name: str
    incident_county: str
    incident_description: str
    status: str
    venue: Optional[str]
    gross_poverty_percentage: Optional[float]
    countable_poverty_percentage: Optional[float]
    priority_score: Optional[float]
    eligibility_determination: Optional[str]
    screened_by_staff_id: Optional[str]
    screened_at: Optional[str]
    promoted_from_waitlist: bool
    created_at: str
    updated_at: str
    version: int


class ConflictCheck(TypedDict, total=False):
    id: str
    application_id: str
    result: str
    checked_by_staff_id: str
    checked_at: str
    valid_until: str
    notes: str
    waiver_reason: Optional[str]
    resolved_by_staff_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    application_id: str
    grant_program_id: Optional[str]
    assigned_attorney_id: Optional[str]
    assigned_paralegal_id: Optional[str]
    service_level: str
    venue: str
    placement: str
    status: str
    funding_status: str
    case_weight: int
    reserved_cents: int
    outcome_code: Optional[str]
    closure_reason: Optional[str]
    advice_deadline: Optional[str]
    opened_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    staff_type: str
    admitted_counties: List[str]
    practice_areas: List[str]
    max_units: int
    supervising_attorney_id: Optional[str]
    status: str
    weighted_open_units: int
    open_case_count: int
    created_at: str
    updated_at: str
    version: int


class ReferralPanelMember(TypedDict, total=False):
    id: str
    full_name: str
    firm_name: str
    practice_areas: List[str]
    counties: List[str]
    max_active_referrals: int
    active_referral_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    case_id: str
    panel_member_id: str
    status: str
    notes: str
    offered_at: str
    response_deadline: str
    responded_at: Optional[str]
    service_start_date: Optional[str]
    service_end_date: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantProgram(TypedDict, total=False):
    id: str
    name: str
    funder: str
    period_start: str
    period_end: str
    allowed_case_types: List[str]
    allowed_counties: List[str]
    income_cap_percentage: float
    per_case_rate_cents: int
    total_budget_cents: int
    reserved_cents: int
    spent_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantReport(TypedDict, total=False):
    id: str
    grant_program_id: str
    period_label: str
    status: str
    cases_opened_count: int
    cases_closed_count: int
    total_hours: float
    reserved_cents_snapshot: int
    spent_cents_snapshot: int
    generated_by_user_id: str
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Five auxiliary resources carry ONLY id + created_at (no updated_at, no version).


class VenueRule(TypedDict, total=False):
    id: str
    county: str
    case_type: str
    venue: str
    priority_base_weight: int
    extended_eligible: bool
    created_at: str


class TimeEntry(TypedDict, total=False):
    id: str
    case_id: str
    staff_id: str
    hours: float
    activity_code: str
    work_date: str
    created_at: str


class SatisfactionSurvey(TypedDict, total=False):
    id: str
    case_id: str
    score: int
    would_recommend: bool
    comments: str
    created_at: str


class UnmetNeedRecord(TypedDict, total=False):
    id: str
    application_id: str
    reason_code: str
    case_type: str
    incident_county: str
    created_at: str


class WaitlistEntry(TypedDict, total=False):
    id: str
    application_id: str
    priority_score_snapshot: float
    required_weight: int
    created_at: str
