"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    EHS_MANAGER = "EHSManager"
    WASTE_COORDINATOR = "WasteCoordinator"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    TRANSPORTER_AGENT = "TransporterAgent"
    TSDF_AGENT = "TSDFAgent"


class GeneratorCategory(str, Enum):
    VSQG = "VSQG"
    SQG = "SQG"
    LQG = "LQG"


class WasteStreamStatus(str, Enum):
    DRAFT = "DRAFT"
    CHARACTERIZED = "CHARACTERIZED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PhysicalState(str, Enum):
    LIQUID = "LIQUID"
    SOLID = "SOLID"
    SLUDGE = "SLUDGE"
    GAS = "GAS"


class AreaType(str, Enum):
    SATELLITE = "SATELLITE"
    CENTRAL_90DAY = "CENTRAL_90DAY"


class ContainerStatus(str, Enum):
    ACCUMULATING_AT_SATELLITE = "ACCUMULATING_AT_SATELLITE"
    SATELLITE_LIMIT_EXCEEDED = "SATELLITE_LIMIT_EXCEEDED"
    IN_CENTRAL_ACCUMULATION = "IN_CENTRAL_ACCUMULATION"
    STAGED_FOR_SHIPMENT = "STAGED_FOR_SHIPMENT"
    SHIPPED = "SHIPPED"
    EMPTIED = "EMPTIED"
    VOIDED = "VOIDED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PartnerType(str, Enum):
    TRANSPORTER = "TRANSPORTER"
    TSDF = "TSDF"


class PartnerStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"


class AuditOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATOR_SIGNED = "GENERATOR_SIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    DISCREPANCY_RAISED = "DISCREPANCY_RAISED"
    RETURNED = "RETURNED"
    EXCEPTION_REQUIRED = "EXCEPTION_REQUIRED"
    EXCEPTION_REPORT_FILED = "EXCEPTION_REPORT_FILED"


class BiennialReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class ReviewOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


# --- Entity payloads (PRD §2.4 common fields: id, created_at, updated_at, version) ---

class GeneratorSite(TypedDict, total=False):
    id: str
    name: str
    epa_id_number: str
    current_month_key: str
    current_month_generated_kg: float
    generator_category: str
    open_exception_count: int
    open_discrepancy_count: int
    created_at: str
    updated_at: str
    version: int


class WasteStream(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    waste_codes: List[str]
    physical_state: str
    status: str
    is_hazardous: bool
    flash_point_c: Optional[float]
    ph: Optional[float]
    ldr_treatment_standard: str
    characterization_version: int
    total_generated_kg: float
    created_at: str
    updated_at: str
    version: int


class AccumulationArea(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    area_type: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    waste_stream_id: str
    accumulation_area_id: str
    site_id: str
    quantity_gallons: float
    quantity_kg: float
    status: str
    accumulation_start_date: Optional[str]
    deadline_days: Optional[int]
    accumulation_deadline_at: Optional[str]
    is_accumulation_overdue: bool
    satellite_exceeded_at: Optional[str]
    move_deadline_at: Optional[str]
    is_move_late: bool
    is_labeled: bool
    label_text: Optional[str]
    label_accumulation_start_marked: Optional[str]
    last_inspected_at: Optional[str]
    is_inspection_overdue: bool
    last_action_user_id: str
    created_by_user_id: str
    shipped_manifest_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContainerInspection(TypedDict, total=False):
    id: str
    container_id: str
    inspector_user_id: str
    inspected_at: str
    result: str
    deficiency_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WastePartner(TypedDict, total=False):
    id: str
    partner_type: str
    name: str
    epa_id_number: str
    permitted_waste_codes: List[str]
    status: str
    created_by_user_id: str
    audit_coverage_start: Optional[str]
    audit_coverage_end: Optional[str]
    is_audit_current: bool
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict, total=False):
    id: str
    waste_partner_id: str
    auditor_user_id: str
    audited_at: str
    coverage_from: str
    coverage_to: str
    outcome: str
    created_at: str
    updated_at: str
    version: int


class Manifest(TypedDict, total=False):
    id: str
    site_id: str
    transporter_id: str
    tsdf_id: str
    manifest_tracking_number: str
    line_items: List[dict]
    status: str
    created_by_user_id: str
    generator_signed_by_user_id: Optional[str]
    shipped_at: Optional[str]
    return_due_at: Optional[str]
    delivered_at: Optional[str]
    returned_at: Optional[str]
    is_return_late: bool
    exception_note: Optional[str]
    total_quantity_kg: float
    tonnage_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class LDRNotification(TypedDict, total=False):
    # Immutable notice: carries id + created_at only (no updated_at, no version).
    id: str
    manifest_id: str
    treatment_standard_codes: List[str]
    certification_statement: str
    notified_at: str
    created_at: str


class BiennialReport(TypedDict, total=False):
    id: str
    site_id: str
    report_year: int
    period_start: str
    period_end: str
    due_at: str
    status: str
    category_snapshot: str
    provisional_shipped_kg: float
    final_shipped_kg: float
    provisional_fee_cents: int
    final_fee_cents: int
    is_late: bool
    days_late: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
