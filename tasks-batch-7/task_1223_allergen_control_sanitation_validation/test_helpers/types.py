"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common system-managed fields described in PRD
"Common Resource Properties": id, created_at, updated_at, version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    QA_MANAGER = "QaManager"
    QA_SUPERVISOR = "QaSupervisor"
    QA_TECHNICIAN = "QaTechnician"
    LINE_OPERATOR = "LineOperator"
    AUDITOR = "Auditor"


class RegulatoryClass(str, Enum):
    MAJOR_9 = "MAJOR_9"
    SESAME = "SESAME"
    SULFITE = "SULFITE"
    OTHER = "OTHER"


class SanitationClass(str, Enum):
    WET_WASH = "WET_WASH"
    DRY_CLEAN = "DRY_CLEAN"
    ALLERGEN_DEDICATED = "ALLERGEN_DEDICATED"


class LinePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    HOLD = "HOLD"


class MatrixHandling(str, Enum):
    ALLOWED = "ALLOWED"
    REQUIRES_CHANGEOVER = "REQUIRES_CHANGEOVER"
    PROHIBITED = "PROHIBITED"


class ReworkClass(str, Enum):
    SAME_INTO_SAME = "SAME_INTO_SAME"
    SAME_ALLERGEN_PROFILE = "SAME_ALLERGEN_PROFILE"
    RESTRICTED_REWORK = "RESTRICTED_REWORK"
    NO_REWORK = "NO_REWORK"


class ProductionRunStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ChangeoverStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_EXECUTION = "IN_EXECUTION"
    SWAB_PENDING = "SWAB_PENDING"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    CANCELLED = "CANCELLED"


class ProcedureStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ProcedureMethod(str, Enum):
    FULL_WET_WASH = "FULL_WET_WASH"
    DRY_SCRAPE = "DRY_SCRAPE"
    PURGE = "PURGE"
    VACUUM_ONLY = "VACUUM_ONLY"


class SwabType(str, Enum):
    ATP = "ATP"
    ALLERGEN_PROTEIN = "ALLERGEN_PROTEIN"
    ALLERGEN_ELISA = "ALLERGEN_ELISA"


class SwabOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INVALIDATED = "INVALIDATED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SEPARATED = "SEPARATED"


class ReconciliationVerdict(str, Enum):
    MATCH = "MATCH"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    UNDECLARED_ALLERGEN = "UNDECLARED_ALLERGEN"
    OVER_DECLARED = "OVER_DECLARED"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ReworkBatchStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    COMMITTED = "COMMITTED"
    CONSUMED = "CONSUMED"
    SCRAPPED = "SCRAPPED"


class IncidentType(str, Enum):
    UNDECLARED_ALLERGEN = "UNDECLARED_ALLERGEN"
    LABEL_MISMATCH = "LABEL_MISMATCH"
    SWAB_FAILURE_CLUSTER = "SWAB_FAILURE_CLUSTER"
    SUPPLIER_ALLERGEN_CHANGE = "SUPPLIER_ALLERGEN_CHANGE"
    REWORK_RULE_BREACH = "REWORK_RULE_BREACH"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    CONTAINED = "CONTAINED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class FindingType(str, Enum):
    PROCEDURE_DEVIATION = "PROCEDURE_DEVIATION"
    DOCUMENTATION_GAP = "DOCUMENTATION_GAP"
    TRAINING_DEFICIENCY = "TRAINING_DEFICIENCY"
    SWAB_TECHNIQUE = "SWAB_TECHNIQUE"
    LABEL_CONTROL = "LABEL_CONTROL"


class FindingSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


class Allergen(TypedDict, total=False):
    id: str
    code: str
    display_name: str
    regulatory_class: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    line_code: str
    description: str
    sanitation_class: str
    posture: str
    last_validated_changeover_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    product_name: str
    allergen_set: List[str]
    rework_class: str
    label_revision: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class LineAllergenMatrixEntry(TypedDict, total=False):
    id: str
    line_id: str
    allergen_id: str
    handling: str
    changeover_minutes: int
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    line_id: str
    product_id: str
    planned_start_utc: str
    planned_end_utc: str
    introduced_allergens: List[str]
    changeover_required: bool
    scheduled_changeover_minutes: int
    label_revision_snapshot: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Changeover(TypedDict, total=False):
    id: str
    line_id: str
    from_run_id: Optional[str]
    to_run_id: str
    procedure_id: str
    scheduled_minutes: int
    actual_minutes: Optional[int]
    validation_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeoverProcedure(TypedDict, total=False):
    id: str
    procedure_code: str
    target_allergen_id: str
    method: str
    min_swab_zones: int
    atp_action_level_rlu: int
    allergen_action_level_ppm: float
    version_seq: int
    is_current: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SwabResult(TypedDict, total=False):
    id: str
    changeover_id: str
    zone_code: str
    swab_type: str
    measured_value: float
    action_level_used: float
    outcome: str
    invalidated_reason: Optional[str]
    recorded_by_id: str
    created_at: str
    updated_at: str
    version: int


class QaTechnician(TypedDict, total=False):
    id: str
    tech_code: str
    full_name: str
    certified_allergen_ids: List[str]
    certification_expiry_utc: str
    training_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LabelReconciliation(TypedDict, total=False):
    id: str
    run_id: str
    expected_label_revision: int
    printed_label_revision: int
    declared_allergens_on_label: List[str]
    missing_allergens: List[str]
    extra_allergens: List[str]
    verdict: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReworkBatch(TypedDict, total=False):
    id: str
    source_run_id: str
    source_product_id: str
    quantity_kg: float
    remaining_kg: float
    rework_allergen_set: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    incident_type: str
    severity: str
    line_id: Optional[str]
    product_id: Optional[str]
    allergen_id: Optional[str]
    source_label_reconciliation_id: Optional[str]
    source_changeover_id: Optional[str]
    description: str
    containment_action: Optional[str]
    root_cause: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    technician_id: str
    auditor_id: str
    finding_type: str
    severity: str
    points_deducted: int
    corrective_action_due_utc: str
    corrective_action_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
