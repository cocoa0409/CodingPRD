"""Domain types for the School-Based Medicaid Billing (LEA) API.

Entity TypedDicts, status enums, and the role enum. Every entity in this
system carries the common fields id/created_at/updated_at/version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---------------------------------------------------------------
class UserRole(str, Enum):
    SERVICE_PROVIDER = "ServiceProvider"
    BILLING_COORDINATOR = "BillingCoordinator"
    MEDICAID_COORDINATOR = "MedicaidCoordinator"
    STATE_REVIEWER = "StateReviewer"


# --- Status enums ------------------------------------------------------------
class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class IEPAuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"
    EXPIRED = "EXPIRED"


class ParentalConsentStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class ProviderCredentialStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class ServiceLogStatus(str, Enum):
    LOGGED = "LOGGED"
    DOCUMENTED = "DOCUMENTED"
    VERIFIED = "VERIFIED"
    CLAIMED = "CLAIMED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class RMTSQuarterStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RMTSMomentStatus(str, Enum):
    GENERATED = "GENERATED"
    RESPONDED = "RESPONDED"
    CODED = "CODED"


class CostSettlementStatus(str, Enum):
    CALCULATED = "CALCULATED"
    CERTIFIED = "CERTIFIED"
    SETTLED = "SETTLED"


# --- Domain value enums ------------------------------------------------------
class ServiceType(str, Enum):
    SPEECH_THERAPY = "SPEECH_THERAPY"
    OCCUPATIONAL_THERAPY = "OCCUPATIONAL_THERAPY"
    PHYSICAL_THERAPY = "PHYSICAL_THERAPY"
    PSYCH_COUNSELING = "PSYCH_COUNSELING"
    NURSING = "NURSING"
    AUDIOLOGY = "AUDIOLOGY"


class Discipline(str, Enum):
    SLP = "SLP"
    OT = "OT"
    PT = "PT"
    PSYCH = "PSYCH"
    RN = "RN"
    AUD = "AUD"


class CredentialType(str, Enum):
    STATE_LICENSE = "STATE_LICENSE"
    NPI_ENROLLMENT = "NPI_ENROLLMENT"
    MEDICAID_ENROLLMENT = "MEDICAID_ENROLLMENT"


class ConsentType(str, Enum):
    BILLING = "BILLING"
    DISCLOSURE = "DISCLOSURE"


class ActivityCategory(str, Enum):
    DIRECT_MEDICAL = "DIRECT_MEDICAL"
    MEDICAL_ADMIN = "MEDICAL_ADMIN"
    GENERAL_ADMIN = "GENERAL_ADMIN"
    NON_MEDICAL = "NON_MEDICAL"
    NON_RESPONSE = "NON_RESPONSE"


class DenialReason(str, Enum):
    MISSING_CONSENT = "MISSING_CONSENT"
    CREDENTIAL_LAPSED = "CREDENTIAL_LAPSED"
    DUPLICATE_CLAIM = "DUPLICATE_CLAIM"
    DOC_INCOMPLETE = "DOC_INCOMPLETE"


# --- Entity TypedDicts (all entities carry id/created_at/updated_at/version) --
class Student(TypedDict, total=False):
    id: str
    medicaid_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    district_student_id: str
    medicaid_eligible: bool
    status: str
    interim_paid_cents: int
    verified_service_units: int
    created_at: str
    updated_at: str
    version: int


class IEPAuthorization(TypedDict, total=False):
    id: str
    student_id: str
    service_type: str
    procedure_code: str
    unit_minutes: int
    unit_rate_cents: int
    authorized_minutes_per_session: int
    sessions_per_week: int
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ParentalConsent(TypedDict, total=False):
    id: str
    student_id: str
    consent_type: str
    signed_by: str
    status: str
    granted_date: Optional[str]
    revoked_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    npi: str
    first_name: str
    last_name: str
    discipline: str
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class ProviderCredential(TypedDict, total=False):
    id: str
    provider_id: str
    credential_type: str
    license_number: str
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceLog(TypedDict, total=False):
    id: str
    iep_authorization_id: str
    provider_id: str
    student_id: str
    claim_id: Optional[str]
    service_date: str
    start_time: str
    end_time: str
    delivered_minutes: int
    group_size: int
    documentation_note: Optional[str]
    return_reason: Optional[str]
    delivered_units: int
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    student_id: str
    service_month: str
    status: str
    total_charge_cents: int
    interim_payment_cents: int
    denial_reason: Optional[str]
    rebill_count: int
    submitted_date: Optional[str]
    attached_log_count: int
    created_at: str
    updated_at: str
    version: int


class RMTSQuarter(TypedDict, total=False):
    id: str
    fiscal_quarter: str
    status: str
    total_moments: int
    responded_moments: int
    medicaid_eligible_moments: int
    medicaid_eligibility_ratio: float
    created_at: str
    updated_at: str
    version: int


class RMTSMoment(TypedDict, total=False):
    id: str
    rmts_quarter_id: str
    provider_id: str
    moment_timestamp: str
    activity_response: Optional[str]
    activity_category: Optional[str]
    is_medicaid_eligible_moment: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CostSettlement(TypedDict, total=False):
    id: str
    rmts_quarter_id: str
    certified_cost_cents: int
    iep_ratio_bps: int
    fmap_bps: int
    interim_paid_cents: int
    gross_medicaid_cost_cents: int
    federal_share_cents: int
    net_settlement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
