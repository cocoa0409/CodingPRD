"""Domain types: entity TypedDicts, status enums, role enum.

Field names and field sets are taken verbatim from the PRD entity definitions.
Entities that the PRD lists as carrying `updated_at` and `version` expose them
here; the six configuration / append-only record kinds carry only `id` and
`created_at` (PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    WARRANTY_ADMIN = "WarrantyAdmin"
    CLAIM_ADJUDICATOR = "ClaimAdjudicator"
    ADJUDICATION_MANAGER = "AdjudicationManager"
    FIELD_AUDITOR = "FieldAuditor"
    AUDIT_MANAGER = "AuditManager"
    APPEAL_REVIEWER = "AppealReviewer"
    DEALER_WARRANTY_ADMIN = "DealerWarrantyAdmin"


class LaborRateMethod(str, Enum):
    RETAIL_SAMPLE = "RETAIL_SAMPLE"
    TIME_AND_PRICE = "TIME_AND_PRICE"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class LaborRateRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class LaborOperationCategory(str, Enum):
    BASIC = "BASIC"
    POWERTRAIN = "POWERTRAIN"


class CoverageType(str, Enum):
    BASIC = "BASIC"
    POWERTRAIN = "POWERTRAIN"
    NONE = "NONE"
    GOODWILL = "GOODWILL"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUSPENDED = "SUSPENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    DEBITED = "DEBITED"
    CREDIT_REINSTATED = "CREDIT_REINSTATED"


class EditCode(str, Enum):
    EXCESSIVE_TIME = "EXCESSIVE_TIME"
    HIGH_VALUE = "HIGH_VALUE"
    NO_COVERAGE = "NO_COVERAGE"
    NARRATIVE_THIN = "NARRATIVE_THIN"
    REPEAT_REPAIR = "REPEAT_REPAIR"
    DEALER_POSTURE_HOLD = "DEALER_POSTURE_HOLD"


class EditSeverity(str, Enum):
    SUSPEND = "SUSPEND"
    WARN = "WARN"


class PartsReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    ANALYZED = "ANALYZED"
    NOT_RETURNED = "NOT_RETURNED"
    WAIVED = "WAIVED"


class AnalysisResult(str, Enum):
    DEFECT_CONFIRMED = "DEFECT_CONFIRMED"
    NO_DEFECT_FOUND = "NO_DEFECT_FOUND"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_FIELD = "IN_FIELD"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class FindingCode(str, Enum):
    NO_REPAIR_ORDER = "NO_REPAIR_ORDER"
    NO_TECHNICIAN_SIGNATURE = "NO_TECHNICIAN_SIGNATURE"
    PART_NOT_ON_HAND = "PART_NOT_ON_HAND"
    TIME_NOT_DOCUMENTED = "TIME_NOT_DOCUMENTED"
    NARRATIVE_UNSUPPORTED = "NARRATIVE_UNSUPPORTED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    CHARGED_BACK = "CHARGED_BACK"
    OVERTURNED = "OVERTURNED"
    UPHELD = "UPHELD"


class AppealStatus(str, Enum):
    FILED = "FILED"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    DENIED = "DENIED"


class GoodwillStatus(str, Enum):
    PENDING = "PENDING"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class LedgerSourceType(str, Enum):
    PARTS_NON_RETURN = "PARTS_NON_RETURN"
    PARTS_NO_DEFECT = "PARTS_NO_DEFECT"
    LATE_RETURN_REVERSAL = "LATE_RETURN_REVERSAL"
    AUDIT_CHARGEBACK_SAMPLE = "AUDIT_CHARGEBACK_SAMPLE"
    AUDIT_CHARGEBACK_EXTRAPOLATION = "AUDIT_CHARGEBACK_EXTRAPOLATION"
    APPEAL_REVERSAL_SAMPLE = "APPEAL_REVERSAL_SAMPLE"
    APPEAL_REVERSAL_EXTRAPOLATION = "APPEAL_REVERSAL_EXTRAPOLATION"


# --- Configuration and append-only records: only id + created_at (PRD §2.4) ---


class StateLawProfile(TypedDict):
    id: str
    created_at: str
    state_code: str
    markup_cap_pct: float
    labor_rate_method: str
    min_sample_repair_orders: int
    max_labor_rate_cents: int
    deemed_approved_days: int
    appeal_window_days: int


class Vehicle(TypedDict):
    id: str
    created_at: str
    vin: str
    model_year: int
    warranty_start_date: str
    in_service_odometer: int
    basic_months: int
    basic_miles: int
    powertrain_months: int
    powertrain_miles: int


class LaborOperation(TypedDict):
    id: str
    created_at: str
    op_code: str
    description: str
    standard_time_hours: float
    max_time_hours: float
    category: str
    requires_causal_part: bool
    causal_failure_group: Optional[str]
    overlap_group: str


class PartCatalogItem(TypedDict):
    id: str
    created_at: str
    part_number: str
    description: str
    dealer_net_cents: int
    failure_group: str
    return_required: bool
    retention_days: int


class ClaimEdit(TypedDict):
    id: str
    created_at: str
    claim_id: str
    conflicting_claim_id: Optional[str]
    edit_code: str
    severity: str
    detail: str
    resolved_at: Optional[str]


class ChargebackLedgerEntry(TypedDict):
    id: str
    created_at: str
    dealer_id: str
    source_type: str
    source_id: str
    claim_id: Optional[str]
    amount_cents: int
    balance_after_cents: int


# --- Records carrying updated_at and version (PRD §2.4) ---


class Dealer(TypedDict):
    id: str
    dealer_code: str
    name: str
    state_law_profile_id: str
    approved_labor_rate_cents: int
    approved_parts_markup_pct: float
    labor_rate_effective_date: Optional[str]
    vehicles_in_operation: int
    status: str
    chargeback_balance_cents: int
    open_parts_return_count: int
    audit_hold: bool
    outlier_flag: bool
    created_at: str
    updated_at: str
    version: int


class LaborRateRequest(TypedDict):
    id: str
    dealer_id: str
    state_law_profile_id: str
    requested_labor_rate_cents: int
    requested_parts_markup_pct: float
    sample_repair_order_count: Optional[int]
    sample_median_rate_cents: Optional[int]
    effective_date: str
    statutory_ceiling_cents: int
    status: str
    approved_labor_rate_cents: Optional[int]
    approved_parts_markup_pct: Optional[float]
    deemed_approved: bool
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    dealer_id: str
    vehicle_id: str
    labor_operation_id: str
    causal_part_id: Optional[str]
    resubmission_of_claim_id: Optional[str]
    repair_order_number: str
    repair_date: str
    odometer_at_repair: int
    claimed_labor_hours: float
    claimed_parts_qty: int
    complaint_text: str
    cause_text: str
    correction_text: str
    coverage_type: str
    status: str
    payment_status: str
    provisional_total_cents: int
    provisional_labor_amount_cents: int
    provisional_parts_amount_cents: int
    approved_labor_hours: Optional[float]
    approved_parts_qty: Optional[int]
    approved_labor_amount_cents: int
    approved_parts_amount_cents: int
    approved_total_cents: int
    dealer_participation_cents: int
    oem_payable_cents: int
    debited_amount_cents: int
    reinstated_amount_cents: int
    suspend_edit_count: int
    void_reason: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartsReturnRequest(TypedDict):
    id: str
    claim_id: str
    part_id: str
    due_date: str
    received_date: Optional[str]
    status: str
    analysis_result: Optional[str]
    analysis_note: Optional[str]
    debit_amount_cents: int
    reversed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class DealerAudit(TypedDict):
    id: str
    dealer_id: str
    period_start: str
    period_end: str
    sample_size: int
    lead_auditor_user_id: str
    status: str
    sample_paid_snapshot_cents: int
    population_paid_snapshot_cents: int
    error_rate: float
    extrapolation_factor: float
    sample_chargeback_cents: int
    extrapolated_chargeback_cents: int
    total_chargeback_cents: int
    findings_issued_at: Optional[str]
    appeal_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    audit_id: str
    claim_id: str
    appeal_id: Optional[str]
    finding_code: str
    unsupported_amount_cents: int
    evidence_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditAppeal(TypedDict):
    id: str
    audit_id: str
    filed_by_dealer_id: str
    grounds: str
    contested_finding_ids: List[str]
    overturned_finding_ids: List[str]
    reviewer_user_id: Optional[str]
    status: str
    reinstated_amount_cents: int
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GoodwillAuthorization(TypedDict):
    id: str
    claim_id: str
    requested_by_user_id: str
    requested_amount_cents: int
    policy_adjustment_pct: float
    justification: str
    adjudicator_limit_cents: int
    manager_limit_cents: int
    out_of_warranty_margin_pct: float
    status: str
    approved_amount_cents: Optional[int]
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
