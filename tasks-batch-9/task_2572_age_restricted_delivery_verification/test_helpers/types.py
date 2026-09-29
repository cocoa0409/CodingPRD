"""TypedDict shapes for every resource the API returns.

Field names are exactly the names the PRD uses. Per PRD 2.4 almost every
resource carries `id`, `created_at`, `updated_at` and `version`;
`CaptureArtifact` is the deliberate exception and carries only `id` and
`created_at`, so its shape below omits `updated_at` and `version` entirely.
"""

from typing import Any, Dict, List, Optional, TypedDict


class Jurisdiction(TypedDict):
    id: str
    code: str
    name: str
    dry_status: str
    utc_offset_minutes: int
    active_policy_count: int
    created_at: str
    updated_at: str
    version: int


class RestrictionPolicy(TypedDict):
    id: str
    jurisdiction_id: str
    restriction_type: str
    permissibility: str
    min_age_years: int
    delivery_window_start_minute: int
    delivery_window_end_minute: int
    unit_scale_factor: float
    max_units_per_order: float
    max_units_per_window: float
    rolling_window_days: int
    acceptable_document_types: List[str]
    requires_scan: bool
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    restriction_type: str
    restricted_units_per_item: float
    list_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    jurisdiction_id: str
    attestation_state: str
    attested_dob: Optional[str]
    attestation_at: Optional[str]
    attestation_channel: Optional[str]
    latest_identity_check_result: str
    refusal_strikes: int
    blocked_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IdentityCheck(TypedDict):
    id: str
    customer_id: str
    provider: str
    provided_dob: str
    source_dob: str
    validity_days: int
    source_signals: List[Dict[str, Any]]
    confidence: float
    result: str
    verified_dob: Optional[str]
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    delivery_jurisdiction_id: str
    delivery_partner_id: str
    scheduled_delivery_at: str
    delivery_fee_cents: int
    compliance_state: str
    fulfillment_state: str
    restriction_types: List[str]
    applied_policy_ids: List[str]
    item_subtotal_cents: int
    charged_cents: int
    provisional_restricted_units: float
    final_restricted_units: Optional[float]
    restocking_fee_cents: int
    refunded_cents: int
    retained_cents: int
    submitted_at: Optional[str]
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    hold_reason: Optional[str]
    clearance_actor_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    units_per_item_snapshot: float
    line_total_cents: int
    line_restricted_units: float
    line_state: str
    created_at: str
    updated_at: str
    version: int


class PerTypeExposure(TypedDict):
    restriction_type: str
    provisional_restricted_units: float


class ComplianceEvaluation(TypedDict):
    order_id: str
    restriction_types: List[str]
    applied_policy_ids: List[str]
    provisional_restricted_units: float
    per_type_exposure: List[Dict[str, Any]]
    window_units_consumed: float
    local_delivery_minute: int
    in_delivery_window: bool
    purchaser_age_years: Optional[int]
    min_age_required: Optional[int]
    identity_result: Optional[str]
    would_route_to: str
    first_blocking_error_id: Optional[str]


class DeliveryPartner(TypedDict):
    id: str
    legal_name: str
    contract_tier: str
    license_reference: str
    license_risk_score: float
    lifetime_risk_score: float
    open_case_count: int
    open_critical_case_count: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class CaseBreakdownEntry(TypedDict):
    violation_case_id: str
    assessed_severity: str
    decided_at: str
    age_days: int
    included_in_rolling: bool
    rolling_points: float
    lifetime_weight: float
    lifetime_points: float


class RiskAssessment(TypedDict):
    delivery_partner_id: str
    evaluated_at: str
    contract_tier: str
    tier_multiplier: float
    rolling_90d_score: float
    lifetime_weighted_score: float
    open_case_count: int
    open_critical_case_count: int
    posture: str
    case_breakdown: List[Dict[str, Any]]


class Courier(TypedDict):
    id: str
    delivery_partner_id: str
    full_name: str
    hired_at: str
    compliance_score: float
    compliant_handover_count: int
    certification_state: str
    dispatch_eligible: bool
    created_at: str
    updated_at: str
    version: int


class CourierCertification(TypedDict):
    id: str
    courier_id: str
    restriction_type: str
    training_score: int
    training_completed_at: str
    valid_days: int
    issued_at: str
    expires_at: str
    state: str
    renewal_count: int
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryAttempt(TypedDict):
    id: str
    order_id: str
    courier_id: str
    started_at: str
    state: str
    document_type: Optional[str]
    document_expires_on: Optional[str]
    scan_performed: Optional[bool]
    scanned_dob: Optional[str]
    recipient_name: Optional[str]
    recipient_age_years: Optional[int]
    id_check_compliant: bool
    observed_indicators: List[str]
    refusal_reason: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaptureArtifact(TypedDict):
    """PRD 2.4: a capture carries only `id` and `created_at` — it is versionless."""

    id: str
    delivery_attempt_id: str
    kind: str
    content_hash: str
    captured_at: str
    retention_until: str
    created_at: str


class SecretShopperTest(TypedDict):
    id: str
    courier_id: str
    order_id: str
    scenario_type: str
    scheduled_at: str
    expected_outcome: str
    observed_outcome: Optional[str]
    verdict: str
    findings: Optional[str]
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ViolationCase(TypedDict):
    id: str
    delivery_partner_id: str
    delivery_attempt_id: Optional[str]
    secret_shopper_test_id: Optional[str]
    origin: str
    severity: Optional[str]
    assessed_severity: Optional[str]
    summary: Optional[str]
    state: str
    investigation_rounds: int
    risk_contribution: float
    decided_at: Optional[str]
    substantiated_by_user_id: Optional[str]
    response_due_at: Optional[str]
    partner_response_text: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict):
    id: str
    violation_case_id: str
    remediation_items: List[str]
    due_at: str
    state: str
    revision_round: int
    reviewed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    verification_outcome: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClockState(TypedDict):
    current_utc: str
    expired_identity_check_count: int
    expired_certification_count: int
    repostured_partner_count: int


class ReturnSettlementResult(TypedDict):
    """The order row as it reads after the settlement waterfall of PRD 3.7."""

    id: str
    fulfillment_state: str
    restocking_fee_cents: int
    refunded_cents: int
    retained_cents: int
    charged_cents: int
    item_subtotal_cents: int
    final_restricted_units: float
