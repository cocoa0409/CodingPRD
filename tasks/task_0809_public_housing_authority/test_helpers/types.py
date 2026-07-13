"""Domain types: entity TypedDicts, status enums, role enum for the PHA API."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    INTAKE_CLERK = "IntakeClerk"
    HOUSING_SPECIALIST = "HousingSpecialist"
    PROPERTY_MANAGER = "PropertyManager"
    APPLICANT = "Applicant"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ApplicantStatus(str, Enum):
    APPLIED = "APPLIED"
    WAITLISTED = "WAITLISTED"
    HOUSED = "HOUSED"
    WITHDRAWN = "WITHDRAWN"


class PreferenceType(str, Enum):
    VETERAN = "VETERAN"
    ELDERLY = "ELDERLY"
    DISABLED = "DISABLED"
    INVOLUNTARY_DISPLACEMENT = "INVOLUNTARY_DISPLACEMENT"
    LOCAL_RESIDENT = "LOCAL_RESIDENT"
    WORKING_FAMILY = "WORKING_FAMILY"


class PreferenceClaimStatus(str, Enum):
    CLAIMED = "CLAIMED"
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"


class WaitlistStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class WaitlistEntryStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    OFFERED = "OFFERED"
    HOUSED = "HOUSED"
    PURGED = "PURGED"
    WITHDRAWN = "WITHDRAWN"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFERED = "OFFERED"
    OCCUPIED = "OCCUPIED"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REFUSED = "REFUSED"


class TenancyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CertificationType(str, Enum):
    INITIAL = "INITIAL"
    ANNUAL = "ANNUAL"
    INTERIM = "INTERIM"


class CertificationStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class HudStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InterimChangeType(str, Enum):
    INCOME_DECREASE = "INCOME_DECREASE"
    INCOME_INCREASE = "INCOME_INCREASE"
    COMPOSITION = "COMPOSITION"


class InterimChangeStatus(str, Enum):
    REPORTED = "REPORTED"
    PROCESSED = "PROCESSED"
    DENIED = "DENIED"


class GrievanceType(str, Enum):
    GRIEVANCE = "GRIEVANCE"
    EVICTION = "EVICTION"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (every entity carries common_fields: id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Applicant(TypedDict):
    id: str
    household_name: str
    application_date: str
    status: str
    annual_gross_income_cents: int
    household_size: int
    created_at: str
    updated_at: str
    version: int


class HouseholdMember(TypedDict):
    id: str
    applicant_id: str
    full_name: str
    relationship: str
    annual_income_cents: int
    nonrecurring_income_cents: int
    is_dependent: bool
    is_elderly: bool
    is_disabled: bool
    created_at: str
    updated_at: str
    version: int


class PreferenceClaim(TypedDict):
    id: str
    applicant_id: str
    preference_type: str
    status: str
    points_awarded: int
    created_at: str
    updated_at: str
    version: int


class Waitlist(TypedDict):
    id: str
    site_name: str
    bedroom_size: int
    status: str
    lottery_drawn: bool
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    applicant_id: str
    waitlist_id: str
    status: str
    lottery_number: Optional[int]
    total_points: int
    effective_rank: int
    refusal_count: int
    last_contact_at: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    address_label: str
    bedroom_size: int
    utility_allowance_cents: int
    income_limit_cents: int
    status: str
    last_lease_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    waitlist_entry_id: str
    unit_id: str
    status: str
    offered_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Tenancy(TypedDict):
    id: str
    applicant_id: str
    unit_id: str
    status: str
    lease_start_date: str
    lease_end_date: Optional[str]
    monthly_tenant_rent_cents: int
    utility_reimbursement_cents: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    tenancy_id: str
    source_interim_change_id: Optional[str]
    cert_type: str
    status: str
    hud_status: str
    effective_date: str
    childcare_expenses_annual_cents: int
    medical_expenses_annual_cents: int
    annual_gross_income_cents: int
    annual_adjusted_income_cents: int
    ttp_cents: int
    created_at: str
    updated_at: str
    version: int


class InterimChange(TypedDict):
    id: str
    tenancy_id: str
    change_type: str
    status: str
    reported_at: str
    effective_date: str
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict):
    id: str
    tenancy_id: str
    grievance_type: str
    status: str
    reason: str
    filed_at: str
    created_at: str
    updated_at: str
    version: int
