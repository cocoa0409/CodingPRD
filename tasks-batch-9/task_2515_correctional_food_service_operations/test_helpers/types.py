"""Entity shapes, status vocabularies and role names for the correctional food
service API.

Two entities are declared by the PRD to carry only `id` and `created_at`: the
population count and the temperature reading. Their TypedDicts deliberately omit
`updated_at` and `version`.
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict

# --- Roles -------------------------------------------------------------------

Role = Literal[
    "ContractAdministrator",
    "FoodServiceSupervisor",
    "RegisteredDietitian",
    "CorrectionalOfficer",
    "MedicalProvider",
    "ChaplainDesignee",
    "GrievanceCoordinator",
    "ComplianceAuditor",
]

ALL_ROLES: List[str] = [
    "ContractAdministrator",
    "FoodServiceSupervisor",
    "RegisteredDietitian",
    "CorrectionalOfficer",
    "MedicalProvider",
    "ChaplainDesignee",
    "GrievanceCoordinator",
    "ComplianceAuditor",
]

# --- Status / enum vocabularies ---------------------------------------------

ContractStatus = Literal["DRAFT", "ACTIVE", "RECONCILING", "CLOSED"]
LdVariant = Literal["INCIDENT_BASED", "POPULATION_WEIGHTED"]
KitchenPosture = Literal["OPEN", "RESTRICTED", "LOCKDOWN"]
MenuCycleStatus = Literal["DRAFT", "NUTRITION_APPROVED", "ACTIVE", "RETIRED"]
MealSlot = Literal["BREAKFAST", "LUNCH", "DINNER"]
HousingUnit = Literal["GENERAL", "SEGREGATION", "SATELLITE", "MEDICAL"]
InmateStatus = Literal["IN_CUSTODY", "RELEASED", "TRANSFERRED"]
OrderType = Literal["RELIGIOUS", "MEDICAL"]
DietCode = Literal[
    "KOSHER",
    "HALAL",
    "VEGETARIAN_RELIGIOUS",
    "RENAL",
    "DIABETIC_2000",
    "GLUTEN_FREE",
    "MECHANICAL_SOFT",
]
DietOrderStatus = Literal[
    "PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED"
]
CountSource = Literal["FORMAL_COUNT", "EMERGENCY_COUNT"]
ForecastVariant = Literal["COUNT_DRIVEN", "ROSTER_DRIVEN"]
ForecastStatus = Literal["DRAFT", "LOCKED", "SUPERSEDED"]
ServiceSite = Literal["MAIN_KITCHEN", "SATELLITE_A", "SEGREGATION_UNIT"]
ProductionStage = Literal[
    "PLANNED", "COOKED", "CHILLED", "STAGED", "SERVED", "DISCARDED"
]
QaStatus = Literal["QA_PENDING", "QA_PASSED", "QA_HELD", "QA_CONDEMNED"]
LogPoint = Literal[
    "COOK_END",
    "CHILL_INTERMEDIATE",
    "CHILL_FINAL",
    "TRANSPORT_DEPART",
    "TRANSPORT_ARRIVE",
    "REHEAT_SERVE",
]
ClearanceStatus = Literal["CLEARED", "SUSPENDED", "BARRED"]
AssignmentStatus = Literal["UNASSIGNED", "ASSIGNED"]
WorkArea = Literal["BAKERY", "COOK_CHILL", "SERVING_LINE", "SANITATION"]
ToolClass = Literal["SHARP_KNIFE", "MEAT_SAW", "SCISSORS", "NON_SHARP"]
ToolStatus = Literal["ISSUED", "UNACCOUNTED", "RETURNED"]
ItemClass = Literal["SHARP", "YEAST_ALCOHOL", "FOOD_DIVERSION", "COMMISSARY_ITEM"]
Severity = Literal["MINOR", "MAJOR", "CRITICAL"]
IncidentStatus = Literal["OPEN", "SANCTIONED", "CLEARED"]
SanctionType = Literal["WARNING", "WORK_SUSPENSION", "WORK_BAR", "REFERRAL"]
ServiceRecordStatus = Literal["OPEN", "CLOSED", "DISPUTED"]
SubstitutionReason = Literal[
    "SUPPLY_OUTAGE", "EQUIPMENT_FAILURE", "SECURITY_LOCKDOWN", "QA_CONDEMNATION"
]
ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED"]
GrievanceCategory = Literal[
    "RELIGIOUS_DIET_DENIAL",
    "DIET_NOT_HONORED",
    "PORTION_SIZE",
    "FOOD_TEMPERATURE",
    "FOREIGN_OBJECT",
]
GrievanceStatus = Literal[
    "FILED",
    "UNDER_INVESTIGATION",
    "DIET_REVIEW",
    "DUAL_TRACK",
    "READY_FOR_RESPONSE",
    "RESPONDED",
    "ESCALATED",
    "CLOSED",
]
RoutedBranch = Literal["INVESTIGATION", "DIET_REVIEW", "BOTH"]
Branch = Literal["INVESTIGATION", "DIET_REVIEW"]
Remedy = Literal["NO_ACTION", "MENU_CORRECTION", "MEAL_REFEED", "DIET_REINSTATEMENT"]
MovementType = Literal["HOUSING_CHANGE", "RELEASE", "TRANSFER"]


# --- Common envelope fields --------------------------------------------------


class VersionedEntity(TypedDict):
    """Fields every mutable entity carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


# --- Entities ----------------------------------------------------------------


class ServiceContract(VersionedEntity, total=False):
    contract_code: str
    vendor_name: str
    status: ContractStatus
    contracted_kcal_per_meal_day: int
    contracted_protein_grams_per_meal_day: float
    contracted_sodium_mg_cap_per_meal_day: int
    cost_ceiling_cents_per_meal_day: int
    ld_cents_per_missed_meal: int
    ld_monthly_cap_cents: int
    substitution_allowance_pct: float
    ld_variant: Optional[LdVariant]
    total_trays_served: int
    meal_days_served: int
    missed_meal_total: int
    substitution_total: int
    substitution_rate_pct: float
    grievance_sla_breach_count: int
    raw_liquidated_damages_cents: int
    substitution_surcharge_cents: int
    liquidated_damages_cents: int
    gross_food_cost_cents: int
    cost_cents_per_meal_day_actual: float
    cost_recovery_credit_cents: int
    net_liquidated_damages_cents: int
    performance_score: float
    reconciled_at: Optional[str]
    closed_at: Optional[str]


class Facility(VersionedEntity, total=False):
    facility_code: str
    name: str
    contract_id: str
    satellite_site_count: int
    blast_chiller_capacity: int
    sharps_authorized_count: int
    sharps_issued_count: int
    sharps_unaccounted_count: int
    sharps_audit_shortfall: int
    sharps_on_board_count: int
    open_sharps_discrepancy_count: int
    open_contraband_incident_count: int
    corrective_action_required: bool
    kitchen_posture: KitchenPosture
    active_special_diet_count: int
    last_sharps_audit_at: Optional[str]


class MenuCycle(VersionedEntity, total=False):
    facility_id: str
    cycle_code: str
    cycle_length_days: int
    status: MenuCycleStatus
    item_count: int
    approved_kcal_per_meal_day: Optional[int]
    approved_protein_grams_per_meal_day: Optional[float]
    approved_sodium_mg_per_meal_day: Optional[int]
    approved_cost_cents_per_meal_day: Optional[int]
    nutrition_signed_by_user_id: Optional[str]
    activated_by_user_id: Optional[str]
    activated_at: Optional[str]


class MenuCycleItem(VersionedEntity, total=False):
    menu_cycle_id: str
    cycle_day: int
    meal_slot: MealSlot
    component_name: str
    kcal_per_100g: float
    protein_grams_per_100g: float
    sodium_mg_per_100g: float
    portion_grams: float
    raw_cost_cents: int
    therapeutic_safe: bool
    religious_tags: List[str]


class Inmate(VersionedEntity, total=False):
    facility_id: str
    booking_number: str
    housing_unit: HousingUnit
    religious_affiliation: Optional[str]
    status: InmateStatus
    active_diet_order_count: int


class DietOrder(VersionedEntity, total=False):
    inmate_id: str
    order_type: OrderType
    diet_code: DietCode
    status: DietOrderStatus
    clinical_indication: Optional[str]
    effective_from: str
    effective_to: str
    supersedes_diet_order_id: Optional[str]
    requested_by_user_id: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    verification_expires_at: Optional[str]
    reverification_count: int
    suspension_reason: Optional[str]


class PopulationCount(TypedDict, total=False):
    """The PRD states a population count carries only `id` and `created_at`:
    it has neither `updated_at` nor `version`."""

    id: str
    created_at: str
    facility_id: str
    general_population: int
    segregation_population: int
    satellite_population: int
    medical_population: int
    source: CountSource
    total_population: int
    count_at: str
    submitted_by_user_id: str


class MealForecast(VersionedEntity, total=False):
    facility_id: str
    population_count_id: str
    service_date: str
    meal_slot: MealSlot
    forecast_variant: ForecastVariant
    status: ForecastStatus
    line_trays: int
    waste_allowance_trays: int
    total_forecast_trays: int
    forecast_special_diet_trays: int
    locked_at: Optional[str]


class ProductionBatch(VersionedEntity, total=False):
    facility_id: str
    meal_forecast_id: str
    recipe_component: str
    planned_trays: int
    produced_trays: int
    scheduled_cook_start_at: str
    chill_deadline_at: str
    buffered_release_at: str
    service_site: ServiceSite
    production_stage: ProductionStage
    qa_status: QaStatus
    cook_end_at: Optional[str]
    chill_final_at: Optional[str]
    chill_minutes: Optional[int]
    cook_chill_compliant: bool
    qa_reason: Optional[str]


class TemperatureLog(TypedDict, total=False):
    """The PRD states a temperature reading carries only `id` and `created_at`:
    it has neither `updated_at` nor `version`."""

    id: str
    created_at: str
    production_batch_id: str
    log_point: LogPoint
    temperature_f: float
    site: ServiceSite
    logged_at: str
    logged_by_user_id: str
    minutes_since_cook_end: Optional[int]
    in_range: bool


class InmateWorker(VersionedEntity, total=False):
    inmate_id: str
    facility_id: str
    clearance_status: ClearanceStatus
    assignment_status: AssignmentStatus
    work_area: Optional[WorkArea]
    medical_clearance_expires_at: str
    sharps_eligible: bool
    contraband_strike_count: int


class ToolIssuance(VersionedEntity, total=False):
    facility_id: str
    issued_to_worker_id: str
    tool_class: ToolClass
    tool_serial: str
    shadow_board_slot: int
    status: ToolStatus
    issued_by_user_id: str
    issued_at: str
    returned_at: Optional[str]
    return_certified_by_user_id: Optional[str]
    unaccounted_at: Optional[str]
    recovered: bool


class ContrabandIncident(VersionedEntity, total=False):
    facility_id: str
    inmate_worker_id: Optional[str]
    related_tool_issuance_id: Optional[str]
    item_class: ItemClass
    severity: Severity
    narrative: str
    status: IncidentStatus
    sanction_type: Optional[SanctionType]
    discovered_by_user_id: str
    discovered_at: str
    disposition_by_user_id: Optional[str]


class MealServiceRecord(VersionedEntity, total=False):
    facility_id: str
    meal_forecast_id: str
    service_date: str
    meal_slot: MealSlot
    trays_served_general: int
    trays_served_segregation: int
    trays_served_satellite: int
    special_diet_trays_served: int
    expected_service_trays: int
    total_trays_served: int
    missed_meal_count: int
    substitution_count: int
    dispute_tray_count: int
    status: ServiceRecordStatus
    closed_at: Optional[str]


class MenuSubstitution(VersionedEntity, total=False):
    menu_cycle_item_id: str
    meal_service_record_id: str
    substitute_component_name: str
    substitute_kcal_per_100g: float
    substitute_protein_grams_per_100g: float
    substitute_sodium_mg_per_100g: float
    substitute_portion_grams: float
    substitute_cost_cents: int
    reason: SubstitutionReason
    kcal_delta_pct: float
    protein_delta_pct: float
    sodium_delta_mg: float
    cost_variance_cents: int
    nutrition_equivalent: bool
    approval_status: ApprovalStatus
    documented_by_user_id: str
    decided_by_user_id: Optional[str]


class Grievance(VersionedEntity, total=False):
    inmate_id: str
    facility_id: str
    category: GrievanceCategory
    narrative: str
    diet_order_id: Optional[str]
    meal_service_record_id: Optional[str]
    refeed_tray_count: int
    responded_by_user_id: Optional[str]
    filed_at: str
    response_due_at: str
    status: GrievanceStatus
    routed_branch: Optional[RoutedBranch]
    investigation_complete: bool
    diet_review_complete: bool
    diet_remedy_required: bool
    remedy: Optional[Remedy]
    response_at: Optional[str]
    sla_breached: bool


Json = Dict[str, Any]
