"""Domain types: entity TypedDicts, status enums, and the role enum.

All field names are exactly as named in the PRD. Every entity here is mutable
(per PRD 2.4) and therefore carries id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    NURSE = "Nurse"
    EMBRYOLOGIST = "Embryologist"
    BILLING_SPECIALIST = "BillingSpecialist"
    PATIENT = "Patient"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DonorStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"


class SurrogateStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MATCHED = "MATCHED"


class ConsentFormStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class PatientConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    STALE = "STALE"


class CryoTankStatus(str, Enum):
    ONLINE = "ONLINE"
    MAINTENANCE = "MAINTENANCE"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    STIM = "STIM"
    RETRIEVAL = "RETRIEVAL"
    FERTILIZATION = "FERTILIZATION"
    FRESH_TRANSFER = "FRESH_TRANSFER"
    FREEZE_ALL = "FREEZE_ALL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ESTIMATED = "ESTIMATED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class MedicationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ADMINISTERED = "ADMINISTERED"
    CANCELLED = "CANCELLED"


class AppointmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class SpecimenStatus(str, Enum):
    PENDING = "PENDING"
    STORED = "STORED"
    THAWED = "THAWED"
    DISCARDED = "DISCARDED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class AppointmentType(str, Enum):
    BLOODWORK = "BLOODWORK"
    ULTRASOUND = "ULTRASOUND"
    CONSULT = "CONSULT"


class DonorType(str, Enum):
    EGG = "EGG"
    SPERM = "SPERM"


class SpecimenType(str, Enum):
    EMBRYO = "EMBRYO"
    OOCYTE = "OOCYTE"
    SPERM = "SPERM"


class PregnancyTestResult(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    INCONCLUSIVE = "INCONCLUSIVE"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    VOID = "VOID"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry id/created_at/updated_at/version per PRD 2.4)
# --------------------------------------------------------------------------
class Clinic(TypedDict):
    id: str
    name: str
    timezone: str
    room_concurrency_limit: int
    current_clock_utc: str
    created_at: str
    updated_at: str
    version: int


class InsurancePackage(TypedDict):
    id: str
    clinic_id: str
    name: str
    base_price_cents: int
    coverage_pct: float
    stim_med_covered: bool
    cryo_storage_covered: bool
    annual_cryo_storage_cents: int
    lifetime_coverage_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    clinic_id: str
    full_name: str
    date_of_birth: str
    insurance_package_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DonorProfile(TypedDict):
    id: str
    clinic_id: str
    code: str
    donor_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SurrogateProfile(TypedDict):
    id: str
    clinic_id: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentForm(TypedDict):
    id: str
    clinic_id: str
    form_key: str
    version_label: str
    required_for: List[str]
    status: str
    supersedes_form_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatientConsent(TypedDict):
    id: str
    patient_id: str
    consent_form_id: str
    pinned_form_version: int
    pinned_form_status_at_sign: str
    status: str
    signed_at: str
    created_at: str
    updated_at: str
    version: int


class CryoTank(TypedDict):
    id: str
    clinic_id: str
    label: str
    capacity_slots: int
    reserved_slots: int
    committed_free_slots: int
    projected_free_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentCycle(TypedDict):
    id: str
    patient_id: str
    insurance_package_id: Optional[str]
    donor_profile_id: Optional[str]
    surrogate_profile_id: Optional[str]
    protocol_status: str
    billing_status: str
    oocytes_retrieved: int
    embryos_fertilized: int
    estimated_patient_owed_cents: int
    final_patient_owed_cents: int
    insurer_paid_cents: int
    gross_charge_cents: int
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class MedicationOrder(TypedDict):
    id: str
    treatment_cycle_id: str
    drug_name: str
    start_day_offset: int
    end_day_offset: int
    daily_dose_units: int
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringAppointment(TypedDict):
    id: str
    treatment_cycle_id: str
    clinic_id: str
    appointment_type: str
    start_utc: str
    end_utc: str
    room_capacity_weight: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CryoSpecimen(TypedDict):
    id: str
    treatment_cycle_id: str
    cryo_tank_id: str
    specimen_type: str
    storage_start_utc: Optional[str]
    storage_years_accrued: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CycleInvoice(TypedDict):
    id: str
    treatment_cycle_id: str
    line_items: list
    gross_total_cents: int
    insurer_total_cents: int
    patient_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeReport(TypedDict):
    id: str
    treatment_cycle_id: str
    pregnancy_test_result: str
    clinical_pregnancy: bool
    live_birth: bool
    utilization_rate: float
    created_at: str
    updated_at: str
    version: int
