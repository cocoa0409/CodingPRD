"""
Typed shapes for every resource the API returns.

Every resource in this service carries the same four common fields — ``id``,
``created_at``, ``updated_at`` and ``version`` — with no exceptions, so they are
factored into a shared base and inherited by all fourteen resource shapes.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four fields every resource in this service carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Platform(CommonFields, total=False):
    name: str
    platform_type: str
    form_code: str
    status: str
    review_window_days: int
    refund_policy: str
    supports_online_tool: bool
    supports_transfer: bool
    supports_memorialization: bool
    supports_deletion: bool
    requires_court_order_for_content: bool
    license_terminates_at_death: bool
    transfer_fee_cents: int
    request_fee_cents: int


class Estate(CommonFields, total=False):
    decedent_name: str
    date_of_death: str
    domicile_state: str
    court_case_number: str
    administration_phase: str
    alternate_valuation_date: str
    valuation_basis: Optional[str]
    inventory_total_count: int
    disclosed_asset_count: int
    assets_pending_disposition_count: int
    assets_disposed_count: int
    open_cancellation_count: int
    cancelled_subscription_count: int
    gross_digital_estate_cents: int
    admin_deduction_cents: int
    taxable_digital_estate_cents: int
    undistributed_value_cents: int
    refund_recovered_cents: int
    closing_statement: Optional[str]
    closed_at: Optional[str]


class Fiduciary(CommonFields, total=False):
    estate_id: str
    full_name: str
    appointment_type: str
    court_reference: str
    letters_status: str


class Document(CommonFields, total=False):
    estate_id: str
    fiduciary_id: Optional[str]
    doc_type: str
    reference_number: str
    issued_on: str
    jurisdiction: str
    verification_status: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    revocation_reason: Optional[str]


class AuthorityDirective(CommonFields, total=False):
    estate_id: str
    directive_type: str
    scope: str
    platform_id: Optional[str]
    asset_category: Optional[str]
    instrument_reference: str
    executed_on: str
    precedence_rank: int
    status: str


class DigitalAsset(CommonFields, total=False):
    estate_id: str
    platform_id: str
    category: str
    account_handle: str
    quoted_value_cents: int
    loyalty_points: int
    inventory_note: Optional[str]
    transferability: str
    transferability_reason: str
    access_status: str
    disposition_status: str
    subscription_billing_state: str
    content_clamp_reason: str
    appraised_value_cents: Optional[int]
    appraised_basis: Optional[str]
    disclosed_at: Optional[str]
    disposed_at: Optional[str]


class SubscriptionTerm(CommonFields, total=False):
    asset_id: str
    term_start_date: str
    term_end_date: str
    billing_interval: str
    period_fee_cents: int
    auto_renew: bool
    term_days: int
    claimed_days_total: int
    state: str
    cancelled_effective_date: Optional[str]


class PlatformRequest(CommonFields, total=False):
    estate_id: str
    platform_id: str
    request_type: str
    requested_scope: str
    death_certificate_document_id: str
    letters_document_id: str
    platform_form_code: str
    status: str
    review_window_start: Optional[str]
    review_window_end: Optional[str]
    info_cycle_count: int
    decision: Optional[str]
    decision_note: Optional[str]
    missing_items: Optional[str]
    remediation_note: Optional[str]
    withdrawal_reason: Optional[str]
    resolved_scope: Optional[str]
    resolved_basis: Optional[str]
    clamp_reason: str
    request_fee_cents: int


class AuthorityGrant(CommonFields, total=False):
    estate_id: str
    platform_id: str
    platform_request_id: str
    granted_scope: str
    basis: str
    status: str
    effective_from: str
    expires_at: str
    clamp_reason: str
    revocation_reason: Optional[str]
    revoked_at: Optional[str]


class BeneficiaryDesignation(CommonFields, total=False):
    estate_id: str
    beneficiary_name: str
    share_bp: int
    source: str
    relationship: Optional[str]
    allocation_rank: int
    planned_allocation_cents: int
    received_value_cents: int


class DispositionElection(CommonFields, total=False):
    asset_id: str
    election: str
    beneficiary_designation_id: Optional[str]
    election_note: Optional[str]
    status: str
    elected_by_fiduciary_id: str
    countersigned_by_fiduciary_id: Optional[str]
    attestation: Optional[str]
    platform_confirmation_reference: Optional[str]
    distributed_value_cents: int
    executed_at: Optional[str]
    rejection_reason: Optional[str]
    reversal_reason: Optional[str]


class CancellationOrder(CommonFields, total=False):
    asset_id: str
    subscription_term_id: Optional[str]
    status: str
    refund_policy_snapshot: str
    effective_date: Optional[str]
    platform_reference: Optional[str]
    auto_renew_stopped: bool
    confirmed_at: Optional[str]
    failure_reason: Optional[str]


class RefundClaim(CommonFields, total=False):
    cancellation_order_id: str
    claimed_period_start: str
    claimed_period_end: str
    claimed_days: int
    claimed_cents: int
    method: str
    status: str
    credited_cents: int
    pursuit_cost_cents: int
    escalation_reason: Optional[str]
    denial_reason: Optional[str]
    charge_back_reason: Optional[str]


class ValuationRun(CommonFields, total=False):
    estate_id: str
    basis: str
    status: str
    valuation_date: str
    included_asset_count: int
    gross_value_cents: int
    deduction_cap_cents: int
    admin_deduction_cents: int
    taxable_value_cents: int
    allocation_remainder_cents: int
    finalization_note: Optional[str]
    finalized_at: Optional[str]


class AuthorityResolution(TypedDict, total=False):
    """Projection returned by the authority-resolution read."""

    estate_id: str
    platform_id: str
    asset_category: Optional[str]
    resolved_scope: str
    resolved_basis: str
    clamp_reason: str
    controlling_directive_id: Optional[str]


class GrantExpirySweep(TypedDict, total=False):
    """Report returned by the grant-expiry sweep."""

    swept_at: str
    expired_grant_count: int
    revoked_asset_count: int
    lapsed_term_count: int


class ClockReading(TypedDict, total=False):
    current_utc: str


class PaginationMeta(TypedDict, total=False):
    limit: int
    offset: int
    total_count: int
    has_more: bool


__all__: List[str] = [
    "CommonFields",
    "Platform",
    "Estate",
    "Fiduciary",
    "Document",
    "AuthorityDirective",
    "DigitalAsset",
    "SubscriptionTerm",
    "PlatformRequest",
    "AuthorityGrant",
    "BeneficiaryDesignation",
    "DispositionElection",
    "CancellationOrder",
    "RefundClaim",
    "ValuationRun",
    "AuthorityResolution",
    "GrantExpirySweep",
    "ClockReading",
    "PaginationMeta",
]
