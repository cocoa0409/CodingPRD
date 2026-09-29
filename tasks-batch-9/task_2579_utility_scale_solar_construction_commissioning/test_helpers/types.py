"""Domain types for the Utility-Scale Solar EPC API.

Status enums mirror the closed sets the PRD declares for each entity, and the
TypedDicts mirror the field sets the PRD says each resource carries.

One resource is deliberately leaner than the rest: a measurement interval of a
commissioning test carries only ``id`` and ``created_at`` (PRD 2.4), so
``TestInterval`` below omits ``updated_at`` and ``version`` entirely.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

Headers = Dict[str, str]
Json = Dict[str, Any]


class UserRole(str, Enum):
    """The eight roles of PRD 2.1, all of them opaque operator identities."""

    EPC_PROJECT_MANAGER = "EpcProjectManager"
    CIVIL_SUPERINTENDENT = "CivilSuperintendent"
    PROCUREMENT_COORDINATOR = "ProcurementCoordinator"
    INSTALLATION_FOREMAN = "InstallationForeman"
    UTILITY_COORDINATOR = "UtilityCoordinator"
    COMMISSIONING_ENGINEER = "CommissioningEngineer"
    OWNER_ENGINEER = "OwnerEngineer"
    LABOR_COMPLIANCE_OFFICER = "LaborComplianceOfficer"


class MilestoneState(str, Enum):
    PRECONSTRUCTION = "PRECONSTRUCTION"
    MC_CLAIMED = "MC_CLAIMED"
    MC_CERTIFIED = "MC_CERTIFIED"
    SC_CLAIMED = "SC_CLAIMED"
    SC_CERTIFIED = "SC_CERTIFIED"
    FA_CLAIMED = "FA_CLAIMED"
    FINAL_ACCEPTED = "FINAL_ACCEPTED"


class McReadiness(str, Enum):
    BLOCKED = "BLOCKED"
    READY = "READY"


class TaxCreditStatus(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class PrevailingWageElection(str, Enum):
    STRICT = "STRICT"
    REMEDIABLE = "REMEDIABLE"


class ApprenticeshipBasis(str, Enum):
    PROJECT_AGGREGATE = "PROJECT_AGGREGATE"
    WEEKLY_WORST_CASE = "WEEKLY_WORST_CASE"


class GradingAreaStatus(str, Enum):
    PLANNED = "PLANNED"
    CLEARED = "CLEARED"
    GRADED = "GRADED"
    ACCEPTED = "ACCEPTED"
    HOLD = "HOLD"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EarthworkActivityType(str, Enum):
    CLEARING = "CLEARING"
    GRADING = "GRADING"
    DRAINAGE = "DRAINAGE"
    ACCESS_ROAD = "ACCESS_ROAD"


class SiteEventType(str, Enum):
    RAIN_EVENT = "RAIN_EVENT"
    BMP_INSPECTION = "BMP_INSPECTION"
    PERMIT_SUSPENSION = "PERMIT_SUSPENSION"
    PERMIT_REINSTATEMENT = "PERMIT_REINSTATEMENT"


class ComponentType(str, Enum):
    MODULE = "MODULE"
    TRACKER = "TRACKER"
    INVERTER = "INVERTER"


class DeliveryStatus(str, Enum):
    RESERVED = "RESERVED"
    ARRIVED = "ARRIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class MechanicalStatus(str, Enum):
    PLANNED = "PLANNED"
    PILES_COMPLETE = "PILES_COMPLETE"
    MECH_COMPLETE = "MECH_COMPLETE"
    HOLD = "HOLD"


class ElectricalStatus(str, Enum):
    PLANNED = "PLANNED"
    WIRED = "WIRED"
    TESTED = "TESTED"
    REWORK = "REWORK"


class PileStatus(str, Enum):
    PLANNED = "PLANNED"
    ACCEPTED = "ACCEPTED"
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"
    REFUSED = "REFUSED"


class RemediationMethod(str, Enum):
    PREDRILL = "PREDRILL"
    SPLICE = "SPLICE"
    RELOCATE = "RELOCATE"


class CircuitStatus(str, Enum):
    PLANNED = "PLANNED"
    WIRED = "WIRED"
    TESTED = "TESTED"
    FAILED = "FAILED"


class TestFailureReason(str, Enum):
    INSULATION = "INSULATION"
    VOC_DEVIATION = "VOC_DEVIATION"
    POLARITY = "POLARITY"


class SubstationStatus(str, Enum):
    SITE_CIVIL = "SITE_CIVIL"
    STEEL_ERECTED = "STEEL_ERECTED"
    EQUIPMENT_SET = "EQUIPMENT_SET"
    BACKFEED_REQUESTED = "BACKFEED_REQUESTED"
    ENERGIZED = "ENERGIZED"


class OutagePurpose(str, Enum):
    BACKFEED = "BACKFEED"
    SWITCHING = "SWITCHING"
    TIE_IN = "TIE_IN"


class OutageWindowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTED = "EXECUTED"


class TestType(str, Enum):
    CAPACITY = "CAPACITY"
    PERFORMANCE_RATIO = "PERFORMANCE_RATIO"


class CorrectionVariant(str, Enum):
    AS_MEASURED = "AS_MEASURED"
    WEATHER_CORRECTED = "WEATHER_CORRECTED"


class CommissioningTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SUSPENDED = "SUSPENDED"
    VOID = "VOID"


class PunchCategory(str, Enum):
    MECHANICAL = "MECHANICAL"
    ELECTRICAL = "ELECTRICAL"
    CIVIL = "CIVIL"
    DOCUMENTATION = "DOCUMENTATION"


class PunchSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class PunchItemStatus(str, Enum):
    OPEN = "OPEN"
    CLOSURE_SUBMITTED = "CLOSURE_SUBMITTED"
    CLOSED = "CLOSED"
    WAIVED = "WAIVED"


class PayrollWeekStatus(str, Enum):
    OPEN = "OPEN"
    CERTIFIED = "CERTIFIED"


class LaborClassification(str, Enum):
    ELECTRICIAN = "ELECTRICIAN"
    LABORER = "LABORER"
    OPERATOR = "OPERATOR"
    IRONWORKER = "IRONWORKER"


class LaborEntryStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class MilestoneKind(str, Enum):
    MECHANICAL_COMPLETION = "MECHANICAL_COMPLETION"
    SUBSTANTIAL_COMPLETION = "SUBSTANTIAL_COMPLETION"
    FINAL_ACCEPTANCE = "FINAL_ACCEPTANCE"


# ---------------------------------------------------------------------------
# Entity shapes. Every entity below carries id/created_at/updated_at/version
# except TestInterval, which PRD 2.4 declares immutable and leaner.
# ---------------------------------------------------------------------------
class Project(TypedDict):
    id: str
    name: str
    utility_name: str
    ac_capacity_kw: float
    dc_capacity_kw: float
    contract_value_cents: int
    approved_change_order_cents: int
    retainage_pct: float
    ld_per_day_cents: int
    ld_cap_pct: float
    sc_deadline_date: str
    guaranteed_capacity_kw_ac: float
    guaranteed_performance_ratio: float
    prevailing_wage_election: str
    apprenticeship_basis: str
    apprenticeship_min_pct: float
    milestone_state: str
    mc_readiness: str
    blocks_total: int
    blocks_mc_ready_count: int
    total_labor_hours: float
    apprentice_labor_hours: float
    apprentice_hours_pct: float
    apprenticeship_basis_applied: Optional[str]
    wage_restitution_owed_cents: int
    wage_liquidated_damages_cents: int
    tax_credit_status: str
    open_punch_item_count: int
    open_critical_punch_count: int
    delay_days: int
    ld_assessed_cents: int
    retainage_held_cents: int
    punchlist_holdback_cents: int
    sc_payment_due_cents: int
    final_payment_cents: int
    mc_claimed_by_user_id: Optional[str]
    last_milestone_rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GradingArea(TypedDict):
    id: str
    project_id: str
    area_code: str
    permit_number: str
    disturbed_acreage_limit: float
    disturbed_acreage_current: float
    access_road_meters: int
    bmp_inspection_interval_days: int
    bmp_last_inspected_at: Optional[str]
    bmp_deficiency_open: bool
    rain_blackout_until: Optional[str]
    permit_status: str
    status: str
    status_before_hold: Optional[str]
    compaction_test_pct: Optional[float]
    drainage_inspection_passed: Optional[bool]
    earthwork_windows: List[Json]
    created_at: str
    updated_at: str
    version: int


class YardZone(TypedDict):
    id: str
    project_id: str
    zone_code: str
    pallet_capacity: int
    reserved_pallets: int
    available_pallets: int
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    project_id: str
    yard_zone_id: str
    component_type: str
    unit_qty: int
    pallets: int
    planned_arrival_at: str
    laydown_window_start: str
    laydown_window_end: str
    status: str
    received_unit_qty: Optional[int]
    damaged_unit_qty: Optional[int]
    accepted_unit_qty: Optional[int]
    damage_ratio: Optional[float]
    inspection_note: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Block(TypedDict):
    id: str
    project_id: str
    grading_area_id: str
    block_code: str
    dc_capacity_kw: float
    planned_pile_count: int
    planned_string_count: int
    mechanical_status: str
    electrical_status: str
    piles_accepted_count: int
    piles_refused_count: int
    circuits_wired_count: int
    circuits_tested_count: int
    circuits_failed_count: int
    modules_installed_qty: Optional[int]
    max_torque_tube_deviation_mm: Optional[float]
    mc_ready: bool
    created_at: str
    updated_at: str
    version: int


class Pile(TypedDict):
    id: str
    block_id: str
    row_index: int
    position_index: int
    design_embedment_mm: int
    actual_embedment_mm: Optional[int]
    plumb_deviation_mm: Optional[float]
    blow_count: Optional[int]
    refusal_flag: bool
    status: str
    remediated: bool
    remediation_method: Optional[str]
    driven_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StringCircuit(TypedDict):
    id: str
    block_id: str
    circuit_code: str
    modules_in_series: int
    combiner_position: Optional[str]
    status: str
    insulation_resistance_mohm: Optional[float]
    measured_voc_v: Optional[float]
    expected_voc_v: Optional[float]
    polarity_ok: Optional[bool]
    test_failure_reason: Optional[str]
    tested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Substation(TypedDict):
    id: str
    project_id: str
    substation_code: str
    interconnection_voltage_kv: float
    mv_collection_km: float
    status: str
    utility_witness_ref: Optional[str]
    energized_at: Optional[str]
    energizing_outage_window_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutageWindow(TypedDict):
    id: str
    substation_id: str
    start_at: str
    end_at: str
    purpose: str
    status: str
    utility_reference: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissioningTest(TypedDict):
    id: str
    project_id: str
    test_type: str
    correction_variant: str
    scheduled_at: str
    status: str
    interval_count: int
    valid_interval_count: int
    reported_kw_ac: Optional[float]
    reported_performance_ratio: Optional[float]
    pass_threshold_kw_ac: Optional[float]
    finalized_at: Optional[str]
    suspend_reason: Optional[str]
    void_reason: Optional[str]
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class TestInterval(TypedDict):
    """PRD 2.4: an interval carries only ``id`` and ``created_at``.

    No ``updated_at`` and no ``version`` — the row is immutable once appended.
    """

    id: str
    commissioning_test_id: str
    sampled_at: str
    irradiance_w_m2: float
    measured_kw_ac: float
    ambient_c: float
    wind_m_s: float
    is_valid: bool
    corrected_kw_ac: Optional[float]
    created_at: str


class PunchListItem(TypedDict):
    id: str
    project_id: str
    block_id: Optional[str]
    title: str
    category: str
    severity: str
    estimated_cost_cents: int
    status: str
    closure_evidence_ref: Optional[str]
    rejection_count: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollWeek(TypedDict):
    id: str
    project_id: str
    week_start_date: str
    status: str
    entry_count: int
    total_hours: float
    apprentice_hours: float
    journeyworker_hours: float
    apprentice_pct: float
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaborEntry(TypedDict):
    id: str
    payroll_week_id: str
    worker_ref: str
    classification: str
    is_apprentice: bool
    hours: float
    paid_rate_cents: int
    fringe_rate_cents: int
    prevailing_rate_cents: int
    work_date: str
    status: str
    shortfall_cents_per_hour: int
    restitution_cents: int
    posted_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
