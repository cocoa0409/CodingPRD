"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource in this API carries the
standard system-managed properties id, created_at, updated_at, and version
(PRD section on common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    QUALITY_ASSURANCE = "QualityAssurance"
    ENVIRONMENT_TECH = "EnvironmentTech"
    PRODUCTION_OPERATOR = "ProductionOperator"
    MATERIAL_HANDLER = "MaterialHandler"


class IsoClass(str, Enum):
    ISO_5 = "ISO_5"
    ISO_6 = "ISO_6"
    ISO_7 = "ISO_7"
    ISO_8 = "ISO_8"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    CERTIFICATION_EXPIRED = "CERTIFICATION_EXPIRED"
    CERTIFICATION_SUSPENDED = "CERTIFICATION_SUSPENDED"


class EnvironmentPosture(str, Enum):
    IN_CONTROL = "IN_CONTROL"
    ALERT = "ALERT"
    ACTION = "ACTION"
    SHUTDOWN = "SHUTDOWN"


class RoomLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class PersonnelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class GowningQualificationStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SamplingMetric(str, Enum):
    PARTICLE = "PARTICLE"
    VIABLE = "VIABLE"


class SamplingPointStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SampleClassification(str, Enum):
    IN_CONTROL = "IN_CONTROL"
    ALERT_EXCEEDED = "ALERT_EXCEEDED"
    ACTION_EXCEEDED = "ACTION_EXCEEDED"


class ExcursionSeverity(str, Enum):
    ALERT = "ALERT"
    ACTION = "ACTION"


class ExcursionStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CLOSED = "CLOSED"


class ProductImpact(str, Enum):
    NONE = "NONE"
    POTENTIAL = "POTENTIAL"
    CONFIRMED = "CONFIRMED"


class Disposition(str, Enum):
    RELEASE = "RELEASE"
    REJECT = "REJECT"
    REWORK = "REWORK"


class InvestigationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CertificationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class MaterialTransferStatus(str, Enum):
    STAGED = "STAGED"
    INTRODUCED = "INTRODUCED"
    REJECTED = "REJECTED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    ON_HOLD = "ON_HOLD"


class TravelerStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    VOID = "VOID"


class CleaningProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    VALIDATED = "VALIDATED"
    RE_VALIDATION_REQUIRED = "RE_VALIDATION_REQUIRED"


class CleaningCycleResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CleaningCycleStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class FindingSeverity(str, Enum):
    OBSERVATION = "OBSERVATION"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    CAPA_SUBMITTED = "CAPA_SUBMITTED"
    CAPA_VERIFIED = "CAPA_VERIFIED"


class Cleanroom(TypedDict, total=False):
    id: str
    room_code: str
    iso_class: str
    particle_alert_limit: int
    particle_action_limit: int
    viable_alert_limit: int
    viable_action_limit: int
    recert_interval_days: int
    certification_status: str
    certified_at: Optional[str]
    environment_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Personnel(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    role_title: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GowningQualification(TypedDict, total=False):
    id: str
    personnel_id: str
    cleanroom_id: str
    qualified_at: str
    qualification_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SamplingPoint(TypedDict, total=False):
    id: str
    cleanroom_id: str
    point_code: str
    metric: str
    zone_iso_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnvironmentalSample(TypedDict, total=False):
    id: str
    sampling_point_id: str
    result_value: int
    sampled_at: str
    classification: str
    triggered_excursion_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Excursion(TypedDict, total=False):
    id: str
    cleanroom_id: str
    sampling_point_id: str
    sample_id: str
    severity: str
    severity_score: float
    recurrence_of_excursion_id: Optional[str]
    recorded_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExcursionInvestigation(TypedDict, total=False):
    id: str
    excursion_id: str
    root_cause: str
    product_impact: str
    disposition: str
    investigated_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RoomCertification(TypedDict, total=False):
    id: str
    cleanroom_id: str
    executed_at: str
    location_mean_values: List[float]
    grade_passed: bool
    result: str
    supersedes_certification_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialTransfer(TypedDict, total=False):
    id: str
    cleanroom_id: str
    material_lot: str
    item_description: str
    staged_at: str
    dwell_minutes: int
    wiped_down: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AssemblyBatch(TypedDict, total=False):
    id: str
    cleanroom_id: str
    batch_number: str
    product_code: str
    status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssemblyTraveler(TypedDict, total=False):
    id: str
    batch_id: str
    step_sequence: int
    step_description: str
    performed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EntryLog(TypedDict, total=False):
    id: str
    personnel_id: str
    cleanroom_id: str
    entered_at: str
    exited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CleaningValidationProgram(TypedDict, total=False):
    id: str
    cleanroom_id: str
    method_code: str
    required_consecutive_passes: int
    consecutive_pass_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CleaningCycle(TypedDict, total=False):
    id: str
    program_id: str
    performed_by_user_id: str
    result: str
    verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerAudit(TypedDict, total=False):
    id: str
    customer_code: str
    cleanroom_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    audit_id: str
    severity: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int
