"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    LEASE_ADMIN = "LeaseAdmin"
    FLEET_PLANNER = "FleetPlanner"
    MAINTENANCE_CONTROLLER = "MaintenanceController"
    BILLING_ANALYST = "BillingAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LESSEE_REP = "LesseeRep"


class CreditTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class CarType(str, Enum):
    BOX = "BOX"
    COVERED_HOPPER = "COVERED_HOPPER"
    GONDOLA = "GONDOLA"
    FLAT = "FLAT"
    TANK_GENERAL = "TANK_GENERAL"
    TANK_PRESSURE = "TANK_PRESSURE"


class Commodity(str, Enum):
    NONE = "NONE"
    GRAIN = "GRAIN"
    COAL = "COAL"
    PLASTIC_PELLETS = "PLASTIC_PELLETS"
    CEMENT = "CEMENT"
    LUMBER = "LUMBER"
    CRUDE_OIL = "CRUDE_OIL"
    GASOLINE = "GASOLINE"
    ETHANOL = "ETHANOL"
    CORN_SYRUP = "CORN_SYRUP"
    CHEMICAL_SOLVENT = "CHEMICAL_SOLVENT"


class LesseeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RailcarStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LEASE = "ON_LEASE"
    IN_SHOP = "IN_SHOP"
    RETIREMENT_PENDING = "RETIREMENT_PENDING"
    RETIRED = "RETIRED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    RETROFIT_DUE = "RETROFIT_DUE"
    NON_COMPLIANT = "NON_COMPLIANT"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class LeaseType(str, Enum):
    FULL_SERVICE = "FULL_SERVICE"
    NET = "NET"


class RateKind(str, Enum):
    CAR_HIRE_BASE = "CAR_HIRE_BASE"
    MILEAGE_CREDIT = "MILEAGE_CREDIT"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_LEASE = "ON_LEASE"
    RETURNED = "RETURNED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    LESSEE_REQUEST = "LESSEE_REQUEST"
    DIRECTIVE_EFFECTIVE = "DIRECTIVE_EFFECTIVE"
    LEASE_TERMINATED = "LEASE_TERMINATED"


class MileageReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    DISPUTED = "DISPUTED"


class StatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    SETTLED = "SETTLED"


class TariffSource(str, Enum):
    CURRENT = "CURRENT"
    PINNED = "PINNED"


class DefectCause(str, Enum):
    WEAR_AND_TEAR = "WEAR_AND_TEAR"
    LESSEE_DAMAGE = "LESSEE_DAMAGE"
    PRE_EXISTING = "PRE_EXISTING"


class RepairStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class CleaningGrade(str, Enum):
    WASH = "WASH"
    STEAM_CLEAN = "STEAM_CLEAN"


class CleaningStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class BillTo(str, Enum):
    LESSEE = "LESSEE"
    LESSOR = "LESSOR"


class Severity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class DirectiveStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    EFFECTIVE = "EFFECTIVE"


class RetrofitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEFERRED = "DEFERRED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CERTIFIED = "CERTIFIED"
    CANCELLED = "CANCELLED"


class RetirementReason(str, Enum):
    AGE_LIMIT = "AGE_LIMIT"
    DAMAGE_BEYOND_REPAIR = "DAMAGE_BEYOND_REPAIR"
    OBSOLESCENCE = "OBSOLESCENCE"
    DIRECTIVE_ECONOMIC = "DIRECTIVE_ECONOMIC"


class RetirementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPRAISED = "APPRAISED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class CommitmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# All fifteen resources carry the standard system-managed properties of PRD
# §2.4 (id, created_at, updated_at, version) plus their domain fields.

class Lessee(TypedDict, total=False):
    id: str
    company_name: str
    credit_tier: str
    credit_limit_cents: int
    security_deposit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Railcar(TypedDict, total=False):
    id: str
    car_mark: str
    car_type: str
    built_year: int
    car_age_years: int
    cumulative_miles: int
    last_commodity: str
    compliance_posture: str
    status: str
    status_before_shop: Optional[str]
    open_shop_repair_count: int
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeaseAgreement(TypedDict, total=False):
    id: str
    lessee_id: str
    lease_type: str
    base_daily_rate_cents: int
    car_hire_lessor_share_pct: int
    authorized_repair_cap_cents: int
    start_date: str
    end_date: str
    submitted_by_user_id: Optional[str]
    early_termination_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TariffRate(TypedDict, total=False):
    id: str
    car_type: str
    rate_kind: str
    effective_from: str
    effective_to: str
    unit_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class LeaseAssignment(TypedDict, total=False):
    id: str
    lease_id: str
    railcar_id: str
    planned_commodity: str
    scheduled_start: str
    scheduled_end: str
    actual_on_lease_date: Optional[str]
    actual_off_lease_date: Optional[str]
    pinned_car_hire_daily_cents: int
    pinned_mileage_credit_cents: int
    billable_days: Optional[int]
    final_rent_cents: Optional[int]
    termination_fee_cents: Optional[int]
    cancellation_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MileageReport(TypedDict, total=False):
    id: str
    railcar_id: str
    lease_assignment_id: str
    report_month: str
    loaded_miles: int
    empty_miles: int
    validated_loaded_miles: Optional[int]
    validated_empty_miles: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarHireStatement(TypedDict, total=False):
    id: str
    lease_assignment_id: str
    railcar_id: str
    lessee_id: str
    statement_month: str
    days_on_lease: int
    gross_car_hire_cents: int
    loaded_miles_used: int
    tier_excess_miles: int
    mileage_credit_cents: int
    provisional_net_cents: int
    final_net_cents: Optional[int]
    tariff_source: str
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairAuthorization(TypedDict, total=False):
    id: str
    railcar_id: str
    lease_assignment_id: Optional[str]
    defect_description: str
    defect_cause: str
    estimate_cents: int
    requires_shop: bool
    approved_amount_cents: Optional[int]
    final_cost_cents: Optional[int]
    lessee_share_cents: int
    lessor_share_cents: int
    lessee_preauth_required: bool
    lessee_preauthorized: bool
    revision_count: int
    shop_entry_date: Optional[str]
    completion_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CleaningRecord(TypedDict, total=False):
    id: str
    railcar_id: str
    prior_commodity: str
    next_commodity: str
    cleaning_grade_required: str
    cleaning_grade_performed: Optional[str]
    planned_date: str
    cost_cents: Optional[int]
    attributable_to_lessee: bool
    bill_to: str
    certificate_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageLineItem(TypedDict):
    component: str
    severity: str
    cause: str
    parts_cents: int
    labor_hours: float
    replaced: bool


class DamageAssessment(TypedDict, total=False):
    id: str
    lease_assignment_id: str
    railcar_id: str
    line_items: List[DamageLineItem]
    total_assessed_cents: Optional[int]
    lessee_liable_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceDirective(TypedDict, total=False):
    id: str
    directive_code: str
    description: str
    applies_to_car_types: List[str]
    retrofit_deadline: str
    grace_days: int
    daily_penalty_cents: int
    penalty_cap_cents: int
    effective_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RetrofitOrder(TypedDict, total=False):
    id: str
    railcar_id: str
    directive_id: str
    scheduled_date: str
    completed_date: Optional[str]
    certification_ref: Optional[str]
    deferral_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetirementCase(TypedDict, total=False):
    id: str
    railcar_id: str
    reason: str
    proposer_user_id: str
    salvage_value_cents: Optional[int]
    book_value_cents: Optional[int]
    impairment_loss_cents: Optional[int]
    reinvestment_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalPool(TypedDict, total=False):
    id: str
    fiscal_year: int
    opening_balance_cents: int
    replenishment_cents: int
    committed_cents: int
    delivered_spend_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class PurchaseCommitment(TypedDict, total=False):
    id: str
    pool_id: str
    car_type: str
    unit_cost_cents: int
    delivered_car_mark: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
