"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are taken verbatim from the PRD's entity and
state-machine descriptions.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum value sets ─────────────────────────────────────────

class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    CODED = "CODED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    SIGNED = "SIGNED"
    TRANSMITTED = "TRANSMITTED"
    DISPENSED = "DISPENSED"
    VOIDED = "VOIDED"


class ReferralStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PortalAccountStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class HedisMeasureStatus(str, Enum):
    GAP = "GAP"
    NUMERATOR_COMPLIANT = "NUMERATOR_COMPLIANT"
    EXCLUDED = "EXCLUDED"


class Specialty(str, Enum):
    FAMILY_MEDICINE = "FAMILY_MEDICINE"
    INTERNAL_MEDICINE = "INTERNAL_MEDICINE"
    PEDIATRICS = "PEDIATRICS"


class VisitType(str, Enum):
    CONSULTATION = "CONSULTATION"
    PHYSICAL = "PHYSICAL"
    VACCINATION = "VACCINATION"


class CptCategory(str, Enum):
    EM = "EM"
    PREVENTIVE = "PREVENTIVE"
    VACCINE_ADMIN = "VACCINE_ADMIN"
    PROCEDURE = "PROCEDURE"


class DeaSchedule(str, Enum):
    NON_CONTROLLED = "NON_CONTROLLED"
    C_II = "C_II"
    C_III = "C_III"
    C_IV = "C_IV"
    C_V = "C_V"


class TargetSpecialty(str, Enum):
    CARDIOLOGY = "CARDIOLOGY"
    DERMATOLOGY = "DERMATOLOGY"
    ORTHOPEDICS = "ORTHOPEDICS"
    ENDOCRINOLOGY = "ENDOCRINOLOGY"


class ReferralPriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class MeasureType(str, Enum):
    CIS_FLU = "CIS_FLU"
    BCS_MAMMOGRAM = "BCS_MAMMOGRAM"
    CBP_BP_CONTROL = "CBP_BP_CONTROL"
    MED_ADHERENCE = "MED_ADHERENCE"


class MeasureMethod(str, Enum):
    ADMINISTRATIVE = "ADMINISTRATIVE"
    HYBRID = "HYBRID"


class Sex(str, Enum):
    M = "M"
    F = "F"


class UserRole(str, Enum):
    FRONT_DESK = "FrontDesk"
    PROVIDER = "Provider"
    BILLER = "Biller"
    QUALITY_ANALYST = "QualityAnalyst"
    PATIENT = "Patient"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# Entities below carry the common fields id/created_at/updated_at/version,
# except CptCode which is shared reference configuration (id + created_at only).

class Provider(TypedDict):
    id: str
    npi: str
    full_name: str
    specialty: str
    dea_number: Optional[str]
    epcs_enrolled: bool
    panel_capacity: int
    status: str
    panel_size: int
    controlled_rx_count: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    first_name: str
    last_name: str
    date_of_birth: str
    sex: str
    pcp_id: Optional[str]
    status: str
    lifetime_charges_cents: int
    outstanding_balance_cents: int
    active_medication_count: int
    open_care_gaps: int
    created_at: str
    updated_at: str
    version: int


# CptCode is shared reference configuration: id + created_at only,
# NO updated_at, NO version.
class CptCode(TypedDict):
    id: str
    code: str
    short_description: str
    category: str
    base_fee_cents: int
    requires_em_level: bool
    created_at: str


class Visit(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    visit_type: str
    scheduled_start: str
    scheduled_end: str
    vaccine_code: Optional[str]
    status: str
    billed_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ChargeLine(TypedDict):
    id: str
    visit_id: str
    cpt_code: str
    units: int
    em_level: Optional[int]
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    visit_id: str
    drug_name: str
    schedule: str
    two_factor_token: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    referring_provider_id: str
    target_specialty: str
    priority: str
    status: str
    authorization_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PortalAccount(TypedDict):
    id: str
    patient_id: str
    login_email: str
    status: str
    activation_token: str
    failed_login_count: int
    created_at: str
    updated_at: str
    version: int


class HedisMeasure(TypedDict):
    id: str
    patient_id: str
    measure_type: str
    measurement_year: int
    method: str
    eligible: bool
    status: str
    chart_confirmed: bool
    created_at: str
    updated_at: str
    version: int
