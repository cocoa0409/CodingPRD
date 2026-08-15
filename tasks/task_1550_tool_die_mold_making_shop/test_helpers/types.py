"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    ESTIMATOR = "Estimator"
    TOOLING_ENGINEER = "ToolingEngineer"
    PROJECT_MANAGER = "ProjectManager"
    QUALITY_MANAGER = "QualityManager"
    FINANCE_ADMIN = "FinanceAdmin"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Enumerated field domains (PRD §3)
# ---------------------------------------------------------------------------
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ToolType(str, Enum):
    PROGRESSIVE_DIE = "PROGRESSIVE_DIE"
    TRANSFER_DIE = "TRANSFER_DIE"
    INJECTION_MOLD = "INJECTION_MOLD"
    BLOW_MOLD = "BLOW_MOLD"
    COMPRESSION_MOLD = "COMPRESSION_MOLD"


class DieClass(str, Enum):
    CLASS_101 = "CLASS_101"
    CLASS_102 = "CLASS_102"
    CLASS_103 = "CLASS_103"
    CLASS_104 = "CLASS_104"
    CLASS_105 = "CLASS_105"


class ToolDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"


class QuoteKind(str, Enum):
    BUDGETARY = "BUDGETARY"
    FIRM = "FIRM"


class WarrantyTerms(str, Enum):
    LINEAR_PRORATION = "LINEAR_PRORATION"
    DECLINING_BALANCE = "DECLINING_BALANCE"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class BuildJobStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_BUILD = "IN_BUILD"
    TRYOUT_PHASE = "TRYOUT_PHASE"
    BUYOFF_PASSED = "BUYOFF_PASSED"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"
    ON_HOLD = "ON_HOLD"


class MilestoneCode(str, Enum):
    DESIGN_COMPLETE = "DESIGN_COMPLETE"
    MATERIAL_STAGED = "MATERIAL_STAGED"
    MACHINING_COMPLETE = "MACHINING_COMPLETE"
    T1_TRYOUT_DONE = "T1_TRYOUT_DONE"
    BUYOFF_SIGNED = "BUYOFF_SIGNED"
    DELIVERY_ACCEPTED = "DELIVERY_ACCEPTED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    EARNED = "EARNED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    REOPENED = "REOPENED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class TryoutSampleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    BOUGHT_OFF = "BOUGHT_OFF"
    REJECTED = "REJECTED"


class EcoRequestedBy(str, Enum):
    SHOP = "SHOP"
    CUSTOMER = "CUSTOMER"


class EcoStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IMPACT_ASSESSED = "IMPACT_ASSESSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VERIFIED = "VERIFIED"


class ReworkAuthorizationStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ToolPhysicalStatus(str, Enum):
    IN_BUILD = "IN_BUILD"
    TRYOUT = "TRYOUT"
    AWAITING_SHIPMENT = "AWAITING_SHIPMENT"
    IN_TRANSIT = "IN_TRANSIT"
    IN_PRODUCTION = "IN_PRODUCTION"
    RETURNED_FOR_REPAIR = "RETURNED_FOR_REPAIR"


class ToolOwnershipStatus(str, Enum):
    SHOP_RETAINED = "SHOP_RETAINED"
    TRANSFERRED = "TRANSFERRED"


class ShotReportStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    REPAIR_SCHEDULED = "REPAIR_SCHEDULED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class SpareInsertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    DISCONTINUED = "DISCONTINUED"


class PressId(str, Enum):
    PRESS_200T = "PRESS_200T"
    PRESS_500T = "PRESS_500T"
    PRESS_800T = "PRESS_800T"


class MachineId(str, Enum):
    CNC_1 = "CNC_1"
    CNC_2 = "CNC_2"
    EDM_1 = "EDM_1"
    GRIND_1 = "GRIND_1"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts. All resources carry id/created_at/updated_at/version
# EXCEPT payments and shot reports, which carry only id and created_at
# (PRD §2.5).
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    company_name: str
    contact_email: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ToolDesign(TypedDict):
    id: str
    customer_id: str
    part_number: str
    tool_type: str
    die_class: str
    cavity_count: int
    design_complexity_score: int
    revision_number: int
    supersedes_design_id: Optional[str]
    quoted_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    customer_id: str
    tool_design_id: str
    quote_kind: str
    requested_lead_weeks: int
    expedited: bool
    warranty_terms: str
    base_price_cents: int
    surcharge_pct: float
    subtotal_cents: int
    contingency_pct: float
    total_price_cents: int
    issued_at: Optional[str]
    valid_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildJob(TypedDict):
    id: str
    quote_id: str
    customer_id: str
    tool_design_id: str
    die_class: str
    contract_value_cents: int
    billed_cents: int
    paid_cents: int
    credit_balance_cents: int
    net_paid_cents: int
    outstanding_cents: int
    open_eco_count: int
    status: str
    hold_return_state: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildMilestone(TypedDict):
    id: str
    build_job_id: str
    seq: int
    code: str
    billing_pct: int
    planned_amount_cents: int
    paid_cents: int
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgressInvoice(TypedDict):
    id: str
    build_job_id: str
    build_milestone_id: str
    invoice_number: str
    amount_cents: int
    paid_cents: int
    balance_due_cents: int
    issued_by_user_id: str
    due_date: str
    void_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentAllocation(TypedDict):
    invoice_id: str
    applied_cents: int


class Payment(TypedDict):
    # Append-only record: id + created_at only, NO updated_at/version (PRD §2.5).
    id: str
    build_job_id: str
    amount_cents: int
    allocations: List[PaymentAllocation]
    recorded_by_user_id: str
    created_at: str


class TryoutSample(TypedDict):
    id: str
    build_job_id: str
    press_reservation_id: str
    round_number: int
    sample_qty: Optional[int]
    shots_used: Optional[int]
    measured_report_ref: Optional[str]
    defect_codes: Optional[List[str]]
    status: str
    created_at: str
    updated_at: str
    version: int


class EngineeringChange(TypedDict):
    id: str
    build_job_id: str
    requested_by: str
    description: str
    affects_from_milestone_seq: int
    rework_hours: Optional[float]
    scrapped_material_cost_cents: Optional[int]
    lead_extension_weeks: Optional[int]
    labor_cost_cents: int
    material_cost_cents: int
    impact_cost_cents: int
    schedule_penalty_cents: int
    total_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReworkAuthorization(TypedDict):
    id: str
    engineering_change_id: str
    build_job_id: str
    authorized_cost_cents: int
    consumed_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ToolAsset(TypedDict):
    id: str
    build_job_id: str
    customer_id: str
    serial_number: str
    die_class: str
    warranty_terms: str
    warranty_shot_limit: int
    warranty_expires_at: Optional[str]
    tryout_shots: int
    reported_shots: int
    lifetime_shots: int
    contract_snapshot_cents: int
    carrier: Optional[str]
    tracking_number: Optional[str]
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    physical_status: str
    ownership_status: str
    created_at: str
    updated_at: str
    version: int


class ShotReport(TypedDict):
    # Append-only record: id + created_at only, NO updated_at/version (PRD §2.5).
    id: str
    tool_asset_id: str
    report_period_end: str
    shots_in_period: int
    status: str
    created_at: str


class WarrantyClaim(TypedDict):
    id: str
    tool_asset_id: str
    defect_description: str
    estimated_repair_cost_cents: int
    claimed_at_shot_count: int
    approved_credit_cents: Optional[int]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpareInsert(TypedDict):
    id: str
    tool_asset_id: str
    insert_code: str
    unit_cost_cents: int
    on_hand: int
    reorder_point: int
    reorder_needed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PressReservation(TypedDict):
    id: str
    build_job_id: str
    press_id: str
    start_time: str
    end_time: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MachineReservation(TypedDict):
    id: str
    build_job_id: str
    machine_id: str
    start_time: str
    end_time: str
    duration_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int
