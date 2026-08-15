"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    QUALITY_ENGINEER = "QualityEngineer"
    QUALITY_MANAGER = "QualityManager"
    PRODUCTION_OPERATOR = "ProductionOperator"
    SUPPLIER_QUALITY_ENGINEER = "SupplierQualityEngineer"
    REGULATORY_AFFAIRS = "RegulatoryAffairs"
    QMS_ADMIN = "QMSAdmin"


class DmrStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    OBSOLETE = "OBSOLETE"


class SupplierStatus(str, Enum):
    PENDING_QUALIFICATION = "PENDING_QUALIFICATION"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class PartStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    ON_HOLD = "ON_HOLD"
    DISQUALIFIED = "DISQUALIFIED"


class ScnStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ImpactClass(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    IQ_EXECUTION = "IQ_EXECUTION"
    IQ_REVIEW = "IQ_REVIEW"
    OQ_EXECUTION = "OQ_EXECUTION"
    OQ_REVIEW = "OQ_REVIEW"
    PQ_EXECUTION = "PQ_EXECUTION"
    PQ_REVIEW = "PQ_REVIEW"
    VALIDATED = "VALIDATED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"


class RevalidationReason(str, Enum):
    NONE = "NONE"
    TIME_EXPIRY = "TIME_EXPIRY"
    SUPPLIER_CHANGE = "SUPPLIER_CHANGE"
    CAPA_PROCESS_CHANGE = "CAPA_PROCESS_CHANGE"
    STUDY_FAILURE = "STUDY_FAILURE"


class StudyStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    INVALIDATED = "INVALIDATED"


class StudyType(str, Enum):
    REAL_TIME = "REAL_TIME"
    ACCELERATED = "ACCELERATED"


class DispositionStatus(str, Enum):
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    SCRAPPED = "SCRAPPED"
    RECALLED = "RECALLED"


class HoldStatus(str, Enum):
    CLEAR = "CLEAR"
    ON_HOLD = "ON_HOLD"


class HoldReason(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    NCR_OPEN = "NCR_OPEN"
    SUPPLIER_QUALITY = "SUPPLIER_QUALITY"
    REVALIDATION = "REVALIDATION"
    STERILITY_FAILURE = "STERILITY_FAILURE"
    FIELD_ACTION = "FIELD_ACTION"


class SterilityResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ExpiryBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class LabelStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PRINTED = "PRINTED"
    VOID = "VOID"


class VoidReason(str, Enum):
    NONE = "NONE"
    LOT_SCRAPPED = "LOT_SCRAPPED"
    LOT_RECALLED = "LOT_RECALLED"
    MANUAL = "MANUAL"


class NcrStatus(str, Enum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    DISPOSITIONED = "DISPOSITIONED"
    CLOSED = "CLOSED"


class NcrFault(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    INTERNAL = "INTERNAL"
    SUPPLIER = "SUPPLIER"


class NcrDisposition(str, Enum):
    NONE = "NONE"
    USE_AS_IS = "USE_AS_IS"
    REWORK = "REWORK"
    SCRAP = "SCRAP"
    RETURN_TO_SUPPLIER = "RETURN_TO_SUPPLIER"


class NcrSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    INVESTIGATED = "INVESTIGATED"
    CLOSED = "CLOSED"


class ComplaintSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    MINOR = "MINOR"
    SERIOUS_INJURY = "SERIOUS_INJURY"
    DEATH = "DEATH"


class CapaStatus(str, Enum):
    INITIATED = "INITIATED"
    INVESTIGATING = "INVESTIGATING"
    ACTION_PLANNED = "ACTION_PLANNED"
    IMPLEMENTING = "IMPLEMENTING"
    EFFECTIVENESS_CHECK = "EFFECTIVENESS_CHECK"
    CLOSED = "CLOSED"
    INEFFECTIVE = "INEFFECTIVE"


class CapaSourceType(str, Enum):
    COMPLAINT = "COMPLAINT"
    NCR = "NCR"
    AUDIT = "AUDIT"
    MANUAL = "MANUAL"


class FieldActionStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class FieldActionType(str, Enum):
    CORRECTION = "CORRECTION"
    REMOVAL = "REMOVAL"


class DeviceMasterRecord(TypedDict, total=False):
    id: str
    device_code: str
    revision_code: str
    revision_seq: int
    parent_dmr_id: Optional[str]
    sterile: bool
    shelf_life_claim_months: int
    confirmed_shelf_life_months: Optional[int]
    complaint_rate_per_100k: float
    field_action_review_required: bool
    author_user_id: str
    approver_user_id: Optional[str]
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ManufacturingLine(TypedDict, total=False):
    id: str
    line_code: str
    description: str
    changeover_buffer_hours: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    supplier_code: str
    name: str
    status: str
    quality_score: float
    quality_score_finalized: float
    applied_penalty_points: float
    applied_finalized_penalty_points: float
    risk_tier: str
    last_audit_completed_at: Optional[str]
    next_audit_due_at: str
    is_audit_overdue: bool
    created_at: str
    updated_at: str
    version: int


class QualityAgreement(TypedDict, total=False):
    id: str
    supplier_id: str
    agreement_code: str
    audit_rights_granted: bool
    audit_notice_days: int
    change_notice_days: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierPart(TypedDict, total=False):
    id: str
    supplier_id: str
    part_number: str
    description: str
    critical: bool
    quantity_received: int
    quantity_remaining: int
    quantity_committed: int
    quantity_in_released_lots: int
    quantity_in_scrapped_lots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierChangeNotification(TypedDict, total=False):
    id: str
    supplier_id: str
    supplier_part_id: Optional[str]
    change_description: str
    impact_class: str
    proposed_effective_date: str
    notified_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierAudit(TypedDict, total=False):
    id: str
    supplier_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    findings_count: int
    major_findings_count: int
    penalty_points: float
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValidationProtocol(TypedDict, total=False):
    id: str
    protocol_code: str
    dmr_id: str
    line_id: str
    planned_start: str
    planned_end: str
    status: str
    iq_executor_user_id: Optional[str]
    iq_approver_user_id: Optional[str]
    oq_executor_user_id: Optional[str]
    oq_approver_user_id: Optional[str]
    pq_executor_user_id: Optional[str]
    pq_approver_user_id: Optional[str]
    validated_at: Optional[str]
    revalidation_due_at: Optional[str]
    revalidation_reason: str
    generation: int
    created_at: str
    updated_at: str
    version: int


class SterileBarrierStudy(TypedDict, total=False):
    id: str
    dmr_id: str
    study_type: str
    claimed_months: int
    started_at: str
    status: str
    result_months_confirmed: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DeviceLot(TypedDict, total=False):
    id: str
    lot_number: str
    dmr_id: str
    validation_protocol_id: str
    quantity: int
    manufactured_at: str
    sample_qty: int
    releasable_qty: int
    expiry_date: str
    expiry_basis: str
    sterility_result: str
    disposition_status: str
    hold_status: str
    hold_reason: str
    created_at: str
    updated_at: str
    version: int


class LotComponent(TypedDict, total=False):
    id: str
    lot_id: str
    supplier_part_id: str
    quantity_used: int
    supplier_lot_number: str
    created_at: str
    updated_at: str
    version: int


class UDILabel(TypedDict, total=False):
    id: str
    lot_id: str
    udi_di: str
    udi_pi: str
    label_revision: str
    status: str
    printed_at: Optional[str]
    void_reason: str
    created_at: str
    updated_at: str
    version: int


class NonconformanceReport(TypedDict, total=False):
    id: str
    ncr_code: str
    lot_id: Optional[str]
    supplier_part_id: Optional[str]
    description: str
    severity: str
    fault: str
    disposition: str
    status: str
    initiator_user_id: str
    penalty_points_applied: float
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    complaint_code: str
    lot_id: str
    severity: str
    description: str
    confirmed: bool
    received_at: str
    investigator_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CAPA(TypedDict, total=False):
    id: str
    capa_code: str
    dmr_id: str
    source_type: str
    source_complaint_id: Optional[str]
    source_ncr_id: Optional[str]
    process_change: bool
    action_summary: Optional[str]
    initiator_user_id: str
    closer_user_id: Optional[str]
    effectiveness_cycles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldAction(TypedDict, total=False):
    id: str
    action_code: str
    dmr_id: str
    action_type: str
    scope_mfg_start: str
    scope_mfg_end: str
    reason_complaint_id: str
    issued_at: Optional[str]
    recalled_lot_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
