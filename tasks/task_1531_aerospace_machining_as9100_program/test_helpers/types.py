"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CONTRACTS_MANAGER = "ContractsManager"
    SUPPLY_CHAIN_MANAGER = "SupplyChainManager"
    MANUFACTURING_PLANNER = "ManufacturingPlanner"
    QUALITY_INSPECTOR = "QualityInspector"
    MRB_MEMBER = "MRBMember"
    QUALITY_MANAGER = "QualityManager"
    CUSTOMER_QUALITY_REP = "CustomerQualityRep"
    SYSTEM_ADMIN = "SystemAdmin"


class LtaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PoStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FaiStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_INSPECTION = "IN_INSPECTION"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class FaiType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class CharacteristicResult(str, Enum):
    UNMEASURED = "UNMEASURED"
    PASS = "PASS"
    FAIL = "FAIL"


class SpcEvalStatus(str, Enum):
    NONE = "NONE"
    MONITORING = "MONITORING"
    CAPABLE = "CAPABLE"
    INCAPABLE = "INCAPABLE"


class WoStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_PRODUCTION = "IN_PRODUCTION"
    QUALITY_HOLD = "QUALITY_HOLD"
    FINAL_INSPECTION = "FINAL_INSPECTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SerialStatus(str, Enum):
    CREATED = "CREATED"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"
    QUARANTINED = "QUARANTINED"


class CertStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"


class SourceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"
    DISQUALIFIED = "DISQUALIFIED"


class ApprovalScope(str, Enum):
    RAW_MATERIAL = "RAW_MATERIAL"
    SPECIAL_PROCESS = "SPECIAL_PROCESS"
    DISTRIBUTOR = "DISTRIBUTOR"


class RiskRating(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProcessCode(str, Enum):
    HEAT_TREAT = "HEAT_TREAT"
    NDT = "NDT"
    PLATING = "PLATING"
    WELDING = "WELDING"
    SHOT_PEEN = "SHOT_PEEN"


class SpaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class NcrStatus(str, Enum):
    OPEN = "OPEN"
    MRB_REVIEW = "MRB_REVIEW"
    DISPOSITIONED = "DISPOSITIONED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"


class NcrDisposition(str, Enum):
    USE_AS_IS = "USE_AS_IS"
    REWORK = "REWORK"
    SCRAP = "SCRAP"
    RETURN_TO_SUPPLIER = "RETURN_TO_SUPPLIER"


class NcrOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_SPC = "AUTO_SPC"
    AUTO_COUNTERFEIT = "AUTO_COUNTERFEIT"


class EscapeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class DiaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class FlowdownClause(str, Enum):
    AS9102_FAI = "AS9102_FAI"
    AS9100D_QMS = "AS9100D_QMS"
    DFARS_COUNTERFEIT_PREVENTION = "DFARS_COUNTERFEIT_PREVENTION"
    CUSTOMER_SOURCE_INSPECTION = "CUSTOMER_SOURCE_INSPECTION"
    DELEGATED_INSPECTION_PERMITTED = "DELEGATED_INSPECTION_PERMITTED"


class AuditResult(str, Enum):
    READY = "READY"
    MARGINAL = "MARGINAL"
    NOT_READY = "NOT_READY"


# --- Entity TypedDicts (PRD §2.4 common fields: id, created_at, updated_at, version) ---

class LongTermAgreement(TypedDict, total=False):
    id: str
    customer_name: str
    ceiling_cents: int
    remaining_ceiling_cents: int
    pricing_tiers: List[dict]
    escalation_pct_per_year: float
    award_year: int
    rebate_tiers: List[dict]
    committed_monthly_rate_units: int
    consecutive_not_ready_count: int
    last_audit_month: Optional[str]
    last_audit_result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    lta_id: str
    po_number: str
    part_number: str
    part_revision: str
    quantity: int
    flowdown_clauses: List[str]
    requires_special_process: bool
    delivery_year: int
    unit_price_cents: int
    total_cents: int
    lta_version_pinned: int
    unreleased_quantity: int
    delivered_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FirstArticleInspection(TypedDict, total=False):
    id: str
    part_number: str
    part_revision: str
    fai_type: str
    status: str
    characteristic_count: int
    measured_count: int
    characteristics_complete: bool
    submitted_by_user_id: Optional[str]
    approved_revision: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BalloonedCharacteristic(TypedDict, total=False):
    id: str
    fai_id: str
    balloon_number: int
    nominal: float
    tolerance_plus: float
    tolerance_minus: float
    is_key_characteristic: bool
    usl: float
    lsl: float
    measured_value: Optional[float]
    result: str
    measured_by_user_id: Optional[str]
    spc_eval_status: str
    cpk_provisional: Optional[float]
    cpk_final: Optional[float]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    po_id: str
    quantity: int
    special_processes_required: List[str]
    status: str
    serials_created_count: int
    good_quantity: int
    scrapped_quantity: int
    spc_status: str
    requires_100pct_inspection: bool
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SerialNumber(TypedDict, total=False):
    id: str
    wo_id: str
    material_cert_id: str
    serial_number: str
    status: str
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialCert(TypedDict, total=False):
    id: str
    source_id: str
    heat_number: str
    material_spec: str
    quantity_received: int
    quantity_available: int
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ApprovedSource(TypedDict, total=False):
    id: str
    supplier_code: str
    approval_scope: str
    counterfeit_risk_rating: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialProcessApproval(TypedDict, total=False):
    id: str
    source_id: str
    process_code: str
    valid_from: str
    valid_to: str
    cert_reference: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NonconformanceReport(TypedDict, total=False):
    id: str
    wo_id: str
    defect_code: str
    description: str
    quantity_affected: int
    affected_serial_ids: List[str]
    detected_post_shipment: bool
    origin: str
    discovered_by_user_id: str
    disposition: Optional[str]
    disposition_by_user_id: Optional[str]
    estimated_cost_cents: Optional[int]
    actual_cost_cents: Optional[int]
    concession_approved: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EscapeReport(TypedDict, total=False):
    id: str
    ncr_id: str
    due_at: str
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DelegatedInspectionAuthority(TypedDict, total=False):
    id: str
    po_id: str
    inspector_user_id: str
    valid_from: str
    valid_to: str
    granted_by_user_id: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpcMeasurement(TypedDict, total=False):
    # Append-only observation (PRD §2.4): carries ONLY id + created_at as
    # system fields — no updated_at, no version.
    id: str
    wo_id: str
    characteristic_id: str
    measured_value: float
    recorded_by_user_id: str
    created_at: str
