"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every entity carries the standard four
system-managed fields (id + created_at + updated_at + version) except the two
append-only records called out in the PRD common-resource-properties section:
DestructionCertificate and ReminderLog carry only id + created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RECORDS_MANAGER = "RecordsManager"
    LEGAL_COUNSEL = "LegalCounsel"
    AUDITOR = "Auditor"
    CUSTODIAN = "Custodian"


class TriggerBasis(str, Enum):
    EVENT_DATE = "EVENT_DATE"
    FISCAL_YEAR_END = "FISCAL_YEAR_END"


class AckSlaMode(str, Enum):
    STRICT = "STRICT"
    REMINDER_ADJUSTED = "REMINDER_ADJUSTED"


class DestructionMethod(str, Enum):
    SECURE_ERASE = "SECURE_ERASE"
    SHRED = "SHRED"
    CRYPTO_SHRED = "CRYPTO_SHRED"


class ResolutionStrategy(str, Enum):
    APPLY_LONGEST = "APPLY_LONGEST"
    APPLY_SHORTEST = "APPLY_SHORTEST"


class RetentionRuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PENDING_CONFLICT = "PENDING_CONFLICT"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class RetentionConflictStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class RecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DESTROYED = "DESTROYED"


class DispositionPosture(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    HELD = "HELD"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"
    ELIGIBLE = "ELIGIBLE"
    RETAINED = "RETAINED"


class LegalHoldStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class HoldCustodianStatus(str, Enum):
    AWAITING_ISSUANCE = "AWAITING_ISSUANCE"
    PENDING = "PENDING"
    ESCALATED = "ESCALATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class HoldScopeItemStatus(str, Enum):
    PENDING_ISSUANCE = "PENDING_ISSUANCE"
    ACTIVE = "ACTIVE"
    EXCLUDED = "EXCLUDED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class DispositionRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"


class DispositionItemStatus(str, Enum):
    PENDING = "PENDING"
    DESTROYED = "DESTROYED"
    SKIPPED_HELD = "SKIPPED_HELD"
    SKIPPED_ALREADY_DESTROYED = "SKIPPED_ALREADY_DESTROYED"


class HoldAuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FreezeWindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ReminderKind(str, Enum):
    ISSUED_NOTICE = "ISSUED_NOTICE"
    REMINDER = "REMINDER"
    ESCALATION = "ESCALATION"
    RELEASE_NOTICE = "RELEASE_NOTICE"
    CANCEL_NOTICE = "CANCEL_NOTICE"


class GovernanceProgram(TypedDict, total=False):
    id: str
    name: str
    fiscal_year_end_month: int
    fiscal_year_end_day: int
    ack_deadline_days: int
    reminder_interval_days: int
    max_reminders_before_escalation: int
    stale_hold_days: int
    over_preservation_warn_pct: float
    ack_sla_mode: str
    created_at: str
    updated_at: str
    version: int


class RecordClass(TypedDict, total=False):
    id: str
    program_id: str
    code: str
    name: str
    monthly_storage_cost_cents_per_gb: float
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    id: str
    program_id: str
    code: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Custodian(TypedDict, total=False):
    id: str
    program_id: str
    email: str
    full_name: str
    department: str
    open_obligation_count: int
    created_at: str
    updated_at: str
    version: int


class RetentionRule(TypedDict, total=False):
    id: str
    program_id: str
    record_class_id: str
    jurisdiction_id: str
    rule_code: str
    retention_months: int
    trigger_basis: str
    effective_from: str
    effective_to: Optional[str]
    supersedes_rule_id: Optional[str]
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RetentionConflict(TypedDict, total=False):
    id: str
    program_id: str
    record_class_id: str
    jurisdiction_id: str
    incumbent_rule_id: str
    challenger_rule_id: str
    governing_rule_id: Optional[str]
    resolution_strategy: Optional[str]
    resolution_justification: Optional[str]
    resolved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Record(TypedDict, total=False):
    id: str
    program_id: str
    record_class_id: str
    jurisdiction_id: str
    owner_custodian_id: Optional[str]
    title: str
    source_system: str
    event_date: str
    size_gb: float
    auto_delete_enabled: bool
    retention_due_date: Optional[str]
    governing_rule_id: Optional[str]
    active_hold_count: int
    auto_delete_suspended: bool
    disposition_posture: str
    destroyed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LegalHold(TypedDict, total=False):
    id: str
    program_id: str
    matter_ref: str
    title: str
    reason: str
    created_by_user_id: str
    issued_at: Optional[str]
    released_at: Optional[str]
    release_reason: Optional[str]
    last_activity_at: Optional[str]
    late_ack_count: int
    all_acknowledged: bool
    active_scope_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HoldCustodian(TypedDict, total=False):
    id: str
    hold_id: str
    custodian_id: str
    program_id: str
    ack_due_date: Optional[str]
    acknowledged_at: Optional[str]
    was_late: Optional[bool]
    reminder_count: int
    last_reminder_at: Optional[str]
    escalated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HoldScopeItem(TypedDict, total=False):
    id: str
    hold_id: str
    record_id: str
    program_id: str
    added_at: str
    activated_at: Optional[str]
    released_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DispositionRequest(TypedDict, total=False):
    id: str
    program_id: str
    requester_user_id: str
    method: str
    justification: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    executed_at: Optional[str]
    stale_item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DispositionItem(TypedDict, total=False):
    id: str
    request_id: str
    record_id: str
    program_id: str
    snapshot_posture: Optional[str]
    snapshot_due_date: Optional[str]
    snapshot_hold_count: Optional[int]
    destroyed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DestructionCertificate(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    program_id: str
    request_id: str
    disposition_item_id: str
    record_id: str
    record_title: str
    record_class_code: str
    jurisdiction_code: str
    retention_due_date: Optional[str]
    destroyed_at: str
    method: str
    content_hash: str
    witness_user_id: str
    certificate_seq: int
    created_at: str


class HoldAudit(TypedDict, total=False):
    id: str
    program_id: str
    active_hold_count: int
    stale_hold_count: int
    held_record_count: int
    eligible_record_count: int
    over_preserved_record_count: int
    over_preservation_pct: float
    over_preservation_cost_cents: int
    threshold_breached: bool
    closed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReminderLog(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    program_id: str
    hold_id: str
    hold_custodian_id: str
    custodian_id: str
    kind: str
    sent_at: str
    reminder_seq: int
    created_at: str


class DispositionFreezeWindow(TypedDict, total=False):
    id: str
    program_id: str
    start_at: str
    end_at: str
    reason: str
    cancelled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
