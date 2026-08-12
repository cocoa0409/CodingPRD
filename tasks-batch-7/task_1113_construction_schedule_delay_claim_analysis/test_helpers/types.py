"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, List, TypedDict


class UserRole(str, Enum):
    CONTRACTOR_SCHEDULER = "ContractorScheduler"
    PROJECT_CONTROLS_ENGINEER = "ProjectControlsEngineer"
    OWNER_REPRESENTATIVE = "OwnerRepresentative"
    CLAIMS_CONSULTANT = "ClaimsConsultant"
    SYSTEM_ADMIN = "SystemAdmin"


class ProjectStatus(str, Enum):
    PRECONSTRUCTION = "PRECONSTRUCTION"
    ACTIVE = "ACTIVE"
    SUBSTANTIALLY_COMPLETE = "SUBSTANTIALLY_COMPLETE"
    CLOSED = "CLOSED"


class ScheduleVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ScheduleVersionKind(str, Enum):
    BASELINE = "BASELINE"
    UPDATE = "UPDATE"


class RelationshipType(str, Enum):
    FS = "FS"
    SS = "SS"
    FF = "FF"
    SF = "SF"


class ProgressUpdateStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DelayEventStatus(str, Enum):
    DRAFT = "DRAFT"
    NOTICED = "NOTICED"
    TIA_SUBMITTED = "TIA_SUBMITTED"
    TIA_ACCEPTED = "TIA_ACCEPTED"
    TIA_REJECTED = "TIA_REJECTED"


class Causation(str, Enum):
    OWNER_CAUSED = "OWNER_CAUSED"
    CONTRACTOR_CAUSED = "CONTRACTOR_CAUSED"
    THIRD_PARTY = "THIRD_PARTY"
    FORCE_MAJEURE = "FORCE_MAJEURE"


class FloatOwnershipPolicy(str, Enum):
    CONTRACTOR_OWNS = "CONTRACTOR_OWNS"
    OWNER_OWNS = "OWNER_OWNS"
    SHARED_FIRST_COME = "SHARED_FIRST_COME"


class EotStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"


class AccelerationDirectiveStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PERFORMING = "PERFORMING"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    UNDER_NEGOTIATION = "UNDER_NEGOTIATION"
    RESOLVED = "RESOLVED"


class RecoveryVariant(str, Enum):
    ACTUAL_COST = "ACTUAL_COST"
    MEASURED_MILE = "MEASURED_MILE"


class LdaStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"
    OFFSET_BY_EOT = "OFFSET_BY_EOT"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    REVERSED = "REVERSED"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).


class ConstructionProject(TypedDict, total=False):
    id: str
    project_name: str
    contract_start_date: str
    contract_completion_date: str
    current_completion_date: str
    liquidated_damages_daily_rate_cents: int
    ld_cap_cents: int
    float_ownership_policy: str
    notice_window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduleVersion(TypedDict, total=False):
    id: str
    project_id: str
    kind: str
    data_date: str
    revision_number: int
    supersedes_version_id: Optional[str]
    projected_finish_date: Optional[str]
    critical_path_activity_count: Optional[int]
    total_activities: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Activity(TypedDict, total=False):
    id: str
    schedule_version_id: str
    activity_code: str
    description: str
    original_duration_days: int
    remaining_duration_days: int
    percent_complete: float
    actual_start: Optional[str]
    actual_finish: Optional[str]
    early_start: Optional[str]
    early_finish: Optional[str]
    late_start: Optional[str]
    late_finish: Optional[str]
    total_float_days: Optional[int]
    is_critical: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class ActivityRelationship(TypedDict, total=False):
    # Lighter sub-resource (PRD §2.5): carries ONLY id + created_at.
    id: str
    schedule_version_id: str
    predecessor_activity_id: str
    successor_activity_id: str
    relationship_type: str
    lag_days: int
    created_at: str


class ProgressUpdate(TypedDict, total=False):
    id: str
    schedule_version_id: str
    reporting_period_end: str
    submitted_by_contractor_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgressEntry(TypedDict, total=False):
    # Lighter sub-resource (PRD §2.5): carries ONLY id + created_at.
    id: str
    progress_update_id: str
    activity_id: str
    percent_complete: float
    remaining_duration_days: int
    actual_start: Optional[str]
    actual_finish: Optional[str]
    created_at: str


class DelayEvent(TypedDict, total=False):
    id: str
    project_id: str
    title: str
    causation: str
    event_start_date: str
    event_end_date: Optional[str]
    notice_submitted_at: Optional[str]
    notice_within_window: Optional[bool]
    fragnet_activity_ids: List[str]
    fragnet_inserted_into_version_id: Optional[str]
    tia_prolongation_days_prospective: Optional[int]
    tia_prolongation_days_retrospective: Optional[int]
    apportioned_compensable_days: Optional[int]
    apportioned_excusable_non_compensable_days: Optional[int]
    apportioned_non_excusable_days: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeExtensionRequest(TypedDict, total=False):
    id: str
    project_id: str
    delay_event_id: str
    requested_days: int
    approved_days: Optional[int]
    cost_recovery_cents: int
    awarded_cost_cents: Optional[int]
    submission_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccelerationDirective(TypedDict, total=False):
    id: str
    project_id: str
    directive_reference: str
    issued_at: Optional[str]
    directed_completion_date: str
    baseline_completion_date: Optional[str]
    days_to_recover: Optional[int]
    actual_cost_cents: Optional[int]
    measured_mile_cost_cents: Optional[int]
    recovered_cost_cents: Optional[int]
    recovery_variant: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LiquidatedDamagesAssessment(TypedDict, total=False):
    id: str
    project_id: str
    assessment_period_start: str
    assessment_period_end: str
    culpable_days: Optional[int]
    gross_ld_cents: Optional[int]
    assessed_ld_cents: Optional[int]
    prior_assessed_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
