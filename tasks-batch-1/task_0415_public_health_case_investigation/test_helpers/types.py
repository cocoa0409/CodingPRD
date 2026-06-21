"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Public Health Case Investigation PRD. Entities that carry the
common system-managed fields (id, created_at, updated_at, version) are modeled
with all four; the append-only ExposureEvent carries only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    JURISDICTION_ADMIN = "JurisdictionAdmin"
    INTAKE_PROCESSOR = "IntakeProcessor"
    CASE_INVESTIGATOR = "CaseInvestigator"
    CONTACT_TRACER = "ContactTracer"
    EPI_ANALYST = "EpiAnalyst"


# ─── Status enums ─────────────────────────────────────────────────────────
class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CLASSIFIED = "CLASSIFIED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    TRANSFER_PENDING = "TRANSFER_PENDING"


class CaseClassification(str, Enum):
    SUSPECT = "SUSPECT"
    PROBABLE = "PROBABLE"
    CONFIRMED = "CONFIRMED"
    NOT_A_CASE = "NOT_A_CASE"


class LabResultStatus(str, Enum):
    RECEIVED = "RECEIVED"
    LINKED = "LINKED"
    UNLINKED = "UNLINKED"
    SUPERSEDED = "SUPERSEDED"


class LabResultValue(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    INDETERMINATE = "INDETERMINATE"


class ContactStatus(str, Enum):
    ELICITED = "ELICITED"
    NOTIFICATION_PENDING = "NOTIFICATION_PENDING"
    NOTIFIED = "NOTIFIED"
    NOTIFICATION_FAILED = "NOTIFICATION_FAILED"
    MONITORING_ACTIVE = "MONITORING_ACTIVE"
    MONITORING_COMPLETE = "MONITORING_COMPLETE"
    PROMOTED_TO_CASE = "PROMOTED_TO_CASE"
    VOIDED = "VOIDED"


class ExposureSetting(str, Enum):
    HOUSEHOLD = "HOUSEHOLD"
    HEALTHCARE = "HEALTHCARE"
    WORKPLACE = "WORKPLACE"
    SOCIAL = "SOCIAL"
    COMMUNITY = "COMMUNITY"


class PriorityBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class QuarantineReleaseBasis(str, Enum):
    STANDARD = "STANDARD"
    TEST_BASED = "TEST_BASED"


class MonitoringType(str, Enum):
    QUARANTINE = "QUARANTINE"
    ISOLATION = "ISOLATION"


class MonitoringPeriodStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED_EARLY = "RELEASED_EARLY"


class JurisdictionTransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class OutbreakClusterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class NedssExportStatus(str, Enum):
    GENERATED = "GENERATED"
    TRANSMITTED = "TRANSMITTED"
    VOIDED = "VOIDED"


# ─── Entity TypedDicts (common_fields: true → id/created_at/updated_at/version)
class SurveillanceProgram(TypedDict):
    id: str
    name: str
    description: Optional[str]
    current_date: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    program_id: str
    name: str
    fips_code: str
    active_monitoring_count: int
    created_at: str
    updated_at: str
    version: int


class ReportableCondition(TypedDict):
    id: str
    program_id: str
    condition_code: str
    display_name: str
    presymptomatic_days: int
    infectious_tail_days: int
    quarantine_days: int
    test_based_release_days: int
    test_release_earliest_offset_days: int
    isolation_min_days: int
    fever_free_days: int
    cluster_min_cases: int
    cluster_window_days: int
    requires_lab_confirmation: bool
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    program_id: str
    jurisdiction_id: str
    condition_code: str
    patient_reference: str
    source_lab_result_id: Optional[str]
    source_contact_id: Optional[str]
    symptom_onset_date: Optional[str]
    specimen_collection_date: Optional[str]
    last_symptomatic_date: Optional[str]
    is_symptomatic: bool
    interview_completed: bool
    infectious_start_date: Optional[str]
    infectious_end_date: Optional[str]
    isolation_end_date: Optional[str]
    completeness_score: int
    contact_count: int
    linked_positive_count: int
    cluster_id: Optional[str]
    exposure_setting_location_id: Optional[str]
    classification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LabResult(TypedDict):
    id: str
    program_id: str
    jurisdiction_id: str
    condition_code: str
    patient_reference: str
    result_value: str
    specimen_collection_date: str
    linked_case_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contact(TypedDict):
    id: str
    program_id: str
    source_case_id: str
    monitoring_jurisdiction_id: str
    contact_reference: str
    exposure_setting: str
    proximity_meters: float
    cumulative_exposure_minutes: int
    is_high_risk_contact: bool
    last_exposure_date: str
    priority_score: int
    priority_band: str
    quarantine_release_basis: str
    quarantine_end_date: Optional[str]
    has_qualifying_negative_test: bool
    notification_attempts: int
    promoted_case_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → append-only encounter log: id + created_at ONLY
class ExposureEvent(TypedDict):
    id: str
    program_id: str
    contact_id: str
    case_id: str
    encounter_date: str
    setting_note: Optional[str]
    created_at: str


class MonitoringPeriod(TypedDict):
    id: str
    program_id: str
    contact_id: str
    jurisdiction_id: str
    monitoring_type: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class JurisdictionTransfer(TypedDict):
    id: str
    program_id: str
    case_id: str
    from_jurisdiction_id: str
    to_jurisdiction_id: str
    expected_case_version: int
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutbreakCluster(TypedDict):
    id: str
    program_id: str
    condition_code: str
    exposure_setting_location_id: str
    anchor_case_id: str
    member_case_count: int
    earliest_onset_date: str
    latest_onset_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NedssExport(TypedDict):
    id: str
    program_id: str
    case_id: str
    snapshot_classification: str
    snapshot_completeness_score: int
    nedss_message_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
