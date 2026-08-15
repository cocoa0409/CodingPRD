"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CONTRACTOR_ADMIN = "ContractorAdmin"
    ESTIMATOR = "Estimator"
    FIELD_TECHNICIAN = "FieldTechnician"
    ADJUSTER = "Adjuster"
    CUSTOMER = "Customer"


class CauseOfLoss(str, Enum):
    WATER = "WATER"
    FIRE = "FIRE"
    WIND = "WIND"
    MOLD = "MOLD"
    HAIL = "HAIL"


class DeductibleType(str, Enum):
    FLAT = "FLAT"
    PERCENT_OF_COVERAGE_A = "PERCENT_OF_COVERAGE_A"


class EntryKind(str, Enum):
    MATERIAL = "MATERIAL"
    LABOR = "LABOR"
    EQUIPMENT = "EQUIPMENT"


class InspectionType(str, Enum):
    INITIAL = "INITIAL"
    VERIFICATION = "VERIFICATION"


class PhotoTag(str, Enum):
    LOSS_OVERVIEW = "LOSS_OVERVIEW"
    AREA = "AREA"
    MOISTURE_PROOF = "MOISTURE_PROOF"
    SUPPLEMENT_EVIDENCE = "SUPPLEMENT_EVIDENCE"
    COMPLETION = "COMPLETION"


class ClaimStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSING = "ASSESSING"
    ESTIMATING = "ESTIMATING"
    NEGOTIATING = "NEGOTIATING"
    APPROVED = "APPROVED"
    AUTHORIZED = "AUTHORIZED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETE = "COMPLETE"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    REVISED = "REVISED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    DENIED = "DENIED"


class EstimateType(str, Enum):
    INITIAL = "INITIAL"
    SUPPLEMENT = "SUPPLEMENT"


class LineNegotiationStatus(str, Enum):
    PENDING = "PENDING"
    DISPUTED = "DISPUTED"
    AGREED = "AGREED"
    REMOVED = "REMOVED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class SupplementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RoundStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"


class DispositionStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CodeUpgradeStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class WorkAuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    CLEARED = "CLEARED"
    RETURNED = "RETURNED"
    VOIDED = "VOIDED"


class PaymentType(str, Enum):
    ACV_ADVANCE = "ACV_ADVANCE"
    DEPRECIATION_RECOVERY = "DEPRECIATION_RECOVERY"
    DEDUCTIBLE = "DEDUCTIBLE"
    CUSTOMER_BALANCE = "CUSTOMER_BALANCE"


class PaymentDirection(str, Enum):
    CARRIER_TO_CONTRACTOR = "CARRIER_TO_CONTRACTOR"
    CUSTOMER_TO_CONTRACTOR = "CUSTOMER_TO_CONTRACTOR"


class PaymentPosture(str, Enum):
    UNPAID = "UNPAID"
    ADVANCE_PAID = "ADVANCE_PAID"
    DEPRECIATION_PENDING = "DEPRECIATION_PENDING"
    PAID_IN_FULL = "PAID_IN_FULL"


# --- Entity TypedDicts (all resources carry id/created_at/updated_at/version, PRD §2.5) ---

class Carrier(TypedDict, total=False):
    id: str
    name: str
    tax_rate: float
    overhead_rate: float
    profit_rate: float
    o_and_p_min_trades: int
    negotiation_response_days: int
    created_at: str
    updated_at: str
    version: int


class PriceListEntry(TypedDict, total=False):
    id: str
    carrier_id: str
    category_code: str
    trade: str
    kind: str
    unit: str
    unit_price_cents: int
    tax_applicable: bool
    o_and_p_eligible: bool
    default_depreciation_pct: float
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    customer_id: str
    carrier_id: str
    policy_number: str
    coverage_a_limit_cents: int
    deductible_type: str
    flat_deductible_cents: Optional[int]
    deductible_pct: Optional[float]
    recoverable_depreciation: bool
    ordinance_coverage_pct: float
    ordinance_flat_cap_cents: int
    period_start: str
    period_end: str
    ordinance_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    customer_id: str
    cause_of_loss: str
    date_of_loss: str
    loss_address: str
    status: str
    deductible_cents: int
    rcv_total_cents: int
    acv_total_cents: int
    recoverable_depreciation_cents: int
    carrier_paid_cents: int
    customer_paid_cents: int
    deductible_collected_cents: int
    outstanding_balance_cents: int
    ordinance_consumed_cents: int
    payment_posture: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    claim_id: str
    type: str
    assignee_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    completed_at: Optional[str]
    drying_days_worst_variant: Optional[int]
    drying_days_mean_variant: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MoistureReading(TypedDict, total=False):
    id: str
    inspection_id: str
    area: str
    material: str
    reading_value: float
    dry_standard: float
    recorded_at: str
    is_wet: bool
    created_at: str
    updated_at: str
    version: int


class Photo(TypedDict, total=False):
    id: str
    claim_id: str
    inspection_id: Optional[str]
    supplement_id: Optional[str]
    tag: str
    file_ref: str
    captured_at: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict, total=False):
    id: str
    claim_id: str
    supplement_id: Optional[str]
    type: str
    revision_number: int
    status: str
    rcv_total_cents: int
    tax_total_cents: int
    overhead_profit_total_cents: int
    depreciation_total_cents: int
    recoverable_depreciation_cents: int
    acv_total_cents: int
    grand_total_cents: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EstimateLine(TypedDict, total=False):
    id: str
    estimate_id: str
    price_list_entry_id: str
    category_code: str
    trade: str
    kind: str
    description: str
    qty: float
    unit_price_cents: int
    depreciation_pct: float
    depreciation_recoverable: bool
    tax_applicable: bool
    o_and_p_eligible: bool
    negotiation_status: str
    qty_actual: Optional[float]
    extended_cents: int
    depreciation_cents: int
    tax_cents: int
    created_at: str
    updated_at: str
    version: int


class Supplement(TypedDict, total=False):
    id: str
    claim_id: str
    narrative: str
    status: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NegotiationRound(TypedDict, total=False):
    id: str
    estimate_id: str
    round_number: int
    status: str
    due_at: str
    disputed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class LineDisposition(TypedDict, total=False):
    id: str
    negotiation_round_id: str
    estimate_line_id: str
    proposed_qty: Optional[float]
    proposed_unit_price_cents: Optional[int]
    propose_removal: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CodeUpgrade(TypedDict, total=False):
    id: str
    claim_id: str
    code_citation: str
    description: str
    estimated_cost_cents: int
    approved_cost_cents: Optional[int]
    covered_cents: Optional[int]
    customer_responsibility_cents: Optional[int]
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkAuthorization(TypedDict, total=False):
    id: str
    claim_id: str
    direct_pay_assignment: bool
    deductible_acknowledged: bool
    status: str
    scope_rcv_cents: Optional[int]
    signed_at: Optional[str]
    expires_at: Optional[str]
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    claim_id: str
    status: str
    total_cents: int
    applied_cents: int
    outstanding_cents: int
    created_by_user_id: str
    issued_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    claim_id: str
    invoice_id: Optional[str]
    type: str
    direction: str
    amount_cents: int
    auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int
