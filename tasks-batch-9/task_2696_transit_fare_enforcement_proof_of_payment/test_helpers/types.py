"""
Typed shapes for every persisted record and every report payload.

Eleven record kinds carry the full identity set — ``id``, ``created_at``,
``updated_at`` and ``version``.  Three record kinds are immutable once
written and therefore carry only ``id`` and ``created_at``: their shapes below
deliberately omit ``updated_at`` and ``version`` entirely, because both fields
are absent from their representations.

Ratios exposed as decimals are carried to exactly four decimal places; the
alias ``RateValue`` covers both the string and the numeric rendering of such a
figure so that assertions can normalise before comparing.
"""

from typing import Any, Dict, List, Optional, Union

try:  # Python 3.8+
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore

RateValue = Union[str, float, int]
Envelope = Dict[str, Any]


# ── Mutable records: id + created_at + updated_at + version ───────────

class FareZone(TypedDict, total=False):
    id: str
    zone_code: str
    name: str
    required_sign_count: int
    penalty_multiplier_bps: int
    enforcement_policy: str
    max_concurrent_deployments: int
    designation_status: str
    verified_sign_count: int
    signage_compliance_pct: RateValue
    designated_at: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransitLine(TypedDict, total=False):
    id: str
    line_code: str
    mode: str
    daily_boardings: int
    baseline_evasion_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    badge_number: str
    display_name: str
    certification_expiry: str
    status: str
    citations_issued_count: int
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict, total=False):
    id: str
    rider_ref: str
    display_name: str
    demographic_band: str
    residence_geo_tract: str
    fare_assistance_enrolled: bool
    prior_warning_count: int
    prior_citation_count: int
    created_at: str
    updated_at: str
    version: int


class InspectionDeployment(TypedDict, total=False):
    id: str
    line_id: str
    zone_id: str
    window_start: str
    window_end: str
    planned_inspector_count: int
    sampling_method: str
    target_sample_size: int
    status: str
    achieved_sample_count: int
    voided_encounter_count: int
    sample_adequacy_ratio: RateValue
    measured_evasion_rate_bps: Optional[int]
    resolved_evasion_rate_bps: Optional[int]
    enforcement_cost_cents: Optional[int]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionEncounter(TypedDict, total=False):
    id: str
    deployment_id: str
    inspector_id: str
    rider_id: Optional[str]
    occurred_at: str
    fare_media_type: str
    media_reference: Optional[str]
    media_validated_at: Optional[str]
    media_expires_at: Optional[str]
    media_zone_code: Optional[str]
    identity_capture_method: str
    validation_result: str
    outcome: str
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict, total=False):
    id: str
    encounter_id: str
    rider_id: str
    zone_id: str
    issuing_inspector_id: str
    issued_at: str
    contest_deadline_at: str
    offense_sequence: int
    citation_only_sequence: int
    assessed_penalty_cents: int
    admin_fee_cents: int
    total_due_cents: int
    reduction_floor_cents: int
    amount_paid_cents: int
    service_credit_cents: int
    outstanding_balance_cents: int
    adjudication_status: str
    settlement_status: str
    dismissal_reason_code: Optional[str]
    dismissed_at: Optional[str]
    reissued_from_citation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdjudicationHearing(TypedDict, total=False):
    id: str
    citation_id: str
    requested_by_rider_id: str
    scheduled_for: str
    status: str
    decision: str
    reduced_penalty_cents: Optional[int]
    dismissal_reason_code: Optional[str]
    hearing_officer_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    citation_id: str
    hearing_id: str
    appellant_rider_id: str
    grounds_code: str
    statement: str
    status: str
    round_index: int
    submitted_at: str
    supplement_deadline_at: Optional[str]
    decision: Optional[str]
    dismissal_reason_code: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict, total=False):
    id: str
    citation_id: str
    installment_count: int
    down_payment_cents: int
    financed_cents: int
    base_installment_cents: int
    final_installment_cents: int
    first_due_at: str
    status: str
    installments_paid_count: int
    missed_installment_count: int
    remaining_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class CommunityServiceAssignment(TypedDict, total=False):
    id: str
    citation_id: str
    partner_org_name: str
    required_hours: int
    hours_completed: int
    credited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ── Immutable records: id + created_at only ──────────────────────────
# These three shapes carry no ``updated_at`` and no ``version`` because both
# fields are absent from their representations entirely.

class ZoneLineAssignment(TypedDict, total=False):
    id: str
    zone_id: str
    line_id: str
    platform_segment_count: int
    effective_from: str
    created_at: str


class SignageAudit(TypedDict, total=False):
    id: str
    zone_id: str
    audited_at: str
    signs_verified_count: int
    deficiency_note: Optional[str]
    auditor_user_id: str
    created_at: str


class PenaltyPayment(TypedDict, total=False):
    id: str
    citation_id: str
    plan_id: Optional[str]
    amount_cents: int
    source: str
    hours_credited: int
    applied_at: str
    created_at: str


# Record kinds whose representations omit ``updated_at`` and ``version``.
IMMUTABLE_RECORD_KINDS = ("ZoneLineAssignment", "SignageAudit", "PenaltyPayment")


# ── Report payloads ──────────────────────────────────────────────────

class EquityGroup(TypedDict, total=False):
    group_key: str
    encounter_pool_count: int
    citation_count: int
    citation_rate: RateValue
    rate_delta: RateValue


class EquityDistributionReport(TypedDict, total=False):
    window_start: str
    window_end: str
    group_by: str
    encounter_pool_count: int
    citation_count: int
    systemwide_citation_rate: RateValue
    groups_evaluated: int
    disparity_index: RateValue
    groups: List[EquityGroup]


class RevenueRecoveryReport(TypedDict, total=False):
    window_start: str
    window_end: str
    basis: str
    recovered_cents: int
    enforcement_cost_cents: int
    net_recovery_cents: int
    recovery_ratio_bps: int
    citations_counted: int
    deployments_counted: int


class ClockState(TypedDict, total=False):
    current_utc: str
