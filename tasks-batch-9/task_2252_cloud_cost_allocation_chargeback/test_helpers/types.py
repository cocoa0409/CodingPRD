"""TypedDict shapes for the fifteen entities the PRD declares.

PRD §2.4 gives every entity `id`, `created_at`, `updated_at` and `version`, with
one stated exception: "`AllocationLine` is the single exception ... a line
carries only `id` and `created_at`; it has no `updated_at` and no `version`
field at all."  :class:`AllocationLine` therefore does **not** inherit
:class:`CommonFields`, and that asymmetry is deliberate.

These shapes are documentation for the suite, not runtime validation; every
member is optional so a response carrying extra keys is still describable.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict, total=False):
    """The four fields PRD §2.4 puts on every entity but AllocationLine."""

    id: str
    created_at: str
    updated_at: str
    version: int


class BusinessUnit(CommonFields, total=False):
    name: str
    cost_center_code: str
    parent_business_unit_id: Optional[str]
    chargeback_enabled: bool
    headcount: int
    revenue_cents: int
    status: str
    resource_count: int
    tracked_run_rate_cents: int
    direct_spend_cents: int
    showback_total_cents: int
    chargeback_balance_cents: int


class TaggingPolicy(CommonFields, total=False):
    name: str
    mandatory_dimensions: List[str]
    enforcement_mode: str
    status: str
    created_by_user_id: str
    activated_by_user_id: Optional[str]
    rejection_count: int


class ProvisioningRequest(CommonFields, total=False):
    tagging_policy_id: str
    business_unit_id: str
    resource_kind: str
    requested_tags: Dict[str, str]
    monthly_run_rate_cents: int
    owner_user_id: str
    status: str
    missing_dimensions: List[str]
    compliance_score: float
    projected_tag_state: str
    retag_count: int


class CloudResource(CommonFields, total=False):
    provisioning_request_id: str
    business_unit_id: str
    resource_kind: str
    applied_tags: Dict[str, str]
    tag_state: str
    environment: str
    owner_user_id: str
    monthly_run_rate_cents: int
    utilization_pct: float
    lifecycle_state: str


class CostRecord(CommonFields, total=False):
    cloud_resource_id: Optional[str]
    business_unit_id: Optional[str]
    billing_period_start: str
    billing_period_end: str
    resource_kind: str
    list_cost_cents: int
    effective_cost_cents: int
    allocation_state: str
    applied_commitment_id: Optional[str]
    shared_cost_pool_id: Optional[str]
    allocated_by_run_id: Optional[str]


class AllocationRun(CommonFields, total=False):
    mode: str
    period_start: str
    period_end: str
    scope_business_unit_id: Optional[str]
    status: str
    variant_applied: Optional[str]
    total_allocated_cents: int
    scoped_list_cost_cents: int
    scoped_effective_cost_cents: int
    line_count: int
    reopen_count: int
    created_by_user_id: str
    published_by_user_id: Optional[str]


class SharedCostPool(CommonFields, total=False):
    allocation_run_id: str
    name: str
    methodology: str
    proportional_basis: str
    participant_business_unit_ids: List[str]
    status: str
    pooled_cost_cents: int
    absorbed_record_count: int


class AllocationLine(TypedDict, total=False):
    """PRD §2.4's one `common_fields: false` entity.

    Only `id` and `created_at` are present — asserting on `version` or
    `updated_at` here would be asserting on a field the PRD says does not
    exist.
    """

    id: str
    created_at: str
    allocation_run_id: str
    business_unit_id: str
    shared_cost_pool_id: Optional[str]
    cost_record_id: Optional[str]
    line_kind: str
    method_applied: str
    allocated_cents: int
    basis_value: float
    rounding_remainder_cents: int
    memo: Optional[str]


class ChargebackInvoice(CommonFields, total=False):
    allocation_run_id: str
    business_unit_id: str
    settlement_status: str
    dispute_status: str
    gross_amount_cents: int
    credited_amount_cents: int
    paid_amount_cents: int
    net_due_cents: int
    issued_at: Optional[str]
    dispute_window_ends_at: Optional[str]


class Dispute(CommonFields, total=False):
    chargeback_invoice_id: str
    filed_by_business_unit_id: str
    filed_by_user_id: str
    reason_code: str
    claimed_credit_cents: int
    granted_credit_cents: int
    narrative: str
    status: str
    outcome: Optional[str]
    review_round: int
    resolved_by_user_id: Optional[str]
    disputed_cost_record_ids: List[str]


class Commitment(CommonFields, total=False):
    commitment_type: str
    region: str
    covered_resource_kind: Optional[str]
    term_start: str
    term_end: str
    hourly_commit_cents: int
    committed_capacity_cents: Optional[int]
    coverage_target_pct: float
    utilization_target_pct: float
    status: str
    covered_spend_cents: int
    total_discount_cents: int
    waste_cents: int
    coverage_pct: float
    utilization_pct: float


class RemediationTask(CommonFields, total=False):
    cloud_resource_id: str
    kind: str
    status: str
    observed_utilization_pct: float
    projected_savings_cents: int
    realized_savings_cents: int
    waste_score: float
    auto_remediation_eligible: bool
    snooze_count: int
    remediation_window_starts_at: Optional[str]
    remediation_window_ends_at: Optional[str]


class AnomalyAlert(CommonFields, total=False):
    business_unit_id: str
    baseline_cents: int
    observed_cents: int
    delta_cents: int
    spike_ratio: float
    severity_score: float
    severity: str
    routed_queue: Optional[str]
    status: str
    detected_at: str
    root_cause_cloud_resource_id: Optional[str]
    root_cause_kind: Optional[str]
    acknowledged_by_user_id: Optional[str]


class Budget(CommonFields, total=False):
    business_unit_id: str
    period_start: str
    period_end: str
    amount_cents: int
    forecast_cents: int
    accuracy_basis: str
    accuracy_basis_applied: Optional[str]
    forecast_history: List[int]
    revision_count: int
    status: str
    actual_spend_cents: int
    variance_cents: int
    variance_pct: float
    warning_flag: bool
    forecast_accuracy_pct: float
    variance_explanation_text: Optional[str]


class UnitEconomicsDriver(CommonFields, total=False):
    business_unit_id: str
    allocation_run_id: str
    driver_name: str
    driver_volume: int
    base_allocated_cents: int
    provisional_cost_per_unit_cents: float
    efficiency_tier: Optional[str]
    platform_overhead_cents: int
    final_cost_per_unit_cents: float


#: Entities whose responses must carry the four PRD §2.4 common fields.
COMMON_FIELD_ENTITIES = (
    "BusinessUnit",
    "TaggingPolicy",
    "ProvisioningRequest",
    "CloudResource",
    "CostRecord",
    "AllocationRun",
    "SharedCostPool",
    "ChargebackInvoice",
    "Dispute",
    "Commitment",
    "RemediationTask",
    "AnomalyAlert",
    "Budget",
    "UnitEconomicsDriver",
)

#: The single entity PRD §2.4 exempts from `updated_at` and `version`.
NO_COMMON_FIELD_ENTITIES = ("AllocationLine",)

JsonDict = Dict[str, Any]
