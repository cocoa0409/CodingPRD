"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    SURVEY_TECHNICIAN = "SurveyTechnician"
    BUILDING_REPRESENTATIVE = "BuildingRepresentative"
    AHJ_INSPECTOR = "AHJInspector"
    SERVICE_MANAGER = "ServiceManager"
    SYSTEM_OPERATOR = "SystemOperator"


class OccupancyType(str, Enum):
    OCCUPIED = "OCCUPIED"
    VACANT = "VACANT"


class ProjectStatus(str, Enum):
    SURVEY = "SURVEY"
    SCOPING = "SCOPING"
    EXECUTION = "EXECUTION"
    CLOSEOUT = "CLOSEOUT"
    COMPLETED = "COMPLETED"


class DowntimePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ControllerTypeLegacy(str, Enum):
    RELAY = "RELAY"
    SOLID_STATE_ANALOG = "SOLID_STATE_ANALOG"
    MICROPROCESSOR = "MICROPROCESSOR"


class MachineType(str, Enum):
    GEARED = "GEARED"
    GEARLESS = "GEARLESS"
    MRL_GEARLESS = "MRL_GEARLESS"


class CarWorkStatus(str, Enum):
    SURVEY_PENDING = "SURVEY_PENDING"
    SURVEYED = "SURVEYED"
    SCOPED = "SCOPED"
    PROCURING = "PROCURING"
    OUTAGE_ACTIVE = "OUTAGE_ACTIVE"
    TESTING = "TESTING"
    ACCEPTED = "ACCEPTED"
    IN_WARRANTY = "IN_WARRANTY"
    UNDER_CONTRACT = "UNDER_CONTRACT"


class CarComplianceStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    TRIGGERS_OPEN = "TRIGGERS_OPEN"
    TRIGGERS_CLEARED = "TRIGGERS_CLEARED"
    CODE_ACCEPTED = "CODE_ACCEPTED"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    FAILED = "FAILED"
    NOT_OBSERVED = "NOT_OBSERVED"


class SurveyStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COUNTERSIGNED = "COUNTERSIGNED"
    VOID = "VOID"


class ScopeTier(str, Enum):
    CONTROLLER_ONLY = "CONTROLLER_ONLY"
    CONTROLLER_DOOR = "CONTROLLER_DOOR"
    CONTROLLER_MACHINE = "CONTROLLER_MACHINE"
    FULL_REPLACEMENT = "FULL_REPLACEMENT"


class ScopeOptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class CodeTriggerType(str, Enum):
    FIRE_SERVICE_PHASE_I_II = "FIRE_SERVICE_PHASE_I_II"
    SEISMIC_RESTRAINT = "SEISMIC_RESTRAINT"
    DOOR_PROTECTION_REOPENING = "DOOR_PROTECTION_REOPENING"
    MACHINE_BRAKE_MONITOR = "MACHINE_BRAKE_MONITOR"


class CodeTriggerStatus(str, Enum):
    REQUIRED = "REQUIRED"
    PRICED = "PRICED"
    WAIVED = "WAIVED"
    SATISFIED = "SATISFIED"


class ProcurementItemType(str, Enum):
    CONTROLLER = "CONTROLLER"
    MACHINE = "MACHINE"
    DOOR_OPERATOR = "DOOR_OPERATOR"
    POWER_UNIT = "POWER_UNIT"


class ProcurementOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    STAGED = "STAGED"
    INSTALLED = "INSTALLED"
    CANCELLED = "CANCELLED"


class StagingReservationStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class TemporaryServicePlan(str, Enum):
    STAIRS_ONLY = "STAIRS_ONLY"
    ADJACENT_CAR = "ADJACENT_CAR"
    ATTENDANT_SERVICE = "ATTENDANT_SERVICE"


class OutageWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectionAppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InspectionResult(str, Enum):
    PASSED = "PASSED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"


class WarrantyTransitionStatus(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    LAPSED = "LAPSED"


class MaintenanceContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class ScoreBasis(str, Enum):
    OBSERVED_ONLY = "OBSERVED_ONLY"
    IMPUTED_FAILED = "IMPUTED_FAILED"


class CreditBasis(str, Enum):
    THIRTY_360 = "THIRTY_360"
    ACTUAL_CALENDAR = "ACTUAL_CALENDAR"


class Jurisdiction(TypedDict):
    id: str
    name: str
    code_edition_year: int
    fire_service_required: bool
    seismic_zone: int
    door_protection_required: bool
    inspection_lead_days: int
    witness_test_required: bool
    reinspection_extension_hours: int
    permit_surcharge_pct: float
    created_at: str
    updated_at: str
    version: int


class ModernizationProject(TypedDict):
    id: str
    jurisdiction_id: str
    building_name: str
    occupancy_type: str
    contract_value_cents: int
    staging_area_sqft: int
    max_concurrent_outages: int
    outage_buffer_hours: int
    tenant_notice_lead_hours: int
    status: str
    car_count: int
    approved_scope_value_cents: int
    staging_committed_sqft: int
    active_outage_count: int
    downtime_posture: str
    created_at: str
    updated_at: str
    version: int


class ElevatorGroup(TypedDict):
    id: str
    project_id: str
    group_label: str
    min_cars_in_service: int
    car_count: int
    cars_in_service: int
    created_at: str
    updated_at: str
    version: int


class ElevatorCar(TypedDict):
    id: str
    project_id: str
    group_id: str
    car_designation: str
    rated_load_lbs: int
    controller_type_legacy: str
    machine_type: str
    duty_rank: int
    work_status: str
    compliance_status: str
    condition_score: Optional[float]
    recommended_scope_tier: Optional[str]
    approved_scope_option_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentSurvey(TypedDict):
    id: str
    car_id: str
    surveyed_by_user_id: str
    countersigned_by_user_id: Optional[str]
    controller_condition: str
    machine_condition: str
    door_equipment_condition: str
    provisional_score: Optional[float]
    final_score: Optional[float]
    recommended_scope_tier: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScopeOption(TypedDict):
    id: str
    car_id: str
    tier: str
    base_price_cents: int
    code_upgrade_cents: int
    max_lead_time_days: int
    escalation_pct: float
    escalation_fee_cents: int
    volume_discount_pct: float
    volume_discount_cents: int
    total_price_cents: int
    revision_count: int
    rejection_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CodeTrigger(TypedDict):
    id: str
    scope_option_id: str
    trigger_type: str
    source_rule: str
    status: str
    cost_cents: int
    waiver_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcurementOrder(TypedDict):
    id: str
    scope_option_id: str
    item_type: str
    lead_time_days: int
    required_staging_sqft: int
    ordered_at: Optional[str]
    promised_delivery_date: Optional[str]
    staging_reservation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StagingReservation(TypedDict):
    id: str
    procurement_order_id: str
    sqft: int
    hold_start: str
    hold_end: str
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutageWindow(TypedDict):
    id: str
    car_id: str
    predecessor_window_id: Optional[str]
    start_at: str
    end_at: str
    extension_hours: int
    temporary_service_plan: str
    advance_notice_sent_at: Optional[str]
    notice_count: int
    notice_lead_hours: Optional[float]
    status: str
    activated_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionAppointment(TypedDict):
    id: str
    car_id: str
    requested_date: str
    witness_requested: bool
    scheduled_at: Optional[str]
    recorded_by_jurisdiction_id: str
    lead_days_at_request: int
    reschedule_count: int
    punch_list_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyTransition(TypedDict):
    id: str
    car_id: str
    maintenance_contract_id: Optional[str]
    warranty_months: int
    warranty_start: str
    warranty_end: str
    provisional_credit_cents: Optional[int]
    final_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceContract(TypedDict):
    id: str
    project_id: str
    monthly_base_cents: int
    coverage_start: str
    monthly_total_cents: int
    cars_covered: int
    total_final_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
