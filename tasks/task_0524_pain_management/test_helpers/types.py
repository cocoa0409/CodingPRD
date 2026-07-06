"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PRESCRIBER = "Prescriber"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PRIOR_AUTH_CLERK = "PriorAuthClerk"


class ProviderRoleKind(str, Enum):
    PRESCRIBER = "PRESCRIBER"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"


class PatientStatus(str, Enum):
    REFERRED = "REFERRED"
    INTAKE_SCHEDULED = "INTAKE_SCHEDULED"
    INTAKE_COMPLETE = "INTAKE_COMPLETE"
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"


class ComplianceFlag(str, Enum):
    NONE = "NONE"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"


class OpioidAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PdmpOutcome(str, Enum):
    CLEAR = "CLEAR"
    CONCERN = "CONCERN"


class TreatmentPlanModality(str, Enum):
    INJECTION = "INJECTION"
    RFA = "RFA"
    MEDICATION = "MEDICATION"


class TreatmentPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    PROCEDURE_PATH = "PROCEDURE_PATH"
    MEDICATION_PATH = "MEDICATION_PATH"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProcedureStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PriorAuthTargetKind(str, Enum):
    PROCEDURE = "PROCEDURE"
    PRESCRIPTION = "PRESCRIPTION"


class PriorAuthStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PrescriptionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    TAPERING = "TAPERING"
    SUSPENDED = "SUSPENDED"
    DISCONTINUED = "DISCONTINUED"


class UrineDrugScreenStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    RESULTED_CONSISTENT = "RESULTED_CONSISTENT"
    RESULTED_INCONSISTENT = "RESULTED_INCONSISTENT"


class PillCountResult(str, Enum):
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"


# --- Entity TypedDicts ---
# All entities below carry the full common-field set (id, created_at, updated_at,
# version) except PdmpCheck, which is an immutable audit record carrying only
# id and created_at.


class Clinic(TypedDict):
    id: str
    name: str
    state_code: str
    med_review_threshold_mg: int
    pill_count_tolerance: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    clinic_id: str
    full_name: str
    dea_number: str
    role_kind: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    clinic_id: str
    full_name: str
    referral_source: str
    status: str
    intake_utc: Optional[str]
    compliance_flag: str
    current_daily_med_mg: float
    open_uds_count: int
    created_at: str
    updated_at: str
    version: int


class OpioidAgreement(TypedDict):
    id: str
    clinic_id: str
    patient_id: str
    prescriber_id: str
    signed_utc: Optional[str]
    expires_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable audit record, only id + created_at
class PdmpCheck(TypedDict):
    id: str
    clinic_id: str
    patient_id: str
    queried_by_provider_id: str
    outside_med_mg: float
    outcome: str
    queried_utc: str
    created_at: str


class TreatmentPlan(TypedDict):
    id: str
    patient_id: str
    modality: str
    requires_procedure: bool
    requires_medication: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FluoroscopySuite(TypedDict):
    id: str
    clinic_id: str
    name: str
    cleanup_buffer_minutes: int
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class Procedure(TypedDict):
    id: str
    patient_id: str
    treatment_plan_id: str
    suite_id: str
    prior_auth_id: str
    start_utc: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    patient_id: str
    target_kind: str
    payer: str
    authorized_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    patient_id: str
    prescriber_id: str
    prior_auth_id: Optional[str]
    drug_name: str
    dose_mg: float
    units_per_day: float
    conversion_factor: float
    day_supply: int
    pills_dispensed: int
    provisional_daily_med_mg: float
    final_daily_med_mg: Optional[float]
    taper_step_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class UrineDrugScreen(TypedDict):
    id: str
    patient_id: str
    due_utc: str
    collected_utc: Optional[str]
    expected_substances: List[str]
    detected_substances: Optional[List[str]]
    recollect_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PillCountAudit(TypedDict):
    id: str
    patient_id: str
    prescription_id: str
    audit_utc: str
    counted_pills: int
    expected_pills_forward: float
    expected_pills_chronological: float
    discrepancy_pills: float
    result: str
    created_at: str
    updated_at: str
    version: int


class ControlledSubstanceLedger(TypedDict):
    id: str
    patient_id: str
    total_active_med_mg: float
    discontinued_med_mg: float
    suspended_med_mg: float
    created_at: str
    updated_at: str
    version: int
