"""Entity shapes and enumerated value sets declared by PRD.md.

The TypedDicts name every field the PRD declares on an entity, so that a test
asserting on a response can be checked against the contract's own vocabulary.
Two entities are immutable evidence rows carrying only ``id`` and ``created_at``
and therefore have neither ``updated_at`` nor ``version``.
"""

from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class Role:
    DISPATCH_COORDINATOR = "DispatchCoordinator"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    VENUE_MANAGER = "VenueManager"
    QUALITY_AUDITOR = "QualityAuditor"
    BREWER_REP = "BrewerRep"


ALL_ROLES: List[str] = [
    Role.DISPATCH_COORDINATOR,
    Role.SERVICE_TECHNICIAN,
    Role.VENUE_MANAGER,
    Role.QUALITY_AUDITOR,
    Role.BREWER_REP,
]


# ---------------------------------------------------------------------------
# Enumerated value sets
# ---------------------------------------------------------------------------
class AccountStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BillingMode:
    DIRECT_BILL = "DIRECT_BILL"
    PROGRAM_BILL = "PROGRAM_BILL"


class SuspendedReason:
    NONE = "NONE"
    MANUAL = "MANUAL"
    LINE_COMPLIANCE_THRESHOLD = "LINE_COMPLIANCE_THRESHOLD"


class ContractStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class FundingStatus:
    NONE = "NONE"
    BREWER_FUNDED = "BREWER_FUNDED"
    SELF_FUNDED = "SELF_FUNDED"


class LineStatus:
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ComplianceFlag:
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class BeerStyleGroup:
    ALE = "ALE"
    LAGER = "LAGER"
    CIDER = "CIDER"
    NITRO = "NITRO"


class CertificationLevel:
    APPRENTICE = "APPRENTICE"
    CERTIFIED = "CERTIFIED"
    MASTER = "MASTER"


class TechnicianStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ChemicalType:
    CAUSTIC = "CAUSTIC"
    ACID = "ACID"
    NONE = "NONE"


class LotStatus:
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class ComponentType:
    FAUCET = "FAUCET"
    COUPLER = "COUPLER"
    FOB = "FOB"


class ConditionGrade:
    GOOD = "GOOD"
    WORN = "WORN"
    FAILED = "FAILED"


class ActionTaken:
    NONE = "NONE"
    CLEANED = "CLEANED"
    REPLACED = "REPLACED"


class FundedScope:
    CLEANING_ONLY = "CLEANING_ONLY"
    CLEANING_AND_PARTS = "CLEANING_AND_PARTS"
    FULL = "FULL"


class ProgramStatus:
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    ENDED = "ENDED"


class VisitKind:
    ROUTINE_CLEANING = "ROUTINE_CLEANING"
    EMERGENCY_TROUBLESHOOT = "EMERGENCY_TROUBLESHOOT"
    GLYCOL_MAINTENANCE = "GLYCOL_MAINTENANCE"


class WorkStatus:
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    WORK_COMPLETE = "WORK_COMPLETE"
    ABANDONED = "ABANDONED"


class VerificationStatus:
    UNVERIFIED = "UNVERIFIED"
    SIGNED = "SIGNED"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"


class SettlementState:
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class AbandonReason:
    NONE = "NONE"
    RESCHEDULED = "RESCHEDULED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"


class ComplianceResult:
    PASS = "PASS"
    FAIL_TEMPERATURE = "FAIL_TEMPERATURE"
    FAIL_CONCENTRATION = "FAIL_CONCENTRATION"
    FAIL_CONTACT_TIME = "FAIL_CONTACT_TIME"


class RecordStatus:
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class BalanceState:
    BALANCED = "BALANCED"
    RESTRICTION_HIGH = "RESTRICTION_HIGH"
    PRESSURE_HIGH = "PRESSURE_HIGH"


class BalanceRecordStatus:
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class BalanceDecision:
    APPLY = "APPLY"
    REJECT = "REJECT"


class Symptom:
    FOAMY_POUR = "FOAMY_POUR"
    FLAT_POUR = "FLAT_POUR"
    OFF_FLAVOR = "OFF_FLAVOR"
    SLOW_POUR = "SLOW_POUR"
    CLOUDY = "CLOUDY"


class ComplaintStatus:
    OPEN = "OPEN"
    DIAGNOSING = "DIAGNOSING"
    AWAITING_PARTS = "AWAITING_PARTS"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class DiagnosticOutcome:
    ROOT_CAUSE_FOUND = "ROOT_CAUSE_FOUND"
    PARTS_REQUIRED = "PARTS_REQUIRED"


class FindingCode:
    NONE = "NONE"
    LINE_SOIL = "LINE_SOIL"
    GAS_IMBALANCE = "GAS_IMBALANCE"
    TEMP_EXCURSION = "TEMP_EXCURSION"
    FAUCET_WEAR = "FAUCET_WEAR"
    KEG_DEFECT = "KEG_DEFECT"


class Disposition:
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class VerificationDecision:
    SIGN = "SIGN"
    DISPUTE = "DISPUTE"


class GlycolStatus:
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    ALARM = "ALARM"


class ReadingSource:
    TECH_MANUAL = "TECH_MANUAL"
    VENUE_MANUAL = "VENUE_MANUAL"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
class MutableCommonFields(TypedDict):
    """Fields every mutable row carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableCommonFields(TypedDict):
    """Fields an immutable evidence row carries — no updated_at, no version."""

    id: str
    created_at: str


class ServiceAccount(MutableCommonFields):
    venue_name: str
    status: str
    access_window_start_minute: int
    access_window_end_minute: int
    glycol_system_present: bool
    billing_mode: str
    lines_out_of_service_count: int
    open_complaint_count: int
    suspended_reason: str


class ServiceContract(MutableCommonFields):
    account_id: str
    brewer_program_id: Optional[str]
    status: str
    cleaning_frequency_days: int
    contracted_line_count: int
    per_line_rate_cents: int
    visit_base_fee_cents: int
    effective_from: str
    funding_status: str
    frequency_multiplier: float


class BeerLine(MutableCommonFields):
    account_id: str
    line_number: int
    run_length_feet: float
    vertical_rise_feet: float
    inner_diameter_inches: float
    beer_style_group: str
    average_daily_throughput_liters: float
    status: str
    compliance_flag: str
    last_chemical_type: str
    last_cleaned_at: Optional[str]
    next_due_at: Optional[str]
    days_overdue: int
    applied_psi: Optional[float]
    applied_co2_pct: Optional[float]


class Technician(MutableCommonFields):
    full_name: str
    certification_level: str
    caustic_certified: bool
    status: str


class ChemicalLot(MutableCommonFields):
    chemical_type: str
    lot_code: str
    concentration_pct_stock: float
    liters_initial: float
    liters_remaining: float
    expires_on: str
    status: str


class PartCatalogItem(MutableCommonFields):
    sku: str
    component_type: str
    unit_price_cents: int
    stock_on_hand: int
    brewer_funded_eligible: bool


class BrewerProgram(MutableCommonFields):
    brewer_name: str
    funded_scope: str
    co_pay_bps: int
    funding_cap_cents: int
    consumed_cents: int
    remaining_cents: int
    status: str


class ServiceVisit(MutableCommonFields):
    account_id: str
    technician_id: str
    rescheduled_from_visit_id: Optional[str]
    visit_kind: str
    scheduled_date: str
    scheduled_start_minute: int
    scheduled_end_minute: int
    work_status: str
    verification_status: str
    settlement_state: str
    abandon_reason: str
    signer_name: Optional[str]
    signed_at: Optional[str]
    work_completed_at: Optional[str]
    serviced_line_count: int
    billable_line_count: int
    cleaning_subtotal_cents: int
    parts_charge_cents: int
    provisional_charge_cents: int
    settled_charge_cents: int
    brewer_funded_cents: int
    account_due_cents: int


class CleaningCycle(MutableCommonFields):
    visit_id: str
    line_id: str
    chemical_lot_id: str
    chemical_type: str
    logged_at: str
    logged_by_technician_id: str
    contact_minutes: int
    recirculation_temp_f: float
    concentrate_liters_used: float
    line_volume_liters: float
    total_solution_liters: int
    prescribed_concentrate_liters: float
    effective_active_pct: float
    required_contact_minutes: int
    compliance_result: str
    record_status: str
    void_reason: Optional[str]


class BalanceRecord(MutableCommonFields):
    line_id: str
    visit_id: str
    measured_temp_f: float
    proposed_applied_psi: float
    proposed_co2_pct: float
    proposed_by_technician_id: str
    target_co2_volumes: float
    equilibrium_psi: float
    total_restriction_psi: float
    required_applied_psi: float
    required_co2_pct: float
    balance_state: str
    status: str
    decision_note: Optional[str]


class ComponentInspection(ImmutableCommonFields):
    visit_id: str
    line_id: str
    part_sku_id: Optional[str]
    component_type: str
    condition_grade: str
    action_taken: str
    part_charge_cents: int
    inspected_by_technician_id: str


class QualityComplaint(MutableCommonFields):
    account_id: str
    line_id: str
    symptom: str
    reported_at: str
    status: str
    diagnostic_round: int
    reopen_count: int
    days_at_risk: int
    provisional_yield_loss_liters: float
    provisional_yield_loss_cents: int
    settled_yield_loss_liters: Optional[float]
    settled_yield_loss_cents: Optional[int]
    measured_waste_liters: Optional[float]
    escalated_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    resolved_at: Optional[str]
    last_finding_code: str


class GlycolLoop(MutableCommonFields):
    account_id: str
    glycol_pct: float
    pump_psi: float
    bath_temp_f: float
    last_serviced_at: str
    health_score: float
    status: str
    window_avg_cooler_temp_f: Optional[float]


class CoolerReading(ImmutableCommonFields):
    glycol_loop_id: str
    reading_at: str
    cooler_temp_f: float
    glycol_supply_temp_f: float
    source: str
    recorded_by_user_id: str
