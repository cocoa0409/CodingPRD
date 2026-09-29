"""Entity shapes, status enumerations and the role vocabulary of the PRD.

Every resource carries an opaque UUID `id`, an ISO-8601 `created_at` and
`updated_at`, and an integer `version` that starts at 1 — with one exception:
the evidence item is append-only audit history and carries only `id` and
`created_at`, so `EvidenceItem` deliberately omits `updated_at` and `version`.
"""
from typing import List, Optional, TypedDict

# --------------------------------------------------------------------- roles
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_DC_INSPECTOR = "DCInspector"
ROLE_VENDOR = "Vendor"
ROLE_AP_ACCOUNTANT = "APAccountant"
ROLE_CATEGORY_BUYER = "CategoryBuyer"

ALL_ROLES: List[str] = [
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DC_INSPECTOR,
    ROLE_VENDOR,
    ROLE_AP_ACCOUNTANT,
    ROLE_CATEGORY_BUYER,
]

# ------------------------------------------------------------ status vocabularies
VENDOR_STATUSES = ["ACTIVE", "PROBATION", "SOURCING_HOLD"]
GUIDE_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED"]
GUIDE_SCOPE_CODES = ["ALL", "SHIPMENT", "LABELING", "PACKAGING", "DOCUMENTATION"]
REQUIREMENT_DOMAINS = ["SHIPMENT", "LABELING", "PACKAGING", "DOCUMENTATION"]
SEVERITY_TIERS = ["TIER_1", "TIER_2", "TIER_3"]
PO_STATUSES = ["OPEN", "PARTIALLY_RECEIVED", "RECEIVED"]
SHIPMENT_STATUSES = ["IN_TRANSIT", "RECEIVED"]
VIOLATION_STATUSES = ["DETECTED", "EVIDENCE_COMPLETE", "VOIDED", "CHARGED"]
EVIDENCE_SUBJECT_TYPES = ["VIOLATION", "DISPUTE"]
EVIDENCE_KINDS = ["PHOTO", "SCAN", "MEASUREMENT", "DOCUMENT"]
ASSESSMENT_VARIANTS = ["STANDARD", "GRACE_FIRST_OCCURRENCE"]
CHARGEBACK_DISPUTE_STATUSES = [
    "NONE",
    "OPEN",
    "UPHELD",
    "REVERSED",
    "PARTIALLY_REVERSED",
]
SETTLEMENT_STATUSES = [
    "ASSESSED",
    "PARTIALLY_RECOVERED",
    "RECOVERED",
    "WRITTEN_OFF",
]
DISPUTE_REASON_CODES = [
    "NOT_OUR_LABEL",
    "CARRIER_CAUSED",
    "DUPLICATE_ASSESSMENT",
    "EVIDENCE_INSUFFICIENT",
    "FEE_MISCALCULATED",
]
DISPUTE_STATUSES = [
    "SUBMITTED",
    "INFO_REQUESTED",
    "APPROVED_FULL",
    "APPROVED_PARTIAL",
    "DENIED",
]
SCORECARD_STATUSES = ["OPEN", "MEASURED", "FINALIZED"]
MEASUREMENT_VARIANTS = ["ORDER_WEIGHTED", "UNIT_WEIGHTED"]
CAP_STATUSES = [
    "ISSUED",
    "VENDOR_SUBMITTED",
    "REJECTED",
    "ACCEPTED",
    "ESCALATED",
    "CLOSED_SUCCESS",
    "CLOSED_UNREMEDIATED",
]
BUYING_DECISIONS = ["NONE", "RANGE_REVIEW", "SOURCING_HOLD"]
DEDUCTION_STATUSES = ["DRAFT", "POSTED", "REVERSED"]
ALLOCATION_SOURCE_TYPES = ["DEDUCTION", "CASH"]
ALLOCATION_EFFECTIVE_STATUSES = ["PENDING", "EFFECTIVE", "REVERSED"]


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Vendor(CommonFields, total=False):
    vendor_code: str
    legal_name: str
    payment_terms_days: int
    status: str
    otif_score: Optional[float]
    open_chargeback_cents: int
    recovered_lifetime_cents: int
    refund_due_cents: int
    open_violation_count: int
    open_cap_count: int
    repeat_offender_flag: bool
    exposure_alert_flag: bool


class RoutingGuide(CommonFields, total=False):
    guide_code: str
    title: str
    scope_code: str
    effective_from: str
    effective_until: Optional[str]
    supersedes_guide_id: Optional[str]
    status: str
    requirement_count: int
    published_at: Optional[str]
    published_by_user_id: Optional[str]


class RoutingRequirement(CommonFields, total=False):
    guide_id: str
    requirement_code: str
    domain: str
    severity_tier: str
    min_evidence_count: int
    fixed_fee_cents: int
    per_unit_recovery_cents: int
    handling_pct: float
    min_fee_cents: int
    cap_cents: int
    effective_until: Optional[str]


class PurchaseOrder(CommonFields, total=False):
    vendor_id: str
    po_number: str
    ordered_units: int
    unit_cost_cents: int
    ship_window_start: str
    ship_window_end: str
    must_arrive_by: str
    status: str
    received_units: int
    first_receipt_at: Optional[str]


class Shipment(CommonFields, total=False):
    po_id: str
    asn_number: str
    shipped_units: int
    carton_count: int
    received_units: Optional[int]
    arrived_at: Optional[str]
    invoice_value_cents: int
    status: str
    open_violation_count: int
    evidence_capture_count: int


class ComplianceViolation(CommonFields, total=False):
    shipment_id: str
    requirement_id: str
    affected_units: int
    affected_cartons: int
    narrative: str
    detected_by_user_id: str
    detected_at: str
    status: str
    evidence_count: int
    void_reason: Optional[str]


class EvidenceItem(TypedDict, total=False):
    """Append-only audit history: `id` and `created_at` only, no version."""

    id: str
    created_at: str
    violation_id: Optional[str]
    dispute_id: Optional[str]
    subject_type: str
    kind: str
    reference_uri: str
    note: Optional[str]
    captured_by_user_id: str
    captured_at: str


class Chargeback(CommonFields, total=False):
    violation_id: str
    vendor_id: str
    requirement_id: str
    assessment_variant: str
    fixed_fee_cents: int
    cost_recovery_cents: int
    gross_assessed_cents: int
    reversal_cents: int
    recovered_cents: int
    outstanding_cents: int
    evidence_at_assessment_count: int
    dispute_status: str
    deduction_posted: bool
    settlement_status: str
    assessed_at: str


class VendorDispute(CommonFields, total=False):
    chargeback_id: str
    vendor_id: str
    reason_code: str
    claimed_reversal_cents: int
    narrative: str
    status: str
    round_count: int
    reason_ceiling_pct: Optional[float]
    approved_reversal_cents: int
    goodwill_cents: int
    submitted_at: str
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    information_request_note: Optional[str]
    review_note: Optional[str]


class Scorecard(CommonFields, total=False):
    vendor_id: str
    period_code: str
    period_start: str
    period_end: str
    tolerance_early_days: int
    tolerance_late_days: int
    fill_tolerance_pct: float
    measurement_variant: Optional[str]
    status: str
    measured_po_count: int
    on_time_count: int
    in_full_count: int
    otif_count: int
    on_time_pct: float
    fill_rate_pct: float
    otif_pct: float
    composite_score: float
    cap_required: bool
    measured_at: Optional[str]
    finalized_at: Optional[str]


class CorrectiveActionPlan(CommonFields, total=False):
    vendor_id: str
    trigger_scorecard_id: str
    predecessor_cap_id: Optional[str]
    status: str
    escalation_level: int
    repeat_count: int
    milestone_text: Optional[str]
    committed_completion_at: Optional[str]
    due_at: str
    buying_decision: str
    submission_round: int
    issued_at: str
    decided_at: Optional[str]
    escalated_at: Optional[str]
    closed_at: Optional[str]
    review_note: Optional[str]
    escalation_note: Optional[str]
    closure_note: Optional[str]


class Deduction(CommonFields, total=False):
    vendor_id: str
    invoice_reference: str
    status: str
    amount_cents: int
    allocation_count: int
    over_allocated_cents: int
    posted_at: Optional[str]
    posted_by_user_id: Optional[str]
    reversed_at: Optional[str]
    reversal_reason: Optional[str]


class RecoveryAllocation(CommonFields, total=False):
    chargeback_id: str
    deduction_id: Optional[str]
    source_type: str
    allocated_cents: int
    remittance_reference: Optional[str]
    effective_status: str
    applied_by_user_id: str
    applied_at: str
