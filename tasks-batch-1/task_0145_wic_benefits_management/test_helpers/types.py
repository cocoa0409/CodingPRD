"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD exactly. Entities that the PRD declares as
append-only evidence (IncomeRecord, Redemption) carry only id + created_at and
deliberately omit updated_at / version.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ELIGIBILITY_CLERK = "EligibilityClerk"
    CPA = "CompetentProfessionalAuthority"
    PARTICIPANT = "Participant"


# ---------------------------------------------------------------------------
# Status enums (exact uppercase state strings from the PRD)
# ---------------------------------------------------------------------------
class VendorStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ParticipantStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    INCOME_DETERMINED = "INCOME_DETERMINED"
    RISK_ASSESSED = "RISK_ASSESSED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class FoodPrescriptionStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED_PARTIAL = "REDEEMED_PARTIAL"
    REDEEMED_FULL = "REDEEMED_FULL"
    VOIDED = "VOIDED"


class EbtAccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class ClinicAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PeerSupportSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Domain value enums
# ---------------------------------------------------------------------------
class ParticipantCategory(str, Enum):
    PREGNANT = "PREGNANT"
    POSTPARTUM = "POSTPARTUM"
    BREASTFEEDING = "BREASTFEEDING"
    INFANT = "INFANT"
    CHILD = "CHILD"


class AdjunctiveProgram(str, Enum):
    NONE = "NONE"
    SNAP = "SNAP"
    MEDICAID = "MEDICAID"
    TANF = "TANF"


class PayFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class IncomeMethod(str, Enum):
    ANNUALIZE_RECENT = "ANNUALIZE_RECENT"
    AVERAGE_ALL = "AVERAGE_ALL"


class IssuanceMode(str, Enum):
    FULL = "FULL"
    PRORATED = "PRORATED"


class VendorPeerGroup(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class AppointmentPurpose(str, Enum):
    INITIAL_CERT = "INITIAL_CERT"
    RECERT = "RECERT"
    NUTRITION_ED = "NUTRITION_ED"
    BF_SUPPORT = "BF_SUPPORT"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Agency(TypedDict):
    id: str
    name: str
    state_code: str
    caseload_cap: int
    active_caseload_count: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Clinic(TypedDict):
    id: str
    agency_id: str
    name: str
    appointment_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    agency_id: str
    legal_name: str
    peer_group: str
    status: str
    violation_points: int
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    agency_id: str
    household_size: int
    pregnancy_count: int
    adjunctive_program: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    household_id: str
    agency_id: str
    full_name: str
    ssn_last4: str
    category: str
    breastfeeding_opt_in: bool
    status: str
    priority_level: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    participant_id: str
    income_method: str
    annual_income_determined: Optional[float]
    income_limit: Optional[float]
    income_eligible: Optional[bool]
    determined_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    risk_factor_codes: List[str]
    total_risk_score: Optional[int]
    risk_eligible: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    participant_id: str
    application_id: str
    period_start_utc: str
    period_end_utc: str
    cert_length_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FoodPrescription(TypedDict):
    id: str
    certification_id: str
    participant_id: str
    issuance_mode: str
    line_items: List[dict]
    prescribed_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EbtAccount(TypedDict):
    id: str
    participant_id: str
    balance_units: Dict[str, int]
    issued_value_cents: int
    redeemed_value_cents: int
    voided_value_cents: int
    remaining_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClinicAppointment(TypedDict):
    id: str
    clinic_id: str
    participant_id: str
    purpose: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PeerSupportSession(TypedDict):
    id: str
    participant_id: str
    peer_counselor_id: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entity TypedDicts — append-only evidence (id + created_at only)
# ---------------------------------------------------------------------------
class IncomeRecord(TypedDict):
    id: str
    application_id: str
    gross_amount_cents: int
    pay_frequency: str
    sequence_index: int
    created_at: str


class Redemption(TypedDict):
    id: str
    ebt_account_id: str
    vendor_id: str
    food_category: str
    units: int
    value_cents: int
    sequence_index: int
    created_at: str
