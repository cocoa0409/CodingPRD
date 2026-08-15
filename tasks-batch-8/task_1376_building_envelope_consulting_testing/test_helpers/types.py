"""Domain types: entity TypedDicts, status enums, role enum.

Resources carry the standard system-managed fields (id, created_at,
updated_at, version) described in PRD section 2.10, except LitigationHold
and Invoice, which expose only id and created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PRINCIPAL = "Principal"
    CONSULTANT = "Consultant"
    REVIEWER = "Reviewer"
    FIELD_TECHNICIAN = "FieldTechnician"
    MANUFACTURER_REP = "ManufacturerRep"


class EngagementStatus(str, Enum):
    SETUP = "SETUP"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSE_OUT = "CLOSE_OUT"
    CLOSED = "CLOSED"


class EngagementPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AssemblyType(str, Enum):
    CURTAIN_WALL = "CURTAIN_WALL"
    WINDOW_WALL = "WINDOW_WALL"
    MASONRY = "MASONRY"
    ROOFING = "ROOFING"
    PLAZA_DECK = "PLAZA_DECK"


class AssemblyReviewStatus(str, Enum):
    NONE = "NONE"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BarrierLayer(str, Enum):
    AIR = "AIR"
    WATER = "WATER"
    THERMAL = "THERMAL"


class DesignReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMMENTS_ISSUED = "COMMENTS_ISSUED"
    REVISED = "REVISED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChamberSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class MockUpStatus(str, Enum):
    PLANNED = "PLANNED"
    CONSTRUCTING = "CONSTRUCTING"
    READY_FOR_TEST = "READY_FOR_TEST"
    TESTING = "TESTING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REMEDIATED = "REMEDIATED"


class TestMethod(str, Enum):
    ASTM_E1105 = "ASTM_E1105"
    ASTM_E783 = "ASTM_E783"
    AAMA_502 = "AAMA_502"


class FieldTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FieldTestExecutionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    RESULT_RECORDED = "RESULT_RECORDED"
    CERTIFIED = "CERTIFIED"


class FieldTestDiagnosisStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    UNDIAGNOSED = "UNDIAGNOSED"
    DIAGNOSING = "DIAGNOSING"
    DIAGNOSED = "DIAGNOSED"


class SurveyType(str, Enum):
    THERMAL_IMAGING = "THERMAL_IMAGING"
    MOISTURE = "MOISTURE"
    COMBINED = "COMBINED"


class SurveyStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    ANALYZED = "ANALYZED"
    VOID = "VOID"


class AnomalyType(str, Enum):
    WATER_INGRESS = "WATER_INGRESS"
    AIR_LEAKAGE = "AIR_LEAKAGE"
    THERMAL_BRIDGE = "THERMAL_BRIDGE"
    MOISTURE_TRAP = "MOISTURE_TRAP"


class AnomalySeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AnomalyStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    DISMISSED = "DISMISSED"
    REMEDIATED = "REMEDIATED"


class RemediationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_MANUFACTURER_REVIEW = "UNDER_MANUFACTURER_REVIEW"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class LitigationHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class MaintenanceVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class Engagement(TypedDict, total=False):
    id: str
    name: str
    client_name: str
    fee_cap_cents: int
    labor_rate_cents_per_hour: int
    recognized_fees_cents: int
    invoiced_cents: int
    fee_headroom_cents: int
    risk_score: int
    posture: str
    status: str
    litigation_hold_active: bool
    created_at: str
    updated_at: str
    version: int


class Assembly(TypedDict, total=False):
    id: str
    engagement_id: str
    tag: str
    assembly_type: str
    design_u_factor: float
    required_airtightness_lps_m2: float
    review_status: str
    created_at: str
    updated_at: str
    version: int


class DesignReview(TypedDict, total=False):
    id: str
    engagement_id: str
    assembly_id: str
    barrier_scope: List[str]
    drawing_count: int
    revision_round: int
    reviewer_id: Optional[str]
    review_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChamberSlot(TypedDict, total=False):
    id: str
    engagement_id: str
    chamber_code: str
    start_date: str
    end_date: str
    daily_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MockUp(TypedDict, total=False):
    id: str
    engagement_id: str
    assembly_id: str
    chamber_slot_id: str
    specimen_count: int
    air_leakage_lps_m2: Optional[float]
    testing_fee_cents: Optional[int]
    attempt_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldTest(TypedDict, total=False):
    id: str
    engagement_id: str
    assembly_id: str
    test_method: str
    test_date: str
    test_pressure_pa: int
    measured_leakage_lps_m2: Optional[float]
    performed_by: Optional[str]
    certified_by: Optional[str]
    result: Optional[str]
    execution_status: str
    diagnosis_status: str
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict, total=False):
    id: str
    engagement_id: str
    assembly_id: str
    survey_type: str
    survey_date: str
    ambient_delta_t_c: float
    anomaly_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Anomaly(TypedDict, total=False):
    id: str
    engagement_id: str
    field_test_id: Optional[str]
    survey_id: Optional[str]
    anomaly_type: str
    severity: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict, total=False):
    id: str
    engagement_id: str
    anomaly_ids: List[str]
    spec_sections: List[str]
    estimated_cost_cents: Optional[int]
    actual_cost_cents: Optional[int]
    plan_status: str
    supersedes_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    engagement_id: str
    anomaly_id: str
    manufacturer_name: str
    claimed_amount_cents: int
    recovered_amount_cents: int
    filed_at: str
    response_due_at: str
    claim_status: str
    created_at: str
    updated_at: str
    version: int


# Reduced property set (PRD section 2.10): only id and created_at.
class LitigationHold(TypedDict, total=False):
    id: str
    engagement_id: str
    matter_reference: str
    hold_status: str
    created_at: str


class MaintenanceVisit(TypedDict, total=False):
    id: str
    engagement_id: str
    visit_label: str
    window_start_date: str
    window_end_date: str
    buffer_days: int
    visit_status: str
    created_at: str
    updated_at: str
    version: int


# Reduced property set (PRD section 2.10): only id and created_at.
class Invoice(TypedDict, total=False):
    id: str
    engagement_id: str
    labor_hours: float
    expense_cents: int
    discount_pct: float
    subtotal_cents: int
    total_cents: int
    invoice_status: str
    created_at: str
