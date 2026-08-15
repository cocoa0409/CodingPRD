"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    INTAKE_AGENT = "IntakeAgent"
    DEPOT_TECHNICIAN = "DepotTechnician"
    DEPOT_MANAGER = "DepotManager"
    WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
    ENGINEERING_LEAD = "EngineeringLead"


class RMAStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    DIAGNOSED = "DIAGNOSED"
    AWAITING_QUOTE_APPROVAL = "AWAITING_QUOTE_APPROVAL"
    QUOTE_DECLINED = "QUOTE_DECLINED"
    IN_REPAIR = "IN_REPAIR"
    AWAITING_PARTS = "AWAITING_PARTS"
    QA_HOLD = "QA_HOLD"
    READY_TO_SHIP = "READY_TO_SHIP"
    REPLACEMENT_PENDING = "REPLACEMENT_PENDING"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"
    SCRAPPED = "SCRAPPED"
    CANCELLED = "CANCELLED"


class CoveragePath(str, Enum):
    IN_WARRANTY = "IN_WARRANTY"
    OUT_OF_WARRANTY = "OUT_OF_WARRANTY"
    GOODWILL_FULL = "GOODWILL_FULL"
    GOODWILL_PARTIAL = "GOODWILL_PARTIAL"


class ServiceOption(str, Enum):
    STANDARD = "STANDARD"
    LOANER = "LOANER"
    ADVANCE_EXCHANGE = "ADVANCE_EXCHANGE"


class Decision(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class Repairability(str, Enum):
    REPAIRABLE = "REPAIRABLE"
    BER = "BER"


class ReturnReason(str, Enum):
    REPAIRED = "REPAIRED"
    REPLACED = "REPLACED"
    UNREPAIRED = "UNREPAIRED"


class QuoteStatus(str, Enum):
    SENT = "SENT"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class RepairLineStatus(str, Enum):
    CONSUMED = "CONSUMED"
    REVERSED = "REVERSED"


class LoanerUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SHIPPED_OUT = "SHIPPED_OUT"
    INSPECTION = "INSPECTION"
    RETIRED = "RETIRED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    CLOSED_RETURNED = "CLOSED_RETURNED"
    CLOSED_DAMAGED = "CLOSED_DAMAGED"
    CLOSED_FORFEITED = "CLOSED_FORFEITED"
    CANCELLED = "CANCELLED"


class ReservationMode(str, Enum):
    LOANER = "LOANER"
    ADVANCE_EXCHANGE = "ADVANCE_EXCHANGE"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONTAINMENT_ACTIVE = "CONTAINMENT_ACTIVE"
    RESOLVED = "RESOLVED"
    MONITORING = "MONITORING"
    CLOSED_FINAL = "CLOSED_FINAL"


class BayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class Channel(str, Enum):
    RETAIL = "RETAIL"
    ENTERPRISE = "ENTERPRISE"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NotificationEventType(str, Enum):
    RMA_AUTHORIZED = "RMA_AUTHORIZED"
    RECEIVED = "RECEIVED"
    QUOTE_SENT = "QUOTE_SENT"
    QUOTE_APPROVED = "QUOTE_APPROVED"
    QUOTE_DECLINED = "QUOTE_DECLINED"
    QUOTE_EXPIRED = "QUOTE_EXPIRED"
    SHIPPED = "SHIPPED"
    SLA_BREACH = "SLA_BREACH"
    LOANER_LATE = "LOANER_LATE"
    ESCALATION_OPENED = "ESCALATION_OPENED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (common_fields: id, created_at, updated_at, version) ---

class Customer(TypedDict, total=False):
    id: str
    name: str
    email: str
    credit_limit_cents: int
    loyalty_tier: str
    deposit_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductModel(TypedDict, total=False):
    id: str
    model_code: str
    description: str
    standard_warranty_days: int
    registration_bonus_days: int
    replacement_cost_cents: int
    flat_rate_repair_cents: int
    labor_rate_cents_per_minute: int
    replace_threshold_pct: int
    sla_turnaround_business_days: int
    loaner_grace_days: int
    recurring_failure_threshold: int
    quote_valid_days: int
    containment_flag: bool
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    serial_number: str
    model_id: str
    customer_id: str
    channel: str
    purchase_date: str
    ship_date: str
    registration_date: Optional[str]
    disposition: str
    created_at: str
    updated_at: str
    version: int


class ServiceRMA(TypedDict, total=False):
    id: str
    rma_number: str
    customer_id: str
    unit_id: str
    service_option: str
    reported_issue: str
    status: str
    coverage_path: Optional[str]
    warranty_end_date_used: Optional[str]
    goodwill_pct: int
    warranty_override_by: Optional[str]
    provisional_estimate_cents: Optional[int]
    final_estimate_cents: Optional[int]
    decision: Optional[str]
    decision_overridden: bool
    repairability: Optional[str]
    labor_minutes_est: Optional[int]
    planned_parts: List[dict]
    diagnosed_by: Optional[str]
    repair_completed_by: Optional[str]
    primary_failure_code_id: Optional[str]
    bay_id: Optional[str]
    bay_start_date: Optional[str]
    bay_end_date: Optional[str]
    authorized_at: Optional[str]
    received_at: Optional[str]
    shipped_at: Optional[str]
    closed_at: Optional[str]
    sla_pause_intervals: List[dict]
    sla_breached: bool
    engineering_review_pending: bool
    rework_count: int
    return_reason: Optional[str]
    current_quote_id: Optional[str]
    settlement_gross_cents: Optional[int]
    settlement_loyalty_credit_cents: Optional[int]
    settlement_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    rma_id: str
    quote_seq: int
    status: str
    lines: List[dict]
    labor_minutes: int
    labor_cents: int
    parts_subtotal_cents: int
    discount_pct: int
    discount_cents: int
    taxable_cents: int
    tax_cents: int
    expedite: bool
    expedite_fee_cents: int
    total_cents: int
    sent_at: str
    expires_at: str
    decided_at: Optional[str]
    payment_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairLine(TypedDict, total=False):
    id: str
    rma_id: str
    part_id: str
    failure_code_id: str
    quantity: int
    unit_cost_cents: int
    line_total_cents: int
    status: str
    consumed_by: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    sku: str
    name: str
    unit_cost_cents: int
    stock_on_hand: int
    reorder_point: int
    created_at: str
    updated_at: str
    version: int


class FailureCode(TypedDict, total=False):
    id: str
    code: str
    description: str
    severity: str
    created_at: str
    updated_at: str
    version: int


class DepotBay(TypedDict, total=False):
    id: str
    bay_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanerUnit(TypedDict, total=False):
    id: str
    asset_tag: str
    model_id: str
    condition_grade: str
    deposit_value_cents: int
    status: str
    completed_loan_cycles: int
    created_at: str
    updated_at: str
    version: int


class LoanerReservation(TypedDict, total=False):
    id: str
    rma_id: str
    loaner_unit_id: str
    mode: str
    start_date: str
    end_date: str
    status: str
    shipped_at: Optional[str]
    due_date: Optional[str]
    returned_at: Optional[str]
    late_fee_cents: int
    damage_fee_cents: int
    forfeit_charge_cents: int
    late_notification_sent: bool
    created_at: str
    updated_at: str
    version: int


class EngineeringEscalation(TypedDict, total=False):
    id: str
    rma_id: str
    model_id: str
    failure_code_id: str
    trigger_source: str
    status: str
    monitoring_until: Optional[str]
    recurrence_count: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false): carries ONLY id + created_at — no
# updated_at, no version (PRD §2.5: both are absent on notification events).
class NotificationEvent(TypedDict, total=False):
    id: str
    created_at: str
    rma_id: str
    event_type: str
    recipient: str
    message: str
