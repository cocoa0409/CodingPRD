"""Entity shapes, status vocabularies and the role enum for the trailer plant.

PRD 2.5 splits the entities in two. Most rows carry the full audit set of
`id`, `created_at`, `updated_at` and `version`; a frame inspection is the
deliberate exception and carries only `id` and `created_at`.
"""

from typing import Any, Dict, List, Optional, TypedDict


# --- Roles (PRD 2.1) -----------------------------------------------------
class Role:
    PLANT_ENGINEER = "PlantEngineer"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    WELD_SUPERVISOR = "WeldSupervisor"
    ASSEMBLY_TECH = "AssemblyTech"
    QUALITY_INSPECTOR = "QualityInspector"
    SALES_ADMIN = "SalesAdmin"
    DEALER = "Dealer"


ALL_ROLES = (
    Role.PLANT_ENGINEER,
    Role.CERTIFICATION_OFFICER,
    Role.WELD_SUPERVISOR,
    Role.ASSEMBLY_TECH,
    Role.QUALITY_INSPECTOR,
    Role.SALES_ADMIN,
    Role.DEALER,
)


# --- Status vocabularies -------------------------------------------------
class CertificationStatus:
    DRAFT = "DRAFT"
    IN_ENGINEERING_REVIEW = "IN_ENGINEERING_REVIEW"
    CERTIFIED = "CERTIFIED"
    WITHDRAWN = "WITHDRAWN"


class BuildStatus:
    PLANNED = "PLANNED"
    BUILD_HOLD = "BUILD_HOLD"
    JIG_RESERVED = "JIG_RESERVED"
    FRAME_REWORK = "FRAME_REWORK"
    FRAME_WELDED = "FRAME_WELDED"
    SYSTEMS_INSTALLED = "SYSTEMS_INSTALLED"
    SYSTEMS_REWORK = "SYSTEMS_REWORK"
    ROAD_TEST_PENDING = "ROAD_TEST_PENDING"
    ROAD_TEST_PASSED = "ROAD_TEST_PASSED"
    LABELED = "LABELED"
    RELEASED_TO_STOCK = "RELEASED_TO_STOCK"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"


class ComplianceStatus:
    NOT_VERIFIED = "NOT_VERIFIED"
    LIGHTING_VERIFIED = "LIGHTING_VERIFIED"
    FULLY_COMPLIANT = "FULLY_COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class ReservationStatus:
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class InspectionResult:
    PASS = "PASS"
    FAIL = "FAIL"


class OptionStatus:
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REMOVED = "REMOVED"


class RoadTestStatus:
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class LabelStatus:
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class DealerStatus:
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class OrderStatus:
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class FloorPlanStatus:
    NONE = "NONE"
    DRAWN = "DRAWN"
    RELEASED = "RELEASED"
    REPAID = "REPAID"


class ClaimStatus:
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    PARTS_SHIPPED = "PARTS_SHIPPED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"


class CoverageVariant:
    IN_WARRANTY_FULL = "IN_WARRANTY_FULL"
    GOODWILL_PRORATED = "GOODWILL_PRORATED"


class SystemsStage:
    LIGHTING = "LIGHTING"
    BRAKE_AND_AXLE = "BRAKE_AND_AXLE"


class CertificationDecision:
    CERTIFIED = "CERTIFIED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    WITHDRAWN = "WITHDRAWN"


class ClaimDecision:
    APPROVE = "APPROVE"
    DENY = "DENY"
    REQUEST_INFO = "REQUEST_INFO"


# --- Audit field groups (PRD 2.5) ---------------------------------------
FULL_AUDIT_FIELDS = ("id", "created_at", "updated_at", "version")
# A frame inspection carries only these two and has no update endpoint.
APPEND_ONLY_AUDIT_FIELDS = ("id", "created_at")


# --- Entity shapes -------------------------------------------------------
class TrailerModel(TypedDict, total=False):
    id: str
    model_code: str
    description: str
    axle_count: int
    axle_rating_lbs: int
    design_braked_axle_count: int
    tire_load_rating_lbs: int
    frame_design_code: str
    frame_design_rated_lbs: int
    coupler_rating_lbs: int
    overall_width_in: float
    nominal_length_mm: int
    nominal_width_mm: int
    base_curb_weight_lbs: int
    base_dealer_price_cents: int
    certification_status: str
    revision_round: int
    provisional_gvwr_lbs: Optional[int]
    certified_gvwr_lbs: Optional[int]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    active_unit_count: int
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict, total=False):
    id: str
    dealer_code: str
    name: str
    labor_rate_cents_per_hour: int
    floor_plan_limit_cents: int
    floor_plan_outstanding_cents: int
    floor_plan_available_cents: int
    allocation_quota_per_month: int
    allocations_current_month_count: int
    allocations_ytd_count: int
    warranty_receivable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeldJig(TypedDict, total=False):
    id: str
    jig_code: str
    frame_design_code: str
    changeover_buffer_min: int
    reserved_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class TestLane(TypedDict, total=False):
    id: str
    lane_code: str
    surface_type: str
    max_concurrent_tests: int
    created_at: str
    updated_at: str
    version: int


class TrailerUnit(TypedDict, total=False):
    id: str
    serial_number: str
    model_id: str
    planned_start_date: str
    build_status: str
    compliance_status: str
    model_version_pinned: Optional[int]
    gvwr_lbs: Optional[int]
    curb_weight_lbs: Optional[int]
    payload_capacity_lbs: Optional[int]
    dealer_order_id: Optional[str]
    installed_braked_axle_count: Optional[int]
    breakaway_kit_installed: Optional[bool]
    clearance_lamp_count: Optional[int]
    frame_fail_count: int
    rework_cycle_count: int
    released_to_stock_at: Optional[str]
    warranty_start_date: Optional[str]
    vin: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JigReservation(TypedDict, total=False):
    id: str
    jig_id: str
    unit_id: str
    window_start_at: str
    window_end_at: str
    occupancy_end_at: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FrameInspection(TypedDict, total=False):
    """PRD 2.5: carries only `id` and `created_at` — no updated_at, no version."""

    id: str
    unit_id: str
    inspection_seq: int
    measured_length_mm: int
    measured_width_mm: int
    diagonal_a_mm: int
    diagonal_b_mm: int
    critical_weld_defect_count: int
    non_critical_weld_defect_count: int
    length_deviation_mm: float
    width_deviation_mm: float
    max_deviation_mm: float
    squareness_delta_mm: float
    result: str
    failure_reasons: List[str]
    inspector_user_id: str
    created_at: str


class OptionInstall(TypedDict, total=False):
    id: str
    unit_id: str
    option_code: str
    quantity: int
    unit_weight_lbs: int
    unit_price_cents: int
    total_weight_lbs: int
    total_price_cents: int
    labor_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RoadTest(TypedDict, total=False):
    id: str
    unit_id: str
    lane_id: str
    window_start_at: str
    window_end_at: str
    protocol_code: str
    status: str
    brake_stop_distance_ft: Optional[float]
    lighting_check_passed: Optional[bool]
    result_notes: Optional[str]
    inspector_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificationLabel(TypedDict, total=False):
    id: str
    unit_id: str
    vin: str
    vin_sequence: int
    mco_number: str
    gvwr_lbs: int
    gawr_per_axle_lbs: int
    tire_size_code: str
    model_version_pinned: int
    issued_by_user_id: str
    issued_at: str
    status: str
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DealerOrder(TypedDict, total=False):
    id: str
    dealer_id: str
    model_id: str
    po_ref: str
    stocking_program: str
    status: str
    allocated_unit_id: Optional[str]
    invoice_subtotal_cents: Optional[int]
    volume_discount_pct: Optional[float]
    volume_discount_cents: Optional[int]
    freight_cents: Optional[int]
    invoice_total_cents: Optional[int]
    floor_plan_draw_cents: int
    floor_plan_status: str
    allocated_at: Optional[str]
    delivered_at: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    claim_ref: str
    unit_id: str
    dealer_id: str
    complaint_code: str
    labor_hours: float
    part_lines: List[Dict[str, Any]]
    part_line_count: int
    shipped_line_count: int
    failure_date: str
    status: str
    info_request_round: int
    coverage_variant: Optional[str]
    coverage_factor: Optional[float]
    labor_cents: Optional[int]
    parts_subtotal_cents: Optional[int]
    freight_cents: Optional[int]
    reimbursement_total_cents: Optional[int]
    tracking_number: Optional[str]
    reviewed_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
