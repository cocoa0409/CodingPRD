"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    HRIS_ANALYST = "HrisAnalyst"
    DATA_STEWARD = "DataSteward"
    CHANGE_APPROVER = "ChangeApprover"
    INTEGRATION_OPERATOR = "IntegrationOperator"
    SECURITY_ADMIN = "SecurityAdmin"


class DataFieldStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class DataFieldSensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class DataFieldHistoryPolicy(str, Enum):
    CORRECTABLE = "CORRECTABLE"
    APPEND_ONLY = "APPEND_ONLY"


class Channel(str, Enum):
    PAYROLL = "PAYROLL"
    BENEFITS = "BENEFITS"
    IDENTITY = "IDENTITY"


class PositionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class RowStatus(str, Enum):
    FUTURE = "FUTURE"
    ACTIVE = "ACTIVE"
    HISTORY = "HISTORY"
    VOIDED = "VOIDED"


class ChangeRequestStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class TargetType(str, Enum):
    WORKER_FIELD = "WORKER_FIELD"
    POSITION_FIELD = "POSITION_FIELD"
    POSITION_HIERARCHY = "POSITION_HIERARCHY"


class CorrectionMode(str, Enum):
    NEW_RECORD = "NEW_RECORD"
    CORRECT_HISTORY = "CORRECT_HISTORY"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    ROLLED_BACK = "ROLLED_BACK"


class BatchLineStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"


class EventType(str, Enum):
    CHANGE_APPLIED = "CHANGE_APPLIED"
    CORRECTION_PROPAGATED = "CORRECTION_PROPAGATED"
    REVERSAL = "REVERSAL"


class EventStatus(str, Enum):
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class RuleType(str, Enum):
    RANGE = "RANGE"
    REQUIRED = "REQUIRED"
    REGEX = "REGEX"


class RuleSeverity(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class RoleCode(str, Enum):
    HRIS_ANALYST = "HRIS_ANALYST"
    DATA_STEWARD = "DATA_STEWARD"
    CHANGE_APPROVER = "CHANGE_APPROVER"
    INTEGRATION_OPERATOR = "INTEGRATION_OPERATOR"
    SECURITY_ADMIN = "SECURITY_ADMIN"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    PROVISIONED = "PROVISIONED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AuditAction(str, Enum):
    APPLY = "APPLY"
    CORRECT = "CORRECT"
    VOID = "VOID"
    BATCH_APPLY = "BATCH_APPLY"
    BATCH_VOID = "BATCH_VOID"
    GRANT_APPROVE = "GRANT_APPROVE"
    GRANT_REVOKE = "GRANT_REVOKE"


# --- Entity TypedDicts (common_fields: true unless noted) ---


class DataField(TypedDict):
    id: str
    field_key: str
    display_name: str
    sensitivity: str
    history_policy: str
    downstream_channels: list
    owner_team: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict):
    id: str
    title: str
    department: str
    parent_position_id: Optional[str]
    headcount_budget: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    legal_name: str
    worker_number: str
    hire_date: str
    initial_position_id: str
    initial_salary_cents: int
    status: str
    termination_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PositionAssignment(TypedDict):
    id: str
    worker_id: str
    change_request_id: Optional[str]
    position_id: str
    salary_cents: int
    pay_grade: Optional[str]
    location_code: Optional[str]
    effective_start_date: str
    effective_end_date: Optional[str]
    row_status: str
    created_at: str
    updated_at: str
    version: int


class ChangeRequest(TypedDict):
    id: str
    target_type: str
    target_worker_id: Optional[str]
    target_position_id: Optional[str]
    target_field_id: str
    new_value: str
    effective_date: Optional[str]
    correction_mode: str
    target_row_id: Optional[str]
    propagate_correction: bool
    status: str
    created_by: str
    approver_1_id: Optional[str]
    approver_2_id: Optional[str]
    prior_value: Optional[str]
    prior_row_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MassChangeBatch(TypedDict):
    id: str
    name: str
    status: str
    scheduled_effective_date: Optional[str]
    total_lines: int
    applied_lines: int
    failed_lines: int
    total_delta_cents: int
    created_at: str
    updated_at: str
    version: int


class BatchLine(TypedDict):
    id: str
    batch_id: str
    line_index: int
    target_worker_id: str
    target_field_id: str
    new_value: str
    effective_date: str
    status: str
    error_id: Optional[str]
    resolved_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class IntegrationEvent(TypedDict):
    id: str
    event_type: str
    channel: str
    worker_id: str
    change_request_id: Optional[str]
    batch_id: Optional[str]
    status: str
    retry_count: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataQualityRule(TypedDict):
    id: str
    target_field_id: str
    rule_type: str
    severity: str
    param_min: Optional[int]
    param_max: Optional[int]
    param_pattern: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExceptionRecord(TypedDict):
    id: str
    rule_id: Optional[str]
    change_request_id: Optional[str]
    batch_id: Optional[str]
    integration_event_id: Optional[str]
    worker_id: str
    field_id: Optional[str]
    observed_value: str
    status: str
    priority_score: int
    waiver_expiry_date: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurityRoleAssignment(TypedDict):
    id: str
    user_id: str
    role_code: str
    scope_department: str
    valid_from: str
    valid_until: str
    status: str
    approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEntry(TypedDict):
    # Append-only log: id + created_at only; no updated_at, no version.
    id: str
    actor_id: str
    action: str
    worker_id: Optional[str]
    field_id: Optional[str]
    change_request_id: Optional[str]
    batch_id: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    created_at: str
