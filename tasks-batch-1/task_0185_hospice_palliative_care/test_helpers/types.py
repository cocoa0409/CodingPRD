"""Domain types: entity TypedDicts, status enums, role enum for the hospice & palliative care API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / level enums ─────────────────────────────────────────────

class ElectionStatus(str, Enum):
    ELECTED = "ELECTED"
    REVOKED = "REVOKED"
    DISCHARGED = "DISCHARGED"
    EXPIRED = "EXPIRED"


class BenefitPeriodCertStatus(str, Enum):
    PENDING_CERT = "PENDING_CERT"
    CERTIFIED = "CERTIFIED"


class CertificationStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class CarePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class LevelOfCare(str, Enum):
    ROUTINE = "ROUTINE"
    RESPITE = "RESPITE"
    GIP = "GIP"


class CoverageStatus(str, Enum):
    COVERED = "COVERED"
    EXCLUDED = "EXCLUDED"


class ItemType(str, Enum):
    MEDICATION = "MEDICATION"
    DME = "DME"


class BereavementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DischargeReason(str, Enum):
    DEATH = "DEATH"
    MOVED_OUT_OF_AREA = "MOVED_OUT_OF_AREA"
    NO_LONGER_TERMINAL = "NO_LONGER_TERMINAL"


class IdgDiscipline(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    NURSE = "NURSE"
    SOCIAL_WORK = "SOCIAL_WORK"
    COUNSELOR = "COUNSELOR"
    AIDE = "AIDE"
    VOLUNTEER = "VOLUNTEER"


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PHYSICIAN = "Physician"
    CLINICAL_MANAGER = "ClinicalManager"
    BILLING_ADMIN = "BillingAdmin"


# ─── Entity TypedDicts (common_fields: true → id, created_at, updated_at, version) ───

class Provider(TypedDict):
    id: str
    name: str
    cap_year_start: str
    per_beneficiary_cap_cents: int
    cap_liability_cents: int
    total_paid_cents: int
    counted_beneficiaries: int
    cap_settled: bool
    created_at: str
    updated_at: str
    version: int


class Election(TypedDict):
    id: str
    provider_id: str
    patient_name: str
    election_date: str
    attending_physician_id: str
    status: str
    current_period_number: int
    days_used_in_period: int
    revocation_date: Optional[str]
    bereavement_required: bool
    created_at: str
    updated_at: str
    version: int


class BenefitPeriod(TypedDict):
    id: str
    election_id: str
    sequence: int
    length_days: int
    start_offset_days: int
    requires_face_to_face: bool
    certification_id: Optional[str]
    cert_status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    election_id: str
    period_sequence: int
    certifying_physician_id: str
    face_to_face_physician_id: Optional[str]
    face_to_face_date: Optional[str]
    narrative_present: bool
    expected_election_version: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    election_id: str
    supersedes_plan_id: Optional[str]
    revision_number: int
    idg_members: List[str]
    review_due_offset_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CareDay(TypedDict):
    id: str
    election_id: str
    benefit_period_id: Optional[str]
    service_date: str
    level_of_care: str
    high_intensity: bool
    payment_cents: int
    respite_run_length: int
    created_at: str
    updated_at: str
    version: int


class CoverageItem(TypedDict):
    id: str
    election_id: str
    care_plan_id: str
    item_type: str
    related_to_terminal_dx: bool
    coverage_status: str
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict):
    id: str
    full_name: str
    is_medical_director: bool
    created_at: str
    updated_at: str
    version: int


class BereavementCase(TypedDict):
    id: str
    election_id: str
    enrolled_date: str
    service_window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int
