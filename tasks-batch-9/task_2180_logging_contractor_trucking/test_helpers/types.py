"""Domain types for the logging contractor trucking API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Role ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OPERATIONS_MANAGER = "OperationsManager"
    HAUL_CONTRACTOR = "HaulContractor"
    MILL_SCALER = "MillScaler"
    SAFETY_OFFICER = "SafetyOfficer"
    SETTLEMENT_ACCOUNTANT = "SettlementAccountant"


# ─── Woods and yard enumerations ─────────────────────────────────────────────

class Species(str, Enum):
    DOUGLAS_FIR = "DOUGLAS_FIR"
    WESTERN_HEMLOCK = "WESTERN_HEMLOCK"
    RED_ALDER = "RED_ALDER"
    PONDEROSA_PINE = "PONDEROSA_PINE"


class Grade(str, Enum):
    PEELER = "PEELER"
    SAWLOG_1 = "SAWLOG_1"
    SAWLOG_2 = "SAWLOG_2"
    PULP = "PULP"


class PermitClass(str, Enum):
    STANDARD = "STANDARD"
    DIVISIBLE_LOAD_PERMIT = "DIVISIBLE_LOAD_PERMIT"
    LONGER_COMBINATION = "LONGER_COMBINATION"


class AccessClass(str, Enum):
    ALL_SEASON = "ALL_SEASON"
    SUMMER_ONLY = "SUMMER_ONLY"
    FROZEN_ONLY = "FROZEN_ONLY"


class AxleConfig(str, Enum):
    FIVE_AXLE = "FIVE_AXLE"
    SIX_AXLE = "SIX_AXLE"
    SEVEN_AXLE = "SEVEN_AXLE"


class CoverageType(str, Enum):
    GENERAL_LIABILITY = "GENERAL_LIABILITY"
    AUTO_LIABILITY = "AUTO_LIABILITY"
    WORKERS_COMP = "WORKERS_COMP"


class CrewType(str, Enum):
    HAND_FALLING = "HAND_FALLING"
    MECHANIZED_GROUND = "MECHANIZED_GROUND"
    CABLE_YARDING = "CABLE_YARDING"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ShutdownReason(str, Enum):
    WET_WEATHER = "WET_WEATHER"
    FROST_LAW = "FROST_LAW"
    FIRE_DANGER = "FIRE_DANGER"
    SAFETY_STAND_DOWN = "SAFETY_STAND_DOWN"


class RejectReason(str, Enum):
    SPECIES_MISMATCH = "SPECIES_MISMATCH"
    EXCESS_DEFECT = "EXCESS_DEFECT"
    CONTAMINATION = "CONTAMINATION"
    OVERWEIGHT = "OVERWEIGHT"


class SettlementLineType(str, Enum):
    HAUL = "HAUL"
    FUEL_SURCHARGE = "FUEL_SURCHARGE"
    DEMURRAGE = "DEMURRAGE"
    REJECT_DEDUCTION = "REJECT_DEDUCTION"
    INSURANCE_HOLDBACK = "INSURANCE_HOLDBACK"


# ─── Status enums ────────────────────────────────────────────────────────────

class MillReceivingStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MillContractStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WARNED = "WARNED"
    SUSPENDED = "SUSPENDED"


class InsuranceCertificateStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class TruckStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISPATCHED = "DISPATCHED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class TractStatus(str, Enum):
    PLANNED = "PLANNED"
    MOBILIZING = "MOBILIZING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class ProductionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class CrewStatus(str, Enum):
    IDLE = "IDLE"
    MOBILIZING = "MOBILIZING"
    ON_TRACT = "ON_TRACT"
    STOOD_DOWN = "STOOD_DOWN"


class CrewAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MOVED_IN = "MOVED_IN"
    WORKING = "WORKING"
    STOOD_DOWN = "STOOD_DOWN"
    RELEASED = "RELEASED"


class HaulRouteStatus(str, Enum):
    OPEN = "OPEN"
    POSTED_RESTRICTED = "POSTED_RESTRICTED"
    CLOSED = "CLOSED"


class ShutdownOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class LoadDispatchStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_MILL = "AT_MILL"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class LoadSettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    ACCRUED = "ACCRUED"
    STATEMENTED = "STATEMENTED"
    PAID = "PAID"


class RehaulStatus(str, Enum):
    NONE = "NONE"
    REHAULED = "REHAULED"
    NO_ALTERNATE = "NO_ALTERNATE"


class DeliveryTicketStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class SettlementStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    REVISED = "REVISED"
    PAID = "PAID"
    VOID = "VOID"


# ─── Entity shapes ───────────────────────────────────────────────────────────
# Entities carrying the full common property set: id, created_at, updated_at,
# version.  SafetyFinding is the sole exception and carries only id and
# created_at.

class Mill(TypedDict):
    id: str
    name: str
    state_code: str
    receiving_status: str
    created_at: str
    updated_at: str
    version: int


class MillContract(TypedDict):
    id: str
    mill_id: str
    species: str
    grade: str
    quota_tons: float
    overrun_tolerance_pct: float
    base_rate_cents_per_ton: int
    period_start: str
    period_end: str
    reserved_tons: float
    delivered_tons: float
    available_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class HaulContractor(TypedDict):
    id: str
    name: str
    dot_number: str
    base_state_code: str
    compliance_status: str
    compliance_score: float
    lifetime_settled_cents: int
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    haul_contractor_id: str
    coverage_type: str
    effective_on: str
    expires_on: str
    limit_cents: int
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    haul_contractor_id: str
    unit_number: str
    axle_config: str
    tare_weight_lbs: int
    permit_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyFinding(TypedDict):
    """Immutable audit record: only id and created_at, no updated_at, no version."""
    id: str
    haul_contractor_id: str
    severity: str
    points: int
    occurred_on: str
    note: Optional[str]
    created_at: str


class Tract(TypedDict):
    id: str
    name: str
    legal_description: str
    gross_acres: float
    planned_volume_tons: float
    access_class: str
    status: str
    suspension_count: int
    move_in_cost_cents: int
    produced_tons: float
    created_at: str
    updated_at: str
    version: int


class ProductionPlan(TypedDict):
    id: str
    tract_id: str
    target_tons_per_week: float
    plan_horizon_weeks: int
    planned_volume_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    crew_type: str
    equipment_pieces: int
    daily_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    tract_id: str
    crew_id: str
    move_in_miles: int
    window_start: str
    window_end: str
    lowboy_trips: int
    move_in_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HaulRoute(TypedDict):
    id: str
    tract_id: str
    mill_id: str
    distance_miles: int
    legal_gross_weight_lbs: int
    permit_class_required: str
    frost_law_start_on: Optional[str]
    frost_law_end_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShutdownOrder(TypedDict):
    id: str
    tract_id: str
    reason: str
    soil_moisture_index: int
    lift_soil_moisture_index: Optional[int]
    declared_at: str
    lifted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict):
    id: str
    tract_id: str
    mill_contract_id: str
    haul_route_id: str
    truck_id: str
    haul_contractor_id: str
    rehaul_of_load_id: Optional[str]
    declared_species: str
    declared_grade: str
    estimated_net_tons: float
    scheduled_depart_at: str
    scheduled_arrive_at: str
    dispatch_status: str
    settlement_status: str
    rehaul_status: str
    departed_at: Optional[str]
    arrived_at: Optional[str]
    rejected_on: Optional[str]
    settlement_event_on: Optional[str]
    wait_minutes: Optional[int]
    rate_cents_per_ton_mile: Optional[int]
    provisional_haul_pay_cents: int
    line_haul_cents: Optional[int]
    fuel_surcharge_cents: Optional[int]
    demurrage_cents: Optional[int]
    incentive_cents: Optional[int]
    regrade_adjustment_cents: Optional[int]
    final_haul_pay_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DeliveryTicket(TypedDict):
    id: str
    load_id: str
    mill_id: str
    gross_weight_lbs: int
    tare_weight_lbs: int
    net_weight_lbs: int
    defect_deduction_pct: float
    defect_deducted_lbs: int
    payable_lbs: int
    net_tons: float
    max_allowed_gross_lbs: int
    scaled_species: str
    scaled_grade: str
    ticket_status: str
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict):
    line_type: str
    load_id: Optional[str]
    tons: Optional[float]
    distance_miles: Optional[int]
    amount_cents: int


class SettlementStatement(TypedDict):
    id: str
    haul_contractor_id: str
    period_start: str
    period_end: str
    status: str
    compiled_by_user_id: str
    approved_by_user_id: Optional[str]
    compliance_score_at_compile: float
    holdback_pct: float
    lines: List[SettlementLine]
    gross_pay_cents: int
    reject_deduction_cents: int
    holdback_cents: int
    deduction_cents: int
    net_pay_cents: int
    dispute_reason: Optional[str]
    payment_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int
