"""TypedDict shapes for every resource the API persists.

Per PRD §2.4 every persisted resource carries `id` and `created_at`; most also
carry `updated_at` and `version`. Two entities are deliberately thinner: a
fingerprint match and a royalty ledger entry carry only `id` and `created_at`,
with no `updated_at` and no `version` — those two shapes therefore omit both
fields and tests must not look for them.
"""

from typing import Any, Dict, List, Optional, TypedDict


class Composer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    display_name: str
    pro_affiliation: str
    payee_country: str
    tax_withholding_pct: float
    accrued_unpaid_cents: int
    outstanding_advance_cents: int
    lifetime_paid_cents: int
    latest_statement_period_end: Optional[str]


class ComposerAgreement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    composer_id: str
    agreement_type: str
    status: str
    writer_share_pct: float
    publisher_share_pct: float
    sync_fee_share_pct: float
    buyout_fee_cents: int
    exclusivity: str
    holdback_days: int
    advance_cents: int
    blanket_opt_in: bool
    amendment_round: int
    pending_writer_share_pct: Optional[float]
    pending_publisher_share_pct: Optional[float]
    pending_sync_fee_share_pct: Optional[float]
    pending_holdback_days: Optional[int]
    signature_name: Optional[str]
    signed_at: Optional[str]
    terminated_at: Optional[str]
    termination_reason: Optional[str]


class Composition(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    composer_id: str
    agreement_id: str
    title: str
    duration_sec: int
    tempo_bpm: int
    genre: str
    mood_tags: List[str]
    instrumentation: List[str]
    catalog_status: str
    availability_status: str
    active_license_count: int
    exclusive_block_until: Optional[str]
    open_claim_count: int
    lifetime_performance_credits: float
    relevance_score: Optional[float]
    retire_reason: Optional[str]


class CatalogSearchProfile(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    weight_mood: int
    weight_genre: int
    weight_instrumentation: int
    weight_tempo: int
    tempo_tolerance_bpm: int
    restricted_availability_factor: float


class LicenseTier(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    code: str
    media_type: str
    allowed_scales: List[str]
    base_rate_cents: int
    min_term_months: int
    max_term_months: int
    per_use_eligible: bool
    blanket_eligible: bool


class Licensee(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    licensee_type: str
    credit_limit_cents: int
    committed_spend_cents: int
    reserved_spend_cents: int
    credit_available_cents: int


class SyncRequest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    composition_id: str
    licensee_id: str
    tier_id: str
    license_id: Optional[str]
    status: str
    media_type: str
    distribution_scale: str
    requested_term_start: str
    requested_term_months: int
    exclusive_requested: bool
    custom_edit_requested: bool
    stems_requested: bool
    alternate_lengths_sec: List[int]
    rush_requested: bool
    brief_note: Optional[str]
    revision_round: int
    revision_note: Optional[str]
    quoted_fee_cents: Optional[int]
    quoted_spend_basis_cents: Optional[int]
    quoted_discount_pct: Optional[float]
    quote_expires_at: Optional[str]
    decline_reason: Optional[str]
    edit_note: Optional[str]
    delivered_asset_count: Optional[int]
    delivery_note: Optional[str]


class License(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    license_mode: str
    status: str
    composition_id: str
    licensee_id: str
    tier_id: str
    sync_request_id: Optional[str]
    blanket_agreement_id: Optional[str]
    media_type: str
    distribution_scale: str
    term_start: str
    term_months: int
    term_end: str
    is_exclusive: bool
    exclusive_block_until: Optional[str]
    final_fee_cents: int
    final_spend_basis_cents: int
    final_discount_pct: float
    composer_sync_share_cents: int
    collected_amount_cents: int
    collected_at: Optional[str]
    revoke_reason: Optional[str]


class BlanketAgreement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    licensee_id: str
    coverage_start: str
    coverage_end: str
    annual_fee_cents: int
    reporting_cadence: str
    usage_cap_minutes: int
    pool_share_pct: float
    coverage_status: str
    reporting_status: str
    delinquent_since: Optional[str]
    reported_minutes_ytd: int
    overage_minutes: int
    overage_cents: int
    pool_distributed_cents: int
    pool_admin_fee_cents: int
    termination_reason: Optional[str]


class PoolAllocation(TypedDict, total=False):
    composition_id: str
    credits: float
    allocation_cents: int


class UsageReport(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    blanket_agreement_id: str
    period_start: str
    period_end: str
    status: str
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    rejection_reason: Optional[str]
    resubmission_count: int
    reported_minutes_total: int
    reported_credits_total: float
    pool_cents: int
    pool_admin_fee_cents: int
    pool_distributable_cents: int
    pool_allocations: List[PoolAllocation]


class CueEntry(TypedDict, total=False):
    composition_id: str
    usage_type: str
    duration_sec: int


class CueCreditLine(TypedDict, total=False):
    composition_id: str
    usage_type: str
    duration_sec: int
    credits: float


class CueSheet(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    license_id: Optional[str]
    usage_report_id: Optional[str]
    production_title: str
    broadcast_date: str
    market_tier: str
    cues: List[CueEntry]
    cue_credit_breakdown: List[CueCreditLine]
    credits_by_composition: Dict[str, float]
    total_credits: float
    total_seconds: int
    status: str
    society_reference: Optional[str]
    registered_at: Optional[str]
    registration_round: int
    rejection_reason: Optional[str]
    collected_at: Optional[str]


class FingerprintMatch(TypedDict, total=False):
    """Append-only detection event: only `id` and `created_at` per PRD §2.4."""

    id: str
    created_at: str
    composition_id: str
    source_platform: str
    source_reference: str
    matched_seconds: int
    confidence_pct: float
    detected_at: str


class InfringementClaim(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    fingerprint_match_id: str
    composition_id: str
    status: str
    statutory_amount_cents: int
    settlement_floor_cents: int
    settlement_amount_cents: Optional[int]
    settlement_basis: Optional[str]
    settlement_collected: Optional[bool]
    composer_share_cents: Optional[int]
    notice_channel: Optional[str]
    noticed_at: Optional[str]
    dispute_note: Optional[str]
    escalation_note: Optional[str]
    settled_at: Optional[str]
    detected_at: str


class RoyaltyStatement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    composer_id: str
    period_start: str
    period_end: str
    basis: str
    status: str
    gross_cents: int
    line_count: int
    recouped_cents: int
    withholding_cents: int
    net_payable_cents: int
    payout_status: str
    finalized_by_user_id: Optional[str]
    finalized_at: Optional[str]
    paid_by_user_id: Optional[str]
    paid_at: Optional[str]
    payment_reference: Optional[str]


class RoyaltyLedgerEntry(TypedDict, total=False):
    """Immutable accounting record: only `id` and `created_at` per PRD §2.4."""

    id: str
    created_at: str
    composer_id: str
    source_type: str
    amount_cents: int
    memo: Optional[str]
    source_ref_id: Optional[str]
    accrual_recognized_at: Optional[str]
    cash_recognized_at: Optional[str]
    statement_id: Optional[str]


class RoyaltyPreview(TypedDict, total=False):
    basis: str
    accrual_gross_cents: int
    cash_gross_cents: int
    gross_cents: int
    included_entry_count: int
    outstanding_advance_cents: int
    projected_recoup_cents: int
    projected_withholding_cents: int
    projected_net_cents: int
    projected_payout_status: str


class ClockSweep(TypedDict, total=False):
    current_utc: str
    expired_license_ids: List[str]
    expired_blanket_agreement_ids: List[str]
    delinquent_blanket_agreement_ids: List[str]


# Entities that carry the full common-field set (id, created_at, updated_at,
# version) versus the two thin append-only records.
VERSIONED_ENTITIES = [
    "Composer",
    "ComposerAgreement",
    "Composition",
    "CatalogSearchProfile",
    "LicenseTier",
    "Licensee",
    "SyncRequest",
    "License",
    "BlanketAgreement",
    "UsageReport",
    "CueSheet",
    "InfringementClaim",
    "RoyaltyStatement",
]
THIN_ENTITIES = ["FingerprintMatch", "RoyaltyLedgerEntry"]

JsonDict = Dict[str, Any]
