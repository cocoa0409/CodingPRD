"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    GROWER = "Grower"
    INTAKE_TECHNICIAN = "IntakeTechnician"
    DRYER_OPERATOR = "DryerOperator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    ELEVATOR_MANAGER = "ElevatorManager"


class Commodity(str, Enum):
    CORN = "CORN"
    SOYBEAN = "SOYBEAN"
    WHEAT = "WHEAT"


class PriorityClass(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY_CONTRACT = "PRIORITY_CONTRACT"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class GrainLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TESTED = "TESTED"
    QUEUED = "QUEUED"
    DRYING = "DRYING"
    DRIED = "DRIED"
    DAMAGE_HOLD = "DAMAGE_HOLD"
    STORED = "STORED"
    LOADED_OUT = "LOADED_OUT"
    BLENDED_OUT = "BLENDED_OUT"


class Ownership(str, Enum):
    GROWER_HELD = "GROWER_HELD"
    ELEVATOR_HELD = "ELEVATOR_HELD"


class MoistureTestStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    CERTIFIED = "CERTIFIED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class TestMethod(str, Enum):
    PROBE = "PROBE"
    OVEN_REFERENCE = "OVEN_REFERENCE"


class QueueTicketStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PREEMPTED = "PREEMPTED"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DryerRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


class BlendOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ASSESSED = "ASSESSED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    PAID = "PAID"
    WITHDRAWN = "WITHDRAWN"


class DamageType(str, Enum):
    HEAT_DAMAGE = "HEAT_DAMAGE"
    STRESS_CRACKING = "STRESS_CRACKING"
    MOLD_CONTAMINATION = "MOLD_CONTAMINATION"
    EXCESS_SHRINK = "EXCESS_SHRINK"


class StorageAgreementStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    DEFAULTED = "DEFAULTED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class PaymentDirection(str, Enum):
    APPLICATION = "APPLICATION"
    REVERSAL = "REVERSAL"


class Customer(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    prepaid_balance_cents: int
    priority_class: str
    account_status: str
    created_at: str
    updated_at: str
    version: int


class GrainLot(TypedDict, total=False):
    id: str
    customer_id: str
    commodity: str
    gross_weight_lbs: int
    tare_weight_lbs: int
    wet_net_weight_lbs: int
    foreign_material_pct: float
    target_moisture_pct: float
    intake_moisture_pct: Optional[float]
    current_moisture_pct: Optional[float]
    certified_test_id: Optional[str]
    provisional_shrink_pct: Optional[float]
    provisional_dry_weight_lbs: Optional[int]
    final_dry_weight_lbs: Optional[int]
    final_shrink_pct: Optional[float]
    shrink_variance_lbs: Optional[int]
    status: str
    ownership: str
    current_owner_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoistureTest(TypedDict, total=False):
    id: str
    lot_id: str
    sample_moisture_pct: float
    method: str
    supersedes_test_id: Optional[str]
    status: str
    tested_by_user_id: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DryingChargeSchedule(TypedDict, total=False):
    id: str
    commodity: str
    effective_from: str
    effective_to: str
    t1_max_moisture_pct: float
    t2_max_moisture_pct: float
    rate_t1_cents_per_pt_bu: int
    rate_t2_cents_per_pt_bu: int
    rate_t3_cents_per_pt_bu: int
    fm_threshold_pct: float
    fm_surcharge_pct: float
    min_charge_cents: int
    energy_t1_limit_therms: float
    energy_t1_rate_cents_per_therm: int
    energy_t2_rate_cents_per_therm: int
    est_therms_per_hour: float
    est_point_factor: float
    created_at: str
    updated_at: str
    version: int


class DryerUnit(TypedDict, total=False):
    id: str
    unit_code: str
    daily_capacity_bushels: int
    standard_class_cap_bushels: int
    throughput_bu_per_hour: int
    cooldown_minutes: int
    created_at: str
    updated_at: str
    version: int


class QueueTicket(TypedDict, total=False):
    id: str
    lot_id: str
    unit_id: str
    window_date: str
    requested_bushels: int
    priority_class: str
    status: str
    preemption_count: int
    created_at: str
    updated_at: str
    version: int


class DryerRun(TypedDict, total=False):
    id: str
    unit_id: str
    lot_id: str
    queue_ticket_id: str
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    operator_user_id: Optional[str]
    meter_start_therms: Optional[float]
    meter_end_therms: Optional[float]
    energy_estimated: bool
    scale_out_weight_lbs: Optional[int]
    discharge_moisture_pct: Optional[float]
    fuel_therms: Optional[float]
    energy_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendOrder(TypedDict, total=False):
    id: str
    high_moisture_lot_id: str
    low_moisture_lot_id: str
    target_moisture_pct: float
    required_low_lot_lbs: int
    result_lot_id: Optional[str]
    result_weight_lbs: Optional[int]
    result_moisture_pct: Optional[float]
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    lot_id: str
    dryer_run_id: str
    damage_type: str
    claimed_amount_cents: int
    status: str
    filed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    assessed_by_user_id: Optional[str]
    lot_value_cents: Optional[int]
    fault_multiplier: Optional[float]
    assessed_liability_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StorageAgreement(TypedDict, total=False):
    id: str
    lot_id: str
    owner_id: Optional[str]
    daily_rate_cents_per_bu: float
    min_days: int
    baseline_bushels: Optional[float]
    start_date: Optional[str]
    closed_date: Optional[str]
    accrued_days: Optional[int]
    accrued_storage_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    line_type: str
    ref_id: str
    description: str
    amount_cents: int


class Invoice(TypedDict, total=False):
    id: str
    customer_id: str
    period_start: str
    period_end: str
    lines: List[Dict[str, Any]]
    total_cents: int
    amount_due_cents: int
    schedule_id: Optional[str]
    pinned_schedule_version: Optional[int]
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry (PRD §2.5): carries ONLY id + created_at from the
# common set — no updated_at, no version.
class Payment(TypedDict, total=False):
    id: str
    invoice_id: str
    amount_cents: int
    applied_from_prepaid_cents: int
    applied_from_cash_cents: int
    direction: str
    reversal_of_payment_id: Optional[str]
    created_at: str
