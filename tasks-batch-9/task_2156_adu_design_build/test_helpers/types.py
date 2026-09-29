"""Domain types for the ADU design-build API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DESIGN_LEAD = "DesignLead"
    PLAN_CHECKER = "PlanChecker"
    PROJECT_MANAGER = "ProjectManager"
    HOMEOWNER = "Homeowner"
    BUILDING_INSPECTOR = "BuildingInspector"
    FINANCE_ADVISOR = "FinanceAdvisor"


class ProjectStatus(str, Enum):
    INTAKE = "INTAKE"
    FEASIBILITY_CLEARED = "FEASIBILITY_CLEARED"
    PERMITTING = "PERMITTING"
    DESIGN_REVISION = "DESIGN_REVISION"
    PERMITTED = "PERMITTED"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    FINALED = "FINALED"


class FinancingState(str, Enum):
    UNFUNDED = "UNFUNDED"
    PRE_QUALIFIED = "PRE_QUALIFIED"
    COMMITTED = "COMMITTED"
    SHORTFALL = "SHORTFALL"


class Pathway(str, Enum):
    STATUTORY_MINISTERIAL = "STATUTORY_MINISTERIAL"
    LOCAL_ORDINANCE = "LOCAL_ORDINANCE"


class UnitType(str, Enum):
    DETACHED_NEW = "DETACHED_NEW"
    ATTACHED = "ATTACHED"
    CONVERSION = "CONVERSION"
    JADU = "JADU"


class ScreeningVerdict(str, Enum):
    PASS = "PASS"
    PASS_WITH_CONDITIONS = "PASS_WITH_CONDITIONS"
    FAIL = "FAIL"


class UtilityStatus(str, Enum):
    PENDING_DECISION = "PENDING_DECISION"
    SEPARATE_APPROVED = "SEPARATE_APPROVED"
    SHARED_APPROVED = "SHARED_APPROVED"
    ENERGIZED = "ENERGIZED"


class MeteringDecision(str, Enum):
    SEPARATE = "SEPARATE"
    SHARED = "SHARED"


class ServiceType(str, Enum):
    WATER = "WATER"
    SEWER = "SEWER"
    ELECTRIC = "ELECTRIC"


class SubmittalStatus(str, Enum):
    PREPARED = "PREPARED"
    UNDER_PLAN_CHECK = "UNDER_PLAN_CHECK"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"


class CorrectionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class CorrectionSeverity(str, Enum):
    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"


class CorrectionDiscipline(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    ENERGY = "ENERGY"
    FIRE = "FIRE"
    PLANNING = "PLANNING"
    UTILITY = "UTILITY"


class ScenarioStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    COMMITTED = "COMMITTED"


class AppraisalApproach(str, Enum):
    SALES_COMPARISON = "SALES_COMPARISON"
    INCOME_CAPITALIZATION = "INCOME_CAPITALIZATION"


class ProductType(str, Enum):
    HELOC = "HELOC"
    CASH_OUT_REFI = "CASH_OUT_REFI"
    RENOVATION_LOAN = "RENOVATION_LOAN"
    CONSTRUCTION_LOAN = "CONSTRUCTION_LOAN"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class PhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class PhaseCode(str, Enum):
    SITE_PREP = "SITE_PREP"
    FOUNDATION = "FOUNDATION"
    FRAMING = "FRAMING"
    ROUGH_MEP = "ROUGH_MEP"
    UTILITY_TIE_IN = "UTILITY_TIE_IN"
    INSULATION_DRYWALL = "INSULATION_DRYWALL"
    FINISHES = "FINISHES"


class DisruptionClass(str, Enum):
    NON_INVASIVE = "NON_INVASIVE"
    INVASIVE = "INVASIVE"
    UTILITY_SHUTOFF = "UTILITY_SHUTOFF"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PARTIAL = "PARTIAL"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InspectionType(str, Enum):
    FOUNDATION = "FOUNDATION"
    FRAMING = "FRAMING"
    ROUGH_MEP = "ROUGH_MEP"
    INSULATION = "INSULATION"
    FINAL = "FINAL"


class Certification(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    ENVELOPE = "ENVELOPE"
    FINAL = "FINAL"


class RentalClassification(str, Enum):
    LONG_TERM_ONLY = "LONG_TERM_ONLY"
    SHORT_TERM_PERMITTED = "SHORT_TERM_PERMITTED"
    RENTAL_PROHIBITED = "RENTAL_PROHIBITED"


# --- Entities carrying id + created_at + updated_at + version ---------------

class Jurisdiction(TypedDict):
    id: str
    name: str
    code: str
    local_max_detached_sqft: int
    local_rear_setback_ft: float
    local_side_setback_ft: float
    local_max_height_ft: float
    correction_response_days: int
    plan_check_base_fee_cents: int
    plan_check_rate_per_sqft_cents: int
    impact_fee_per_sqft_cents: int
    utility_capacity_fee_cents: int
    separate_meter_required: bool
    str_min_lease_days: int
    str_prohibited: bool
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    jurisdiction_id: str
    full_name: str
    certifications: List[str]
    daily_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    jurisdiction_id: str
    address_line: str
    lot_sqft: int
    existing_dwelling_sqft: int
    occupied: bool
    in_str_overlay: bool
    electrical_service_amps: int
    existing_water_meter_size_in: float
    pre_adu_value_cents: int
    existing_mortgage_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class AduProject(TypedDict):
    id: str
    property_id: str
    unit_type: str
    proposed_sqft: int
    proposed_height_ft: float
    rear_setback_ft: float
    side_setback_ft: float
    bedrooms: int
    contract_base_price_cents: int
    status: str
    financing_state: str
    approved_pathway: Optional[str]
    max_allowed_sqft: int
    contract_price_current_cents: int
    approved_change_days: int
    approved_change_order_count: int
    total_permit_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class UtilityConnection(TypedDict):
    id: str
    adu_project_id: str
    service_type: str
    status: str
    decision: Optional[str]
    separation_score: int
    separation_cost_cents: int
    energized_on_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitSubmittal(TypedDict):
    id: str
    adu_project_id: str
    design_sheet_count: int
    title24_compliant: bool
    design_revision: int
    status: str
    cycle_number: int
    submitted_on_date: Optional[str]
    correction_deadline_date: Optional[str]
    plan_check_component_cents: int
    impact_component_cents: int
    school_component_cents: int
    utility_component_cents: int
    total_permit_fee_cents: int
    approved_on_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectionItem(TypedDict):
    id: str
    permit_submittal_id: str
    discipline: str
    severity: str
    description: str
    status: str
    resolved_on_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancingScenario(TypedDict):
    id: str
    adu_project_id: str
    product_type: str
    appraisal_approach: str
    comparable_adjustment_cents: int
    projected_monthly_rent_cents: int
    status: str
    as_completed_value_cents: int
    max_loan_cents: int
    available_cents: int
    required_funds_cents: int
    funding_gap_cents: int
    appraisal_shortfall: bool
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    adu_project_id: str
    supersedes_change_order_id: Optional[str]
    title: str
    scope_items: List[str]
    cost_delta_cents: int
    schedule_delta_days: int
    status: str
    builder_fee_cents: int
    cumulative_change_pct_before: float
    cumulative_change_pct_after: float
    authored_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConstructionPhase(TypedDict):
    id: str
    adu_project_id: str
    depends_on_phase_id: Optional[str]
    phase_code: str
    disruption_class: str
    sequence_index: int
    status: str
    window_start_date: Optional[str]
    window_end_date: Optional[str]
    started_on_date: Optional[str]
    completed_on_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionAppointment(TypedDict):
    id: str
    adu_project_id: str
    construction_phase_id: str
    inspector_id: str
    inspection_type: str
    slot_date: str
    slot_start: str
    slot_end: str
    status: str
    result_notes: Optional[str]
    recorded_by_inspector_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Immutable records: only id + created_at (no updated_at, no version) ----

class FeasibilityScreening(TypedDict):
    id: str
    adu_project_id: str
    pathway: str
    max_allowed_sqft: int
    required_rear_setback_ft: float
    required_side_setback_ft: float
    required_height_ft: float
    required_service_amps: int
    zoning_ok: bool
    setback_ok: bool
    height_ok: bool
    utility_capacity_ok: bool
    verdict: str
    deficiency_codes: List[str]
    created_at: str


class OccupancyCertificate(TypedDict):
    id: str
    adu_project_id: str
    certificate_number: str
    issued_on_date: str
    final_inspection_passed_at: str
    rental_classification: str
    min_lease_days: int
    rental_ready: bool
    blocking_reasons: List[str]
    created_at: str
