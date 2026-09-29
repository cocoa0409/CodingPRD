"""TypedDict shapes for every resource the price-integrity API returns.

Fourteen of the fifteen resources carry the common ``created_at``,
``updated_at`` and ``version`` fields.  ``ScanLine`` is the single exception:
it carries only ``id`` and ``created_at``, so its shape deliberately omits
``updated_at`` and ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """Identity and audit fields shared by every resource but ScanLine."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(CommonFields):
    code: str
    name: str
    unit_price_required: bool
    unit_price_uom_rule: str
    unit_price_decimal_places: int
    unit_price_rounding: str
    scanner_error_rate_threshold_pct: float
    default_rate_variant: str
    overcharge_refund_policy: str
    refund_fixed_bonus_cents: int
    refund_cap_cents: int
    refund_budget_per_audit_cents: int
    penalty_per_violation_cents: int
    penalty_max_cents: int
    signage_disclosure_codes: List[str]
    grace_period_hours: int
    accountability_variant: str


class Store(CommonFields):
    store_number: str
    name: str
    jurisdiction_id: str
    compliance_posture: str
    open_finding_count: int
    escalated_finding_count: int
    failed_audit_count_30d: int
    signage_violation_count: int
    label_backlog_count: int
    refund_liability_outstanding_cents: int
    refund_paid_total_cents: int
    cumulative_penalty_exposure_cents: int
    executed_file_count: int


class Aisle(CommonFields):
    store_id: str
    aisle_code: str
    category_code: str
    assigned_associate_id: Optional[str]
    last_audit_closed_at: Optional[str]


class Associate(CommonFields):
    store_id: str
    employee_number: str
    full_name: str
    role_code: str
    training_status: str
    certification_expires_at: Optional[str]
    last_training_module_code: Optional[str]
    last_training_score_pct: Optional[float]
    accountability_score: float
    issued_action_count: int
    verified_placement_count: int


class AccountabilityAction(CommonFields):
    associate_id: str
    action_type: str
    trigger_code: str
    status: str
    score_weight: int
    source_ref: Optional[str]
    issued_by_ref: str
    void_reason: Optional[str]


class PriceChangeFile(CommonFields):
    file_number: str
    jurisdiction_id: str
    effective_date: str
    scope_store_ids: List[str]
    priority: str
    status: str
    line_count: int
    verified_line_count: int
    distributed_at: Optional[str]
    superseded_by_file_id: Optional[str]


class PriceChangeLine(CommonFields):
    price_change_file_id: str
    item_upc: str
    item_description: str
    category_code: str
    old_retail_cents: int
    new_retail_cents: int
    net_content_qty: float
    net_content_uom: str
    promo_flag: bool
    line_status: str
    unit_price_display_cents: Optional[int]
    unit_price_basis_qty: Optional[float]
    unit_price_basis_uom: Optional[str]


class LabelTask(CommonFields):
    store_id: str
    price_change_line_id: str
    aisle_id: str
    assigned_associate_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    print_status: str
    placement_status: str
    printed_label_serial: Optional[str]
    placed_by_associate_id: Optional[str]
    verified_by_associate_id: Optional[str]
    placed_at: Optional[str]
    verified_at: Optional[str]
    observed_shelf_price_cents: Optional[int]
    rejection_count: int
    due_at: str
    overdue: bool


class ScannerAudit(CommonFields):
    store_id: str
    aisle_id: str
    auditor_associate_id: str
    audit_type: str
    scan_window_start: str
    scan_window_end: str
    status: str
    outcome: str
    sample_size: int
    overcharge_count: int
    undercharge_count: int
    reopen_count: int
    gross_error_rate_pct: Optional[float]
    net_overcharge_rate_pct: Optional[float]
    error_rate_pct: Optional[float]
    rate_variant_applied: Optional[str]
    closed_at: Optional[str]


class ScanLine(TypedDict):
    """Append-only evidence: only ``id`` and ``created_at``, no version."""

    id: str
    created_at: str
    scanner_audit_id: str
    item_upc: str
    shelf_price_cents: int
    register_price_cents: int
    variance_cents: int
    classification: str
    category_code: str


class PromoSignage(CommonFields):
    store_id: str
    aisle_id: str
    sign_code: str
    promo_start_at: str
    promo_end_at: str
    disclosure_codes: List[str]
    price_change_line_id: Optional[str]
    status: str
    compliance_state: str
    missing_disclosure_codes: List[str]
    posted_at: Optional[str]
    removed_at: Optional[str]


class RegulatoryInspection(CommonFields):
    store_id: str
    scanner_audit_id: str
    inspector_ref: str
    inspection_date: str
    status: str
    finding_count: int
    penalty_exposure_cents: int
    refund_liability_cents: int
    refund_credit_cents: int
    response_round: int
    assessed_penalty_cents: Optional[int]
    remediation_summary: Optional[str]
    closed_at: Optional[str]


class InspectionFinding(CommonFields):
    regulatory_inspection_id: str
    finding_code: str
    severity: str
    affected_item_count: int
    affected_aisle_code: Optional[str]
    status: str
    penalty_component_cents: int
    remediation_action_code: Optional[str]
    remediation_evidence_ref: Optional[str]
    waiver_reason: Optional[str]


class RefundClaim(CommonFields):
    scan_line_id: str
    store_id: str
    customer_ref: str
    claimed_amount_cents: int
    policy_applied: str
    status: str
    denial_reason: Optional[str]
    paid_at: Optional[str]


class CategoryBreakdownEntry(TypedDict):
    category_code: str
    sample_size: int
    error_count: int
    error_rate_pct: float


class ExceptionReport(CommonFields):
    store_id: str
    period_start_at: str
    period_end_at: str
    status: str
    audit_count: int
    scan_line_count: int
    category_breakdown: List[CategoryBreakdownEntry]
    top_category_code: Optional[str]
    top_category_error_rate_pct: Optional[float]
    root_cause_code: Optional[str]
    remediation_owner_associate_id: Optional[str]
    closure_note: Optional[str]


class SignageSweepResult(TypedDict):
    swept_count: int
    expired_count: int
    non_compliant_count: int
    compliance_posture: str


JsonDict = Dict[str, Any]
