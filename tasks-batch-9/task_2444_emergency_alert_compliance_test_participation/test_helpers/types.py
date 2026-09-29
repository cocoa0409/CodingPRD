"""Domain types: status enums, role enum and entity TypedDicts.

Note on audit fields (PRD §2.5): most resources carry ``updated_at`` and
``version``; ``WirelessAlertNotice`` and ``TestLogEntry`` are immutable once
written and expose only ``id`` and ``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    STATION_ENGINEER = "StationEngineer"
    CERTIFYING_OFFICER = "CertifyingOfficer"
    FIELD_INSPECTOR = "FieldInspector"


class StatePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RelayRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CompliancePosture(str, Enum):
    PROVISIONING = "PROVISIONING"
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    SUSPENDED_FILINGS = "SUSPENDED_FILINGS"


class ComplianceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


class DeviceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    READY = "READY"
    FAILED = "FAILED"
    DECOMMISSIONED = "DECOMMISSIONED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SILENT = "SILENT"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class OutageStatus(str, Enum):
    OPEN = "OPEN"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    RESTORED = "RESTORED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    CLOSED = "CLOSED"


class RelayState(str, Enum):
    RECEIVED = "RECEIVED"
    RELAY_PENDING = "RELAY_PENDING"
    RELAYED = "RELAYED"
    UNMATCHED_OPTIONAL = "UNMATCHED_OPTIONAL"
    SUPPRESSED_DUPLICATE = "SUPPRESSED_DUPLICATE"


class AccessibilityState(str, Enum):
    UNVERIFIED = "ACCESSIBILITY_UNVERIFIED"
    PASSED = "ACCESSIBILITY_PASSED"
    FAILED = "ACCESSIBILITY_FAILED"


class SuppressionSource(str, Enum):
    NONE = "NONE"
    STATION_REPEAT = "STATION_REPEAT"
    WIRELESS_NOTICE = "WIRELESS_NOTICE"


class RelayClassApplied(str, Enum):
    NONE = "NONE"
    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"


class TestEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    READINESS_PENDING = "READINESS_PENDING"
    READY = "READY"
    LOGGED = "LOGGED"
    FILED = "FILED"
    FAILED_UNFILED = "FAILED_UNFILED"


class FilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REVERSED = "REVERSED"


class InspectionStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_DRAFTED = "RESPONSE_DRAFTED"
    RESPONDED = "RESPONDED"
    CLOSED_SATISFIED = "CLOSED_SATISFIED"
    CLOSED_DEFICIENT = "CLOSED_DEFICIENT"


# ---------------------------------------------------------------------------
# Entity shapes — resources carrying the full audit set (PRD §2.5)
# ---------------------------------------------------------------------------
class StatePlan(TypedDict):
    id: str
    state_code: str
    plan_version_label: str
    required_source_types: List[str]
    required_source_count: int
    mandatory_relay_event_codes: List[str]
    status: str
    activated_at: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    state_plan_id: str
    call_sign: str
    service_type: str
    engineer_user_ids: List[str]
    certification_officer_user_id: str
    compliance_posture: str
    compliance_score: Optional[float]
    compliance_variant_applied: Optional[str]
    accessible_source_count: int
    silent_assignment_count: int
    penalty_points_total: float
    plan_revalidation_required: bool
    public_file_document_count: int
    last_log_review_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RelayRule(TypedDict):
    id: str
    state_plan_id: str
    event_code: str
    fips_codes: List[str]
    relay_class: str
    priority: int
    forward_delay_seconds: int
    specificity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EASDevice(TypedDict):
    id: str
    station_id: str
    model_code: str
    device_role: str
    firmware_version: str
    status: str
    readiness_check_passed: bool
    last_readiness_check_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringAssignment(TypedDict):
    id: str
    station_id: str
    device_id: str
    source_type: str
    source_call_sign: str
    status: str
    counts_toward_required_sources: bool
    last_receipt_at: Optional[str]
    silence_flagged_at: Optional[str]
    superseded_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentOutage(TypedDict):
    id: str
    device_id: str
    detected_at: str
    notified_at: str
    failure_summary: str
    status: str
    repair_started_at: Optional[str]
    restored_at: Optional[str]
    repair_cycle_count: int
    continuous_downtime_hours: Optional[float]
    obligation_downtime_hours: Optional[float]
    continuous_clock_breached: bool
    obligation_breached: bool
    verification_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlertEvent(TypedDict):
    id: str
    station_id: str
    event_code: str
    originator_sequence: str
    fips_codes: List[str]
    received_at: str
    relay_state: str
    matched_relay_rule_id: Optional[str]
    relay_class_applied: str
    forward_delay_seconds_applied: int
    suppression_source: str
    suppression_reference_alert_id: Optional[str]
    accessibility_state: str
    visual_crawl_seconds: Optional[int]
    audio_loudness_lufs: Optional[float]
    caption_interaction: Optional[str]
    accessibility_deficiency_points: Optional[float]
    created_at: str
    updated_at: str
    version: int


class TestEvent(TypedDict):
    id: str
    station_id: str
    test_type: str
    window_start_at: str
    window_end_at: str
    filing_deadline_at: str
    status: str
    readiness_score: Optional[float]
    readiness_evaluated_at: Optional[str]
    logged_entry_count: int
    retention_until_max: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FilingRecord(TypedDict):
    id: str
    test_event_id: str
    filed_by_user_id: str
    filed_at: str
    attestation_note: str
    status: str
    late_days: int
    entry_subtotal_points: float
    lateness_points: float
    unconfirmed_relay_points: float
    penalty_points: float
    reversal_reason: Optional[str]
    superseded_filing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionRequest(TypedDict):
    id: str
    station_id: str
    requested_document_kinds: List[str]
    provided_document_kinds: List[str]
    requested_at: str
    response_due_at: str
    responded_at: Optional[str]
    completeness_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable resources — id + created_at only, no updated_at and no version
# ---------------------------------------------------------------------------
class WirelessAlertNotice(TypedDict):
    id: str
    station_id: str
    originator_sequence: str
    event_code: str
    wea_sent_at: str
    fips_codes: List[str]
    created_at: str


class TestLogEntry(TypedDict):
    id: str
    test_event_id: str
    device_id: str
    entry_kind: str
    source_call_sign: Optional[str]
    logged_by_user_id: str
    logged_at: str
    retention_days_applied: int
    retention_until: str
    created_at: str
