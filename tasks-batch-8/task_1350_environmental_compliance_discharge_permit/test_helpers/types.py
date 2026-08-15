"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ENVIRONMENTAL_MANAGER = "EnvironmentalManager"
    FIELD_SAMPLER = "FieldSampler"
    LAB_ANALYST = "LabAnalyst"
    LAB_VALIDATOR = "LabValidator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FACILITY_INSPECTOR = "FacilityInspector"
    REGULATOR = "Regulator"
    SYSTEM_ADMIN = "SystemAdmin"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class CompliancePosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    UNDER_CORRECTIVE_ACTION = "UNDER_CORRECTIVE_ACTION"
    ENFORCEMENT = "ENFORCEMENT"


class OutfallStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LimitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RESCINDED = "RESCINDED"


class ParameterCode(str, Enum):
    BOD5 = "BOD5"
    TSS = "TSS"
    PH = "PH"
    AMMONIA_N = "AMMONIA_N"
    COPPER = "COPPER"
    FECAL_COLIFORM = "FECAL_COLIFORM"


class LimitType(str, Enum):
    DAILY_MAX = "DAILY_MAX"
    MONTHLY_AVG = "MONTHLY_AVG"


class Unit(str, Enum):
    MG_L = "MG_L"
    SU = "SU"
    MPN_100ML = "MPN_100ML"


class AverageMethod(str, Enum):
    ARITHMETIC = "ARITHMETIC"
    FLOW_WEIGHTED = "FLOW_WEIGHTED"


class MonitoringFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class ScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    CLOSED = "CLOSED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class CustodyStatus(str, Enum):
    NOT_SEALED = "NOT_SEALED"
    SEALED = "SEALED"
    IN_TRANSIT = "IN_TRANSIT"
    LAB_RECEIVED = "LAB_RECEIVED"
    ANALYZED = "ANALYZED"


class CustodyEventType(str, Enum):
    SEAL = "SEAL"
    TRANSFER = "TRANSFER"
    RECEIVE_LAB = "RECEIVE_LAB"
    ANALYSIS_START = "ANALYSIS_START"


class Qualifier(str, Enum):
    NONE = "NONE"
    BELOW_MDL = "BELOW_MDL"
    ESTIMATED = "ESTIMATED"


class ValidationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class NotificationStatus(str, Enum):
    PENDING_ORAL = "PENDING_ORAL"
    ORAL_OVERDUE = "ORAL_OVERDUE"
    ORAL_NOTIFIED = "ORAL_NOTIFIED"
    WRITTEN_OVERDUE = "WRITTEN_OVERDUE"
    WRITTEN_FILED = "WRITTEN_FILED"
    CLOSED = "CLOSED"


class EnforcementStatus(str, Enum):
    NONE = "NONE"
    ORDER_ISSUED = "ORDER_ISSUED"
    RESOLVED = "RESOLVED"


class DmrStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class CorrectiveActionSourceType(str, Enum):
    INSPECTION = "INSPECTION"
    EXCEEDANCE = "EXCEEDANCE"


class RenewalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ConsentOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ISSUED = "ISSUED"
    UNDER_APPEAL = "UNDER_APPEAL"
    FINAL = "FINAL"
    SATISFIED = "SATISFIED"


class AssessmentVariant(str, Enum):
    PER_DAY = "PER_DAY"
    ECONOMIC_BENEFIT = "ECONOMIC_BENEFIT"


class PaymentDirection(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources (PRD §2.4) carry id / created_at / updated_at / version.

class Permit(TypedDict, total=False):
    id: str
    permit_number: str
    facility_name: str
    receiving_water_body: str
    effective_date: str
    expiration_date: str
    status: str
    superseded_by_permit_id: Optional[str]
    compliance_posture: str
    open_corrective_action_count: int
    open_exceedance_count: int
    created_at: str
    updated_at: str
    version: int


class Outfall(TypedDict, total=False):
    id: str
    permit_id: str
    outfall_number: str
    description: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EffluentLimit(TypedDict, total=False):
    id: str
    outfall_id: str
    parameter_code: str
    limit_type: str
    limit_value: float
    unit: str
    average_method: str
    monitoring_frequency: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    supersedes_limit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SamplingEvent(TypedDict, total=False):
    id: str
    outfall_id: str
    parameter_code: str
    scheduled_for: str
    collection_window_hours: int
    schedule_status: str
    custody_status: str
    collected_at: Optional[str]
    collected_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabResult(TypedDict, total=False):
    id: str
    sampling_event_id: str
    parameter_code: str
    reported_value: float
    unit: str
    method_detection_limit: float
    qualifier: str
    flow_mgd: float
    analyzed_at: str
    analyzed_by_user_id: str
    validation_status: str
    validated_by_user_id: Optional[str]
    validated_at: Optional[str]
    rejection_reason: Optional[str]
    exceeds_limit: Optional[bool]
    exceedance_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Exceedance(TypedDict, total=False):
    id: str
    lab_result_id: str
    effluent_limit_id: str
    outfall_id: str
    parameter_code: str
    reported_value: float
    limit_value: float
    percent_over: float
    detected_at: str
    oral_notification_due_at: str
    written_report_due_at: str
    notification_status: str
    enforcement_status: str
    oral_notified_at: Optional[str]
    written_filed_at: Optional[str]
    corrective_action_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DmrSummaryLine(TypedDict, total=False):
    parameter_code: str
    sample_count: int
    avg_concentration: Optional[float]
    max_concentration: Optional[float]
    total_loading_kg: float
    exceeds_limit: bool


class DischargeMonitoringReport(TypedDict, total=False):
    id: str
    outfall_id: str
    period_start: str
    period_end: str
    due_date: str
    status: str
    prepared_by_user_id: str
    certified_by_user_id: Optional[str]
    submitted_at: Optional[str]
    is_late: bool
    required_sample_count: int
    total_validated_results: int
    monitoring_completeness_ratio: float
    summary_lines: List[DmrSummaryLine]
    deficiency_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StormwaterPlan(TypedDict, total=False):
    id: str
    permit_id: str
    plan_title: str
    version_label: str
    inspection_frequency_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    plan_id: str
    scheduled_for: str
    status: str
    inspector_user_id: str
    completed_at: Optional[str]
    findings: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict, total=False):
    id: str
    source_type: str
    inspection_id: Optional[str]
    exceedance_id: Optional[str]
    description: str
    severity: str
    deadline_at: str
    status: str
    is_overdue: bool
    resolved_at: Optional[str]
    resolved_by_user_id: Optional[str]
    actual_cost_cents: Optional[int]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalApplication(TypedDict, total=False):
    id: str
    permit_id: str
    proposed_expiration_date: str
    status: str
    submitted_at: str
    info_request_note: Optional[str]
    decision_reason: Optional[str]
    resulting_permit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentOrder(TypedDict, total=False):
    id: str
    exceedance_id: str
    assessment_variant: str
    base_penalty_cents: int
    daily_accrual_cents: int
    avoided_cost_cents: Optional[int]
    gravity_factor: Optional[float]
    statutory_cap_cents: int
    status: str
    issued_at: Optional[str]
    finalized_at: Optional[str]
    cure_date: Optional[str]
    accrued_days: int
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    paid_cents: int
    refunded_cents: int
    outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


# --- Append-only records (PRD §2.4): id + created_at ONLY --------------------
# These three deliberately omit updated_at and version.

class ChainOfCustodyRecord(TypedDict, total=False):
    id: str
    sampling_event_id: str
    event_type: str
    event_at: str
    from_party: Optional[str]
    to_party: Optional[str]
    note: Optional[str]
    sequence_index: int
    recorded_by_user_id: str
    created_at: str


class PenaltyPayment(TypedDict, total=False):
    id: str
    consent_order_id: str
    direction: str
    amount_cents: int
    posted_at: str
    status: str
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor_user_id: str
    actor_role: str
    occurred_at: str
    prev_entry_hash: str
    entry_hash: str
    created_at: str
