"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class VoltageClass(str, Enum):
    DISTRIBUTION_4KV = "DISTRIBUTION_4KV"
    DISTRIBUTION_12KV = "DISTRIBUTION_12KV"
    DISTRIBUTION_35KV = "DISTRIBUTION_35KV"
    SUBTRANSMISSION_69KV = "SUBTRANSMISSION_69KV"
    TRANSMISSION_115KV = "TRANSMISSION_115KV"


class GrowthZone(str, Enum):
    SLOW = "SLOW"
    MODERATE = "MODERATE"
    RAPID = "RAPID"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ReliabilityTier(str, Enum):
    TIER_NORMAL = "TIER_NORMAL"
    TIER_ELEVATED = "TIER_ELEVATED"
    TIER_CRITICAL = "TIER_CRITICAL"


class TrimStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    ACTIVE_CYCLE = "ACTIVE_CYCLE"
    CYCLE_AT_RISK = "CYCLE_AT_RISK"
    CYCLE_COMPLETE = "CYCLE_COMPLETE"


class WorkPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ExecutionStatus(str, Enum):
    PLANNED = "PLANNED"
    MAPPED = "MAPPED"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    STORM_PREEMPTED = "STORM_PREEMPTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    NOT_BILLABLE = "NOT_BILLABLE"
    BILLABLE = "BILLABLE"
    LINE_DRAFTED = "LINE_DRAFTED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class BillingMethod(str, Enum):
    UNIT_PRICE = "UNIT_PRICE"
    TIME_AND_MATERIALS = "TIME_AND_MATERIALS"


class CrewType(str, Enum):
    BUCKET = "BUCKET"
    CLIMBING = "CLIMBING"
    MANUAL = "MANUAL"
    HERBICIDE = "HERBICIDE"
    STORM = "STORM"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    STORM_DEPLOYED = "STORM_DEPLOYED"


class CrewAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    PREEMPTED = "PREEMPTED"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REFUSED = "REFUSED"
    ESCALATED = "ESCALATED"
    FINAL_REFUSAL = "FINAL_REFUSAL"


class ContactMethod(str, Enum):
    DOOR_HANGER = "DOOR_HANGER"
    PHONE = "PHONE"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"


class HazardTreeStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    ASSESSED = "ASSESSED"
    APPROVED_REMOVAL = "APPROVED_REMOVAL"
    DECLINED = "DECLINED"
    DEFERRED = "DEFERRED"
    REMOVED = "REMOVED"


class Species(str, Enum):
    SILVER_MAPLE = "SILVER_MAPLE"
    COTTONWOOD = "COTTONWOOD"
    ASH = "ASH"
    OAK = "OAK"
    CONIFER = "CONIFER"


class DefectClass(str, Enum):
    DEAD = "DEAD"
    CAVITY = "CAVITY"
    LEAN = "LEAN"
    CODOMINANT = "CODOMINANT"
    HEALTHY = "HEALTHY"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ChemicalCode(str, Enum):
    GLYPHOSATE = "GLYPHOSATE"
    TRICLOPYR = "TRICLOPYR"
    IMAZAPYR = "IMAZAPYR"
    AMINOPYRALID = "AMINOPYRALID"


class StormStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    DEMOBILIZING = "DEMOBILIZING"
    CLOSED = "CLOSED"


class BillingLineStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOID = "VOID"


class CauseCode(str, Enum):
    TREE_GROWN_IN = "TREE_GROWN_IN"
    TREE_FELL_ON = "TREE_FELL_ON"
    NON_TREE = "NON_TREE"


class UserRole(str, Enum):
    UTILITY_FORESTER = "UtilityForester"
    CONTRACTOR_PLANNER = "ContractorPlanner"
    CREW_FOREMAN = "CrewForeman"
    CERTIFIED_ARBORIST = "CertifiedArborist"
    CUSTOMER_ADVOCATE = "CustomerAdvocate"
    BILLING_ANALYST = "BillingAnalyst"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity shapes -------------------------------------------------------
# Records that carry id + created_at + updated_at + version.

class Prescription(TypedDict):
    id: str
    voltage_class: str
    growth_zone: str
    base_cycle_years: float
    clearance_radius_ft: float
    ground_to_sky: bool
    herbicide_allowed: bool
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Circuit(TypedDict):
    id: str
    circuit_code: str
    voltage_class: str
    growth_zone: str
    customer_count: int
    last_trim_completed_on: str
    prescription_id: Optional[str]
    cycle_months: int
    next_trim_due_on: str
    tree_caused_outage_count_36mo: int
    reliability_index_36mo: float
    reliability_index_ytd: float
    reliability_tier: str
    trim_status: str
    created_at: str
    updated_at: str
    version: int


class WorkPlan(TypedDict):
    id: str
    circuit_id: str
    program_year: int
    planned_span_miles: float
    budget_cents: int
    planned_unit_count: int
    completed_unit_count: int
    production_pct: float
    committed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    work_plan_id: str
    parent_work_order_id: Optional[str]
    storm_event_id: Optional[str]
    span_miles: float
    billing_method: str
    planned_unit_count: int
    clearance_radius_ft: Optional[float]
    actual_units_completed: int
    refusal_blocked_unit_count: int
    execution_status: str
    billing_status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    crew_code: str
    crew_type: str
    headcount: int
    hourly_rate_cents: int
    home_district: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    work_order_id: str
    crew_id: str
    preempted_by_storm_event_id: Optional[str]
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerNotification(TypedDict):
    id: str
    work_order_id: str
    premise_code: str
    contact_method: str
    unit_count_at_premise: int
    refusal_round: int
    notified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HazardTree(TypedDict):
    id: str
    circuit_id: str
    work_order_id: Optional[str]
    customer_notification_id: Optional[str]
    species: str
    defect_class: str
    height_ft: float
    offset_ft: float
    strike_potential: bool
    risk_score: float
    removal_required: bool
    identified_by_user_id: str
    assessed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HerbicidePermit(TypedDict):
    id: str
    circuit_id: str
    chemical_code: str
    applicator_license_no: str
    buffer_ft: float
    window_start: str
    window_end: str
    status: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StormEvent(TypedDict):
    id: str
    event_code: str
    severity_level: int
    affected_district: str
    reassigned_crew_count: int
    preempted_assignment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingLine(TypedDict):
    id: str
    work_order_id: str
    billing_method: str
    billable_units: int
    density_multiplier: float
    gross_cents: int
    retainage_cents: int
    storm_premium_cents: int
    net_payable_cents: int
    mobilization_credit_cents: int
    final_payable_cents: int
    submitted_at: Optional[str]
    superseded_by_billing_line_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only records: id + created_at only, no updated_at, no version ---

class ProductionEntry(TypedDict):
    id: str
    crew_assignment_id: str
    herbicide_permit_id: Optional[str]
    work_date: str
    units_trimmed: int
    labor_hours: float
    equipment_hours: float
    disposal_tons: float
    gallons_applied: float
    entry_cents: int
    created_at: str


class OutageRecord(TypedDict):
    id: str
    circuit_id: str
    work_order_id: Optional[str]
    outage_at: str
    cause_code: str
    customers_affected: int
    customer_minutes: float
    created_at: str
