"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the four common system fields
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    IMMUNIZATION_REGISTRAR = "ImmunizationRegistrar"
    RECORDS_CLERK = "RecordsClerk"
    PROVIDER = "Provider"


# --- Status / enum value sets ---
class PatientScheduleStatus(str, Enum):
    UP_TO_DATE = "UP_TO_DATE"
    BEHIND = "BEHIND"
    CONDITIONAL = "CONDITIONAL"
    NON_COMPLIANT = "NON_COMPLIANT"


class ProviderStatus(str, Enum):
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"


class VaccineProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VaccineLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RECALLED = "RECALLED"


class ImmunizationValidity(str, Enum):
    VALID = "VALID"
    INVALID_INTERVAL = "INVALID_INTERVAL"
    INVALID_AGE = "INVALID_AGE"
    INVALID_RECALL = "INVALID_RECALL"


class ImmunizationStatus(str, Enum):
    RECORDED = "RECORDED"
    AMENDED = "AMENDED"
    INVALIDATED = "INVALIDATED"
    DELETED = "DELETED"


class AllergySeverity(str, Enum):
    CONTRAINDICATED = "CONTRAINDICATED"
    PRECAUTION = "PRECAUTION"


class AllergyOrigin(str, Enum):
    MANUAL = "MANUAL"
    ADVERSE_EVENT = "ADVERSE_EVENT"


class ProviderReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_REJECTED = "PARTIALLY_REJECTED"
    REJECTED = "REJECTED"


class AdverseEventSeriousness(str, Enum):
    SERIOUS = "SERIOUS"
    NON_SERIOUS = "NON_SERIOUS"


class AdverseEventStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class ScheduleEvaluationStatus(str, Enum):
    UP_TO_DATE = "UP_TO_DATE"
    BEHIND = "BEHIND"
    CONDITIONAL = "CONDITIONAL"
    NON_COMPLIANT = "NON_COMPLIANT"


class CertificateType(str, Enum):
    COMPLETE = "COMPLETE"
    CONDITIONAL = "CONDITIONAL"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


# --- Entity TypedDicts (all common_fields: true -> carry id/created_at/updated_at/version) ---

class Patient(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    date_of_birth: str
    state_code: str
    schedule_status: str
    active_certificate_id: Optional[str]


class Provider(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    vfc_pin: str
    authorized_product_codes: List[str]
    status: str


class VaccineProduct(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    product_code: str
    antigen: str
    doses_in_series: int
    min_age_days: int
    recommended_age_days: int
    min_interval_days: int
    grace_period_days: int
    status: str


class VaccineLot(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    product_id: str
    lot_number: str
    received_date: str
    expiration_date: str
    doses_total: int
    administered_count: int
    status: str


class Immunization(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    lot_id: str
    provider_id: str
    report_id: Optional[str]
    administered_date: str
    dose_number: int
    validity: str
    status: str


class AllergyRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    antigen: str
    severity: str
    origin: str
    source_event_id: Optional[str]


class ProviderReport(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    provider_id: str
    line_count: int
    accepted_count: int
    rejected_count: int
    status: str


class AdverseEvent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    immunization_id: str
    patient_id: str
    seriousness: str
    symptoms: str
    status: str


class ScheduleEvaluation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    as_of_date: str
    overall_status: str
    antigen_results: list
    completeness_pct: float


class SchoolComplianceCertificate(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    evaluation_id: str
    certificate_type: str
    status: str


class LotRecall(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    lot_id: str
    reason: str
    invalidated_count: int
