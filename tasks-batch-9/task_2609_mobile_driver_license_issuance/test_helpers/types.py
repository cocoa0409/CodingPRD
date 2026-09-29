"""TypedDict shapes for every resource the API returns.

Three resources are append-only and therefore carry only `id` and
`created_at` from the common property set - proofing evidence items,
revocation ledger entries and pseudonymised presentation log entries.  Every
other resource additionally carries `updated_at` and `version`.
"""

from typing import List, Optional, TypedDict


class InteropProfile(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    profile_code: str
    standard_version: str
    accepted_issuer_states: List[str]
    required_assurance_level: str
    max_devices_per_holder: int
    max_active_credentials_per_holder: int
    proofing_validity_days: int
    revocation_freshness_seconds: int
    age_only_allowed_elements: List[str]
    pending_republish_count: int
    is_active: bool


class Holder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    date_of_birth: str
    address_line1: str
    city: str
    state_code: str
    postal_code: str
    physical_credential_number: str
    physical_credential_status: str
    physical_credential_expires_on: str
    restriction_codes: List[str]
    active_credential_count: int
    bound_device_count: int
    revoked_credential_count: int
    address_version: int


class IdentityProofingSession(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    holder_id: str
    requested_assurance_level: str
    state: str
    proofing_agent_user_id: str
    adjudicator_user_id: Optional[str]
    submission_count: int
    evidence_count: int
    adjudication_score: Optional[int]
    achieved_assurance_level: Optional[str]
    verified_at: Optional[str]
    assurance_expires_at: Optional[str]
    return_reason: Optional[str]


class ProofingEvidence(TypedDict):
    """Append-only: carries only id and created_at, no updated_at or version."""

    id: str
    created_at: str
    proofing_session_id: str
    evidence_type: str
    quality: str
    captured_at: str
    source_reference: str
    strength_points: int
    superseded: bool


class Device(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    holder_id: str
    platform: str
    model_name: str
    hardware_attestation_token: str
    protection_method: str
    state: str
    attestation_result: Optional[str]
    secure_element_grade: Optional[str]
    active_binding_count: int
    lost_reported_at: Optional[str]
    reprovision_count: int


class DigitalCredential(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    holder_id: str
    device_id: str
    proofing_session_id: str
    supersedes_credential_id: Optional[str]
    lifecycle_state: str
    sync_state: str
    doc_version: int
    valid_from: str
    valid_until: str
    assurance_level: Optional[str]
    restriction_codes: List[str]
    address_version_synced: int
    pending_update_count: int
    failed_delivery_count: int
    suspend_reason: Optional[str]
    revocation_sequence: int
    activated_at: Optional[str]
    protection_method_at_activation: Optional[str]
    reissuance_settlement_cents: int
    age_only_capable: bool


class UpdateOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    holder_id: str
    reason: str
    status: str
    payload_summary: Optional[str]
    delivery_count: int
    delivered_count: int
    failed_count: int
    target_address_version: int
    opened_at: str
    closed_at: Optional[str]


class UpdateDelivery(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    update_order_id: str
    credential_id: str
    status: str
    attempt_count: int
    failure_code: Optional[str]
    delivered_at: Optional[str]
    device_receipt_token: Optional[str]
    resulting_doc_version: Optional[int]


class RevocationEntry(TypedDict):
    """Append-only: carries only id and created_at, no updated_at or version."""

    id: str
    created_at: str
    credential_id: str
    sequence: int
    status: str
    reason: str
    effective_at: str
    published: bool


class Verifier(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    organization_name: str
    category: str
    purpose_scope: List[str]
    retention_ceiling_days: int
    trust_status: str
    exposure_index: int
    last_attestation_at: Optional[str]
    attested_max_retention_days: Optional[int]
    open_session_count: int
    billable_query_balance_cents: int
    credited_amount_cents: int
    probation_strike_count: int


class ReaderApp(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    verifier_id: str
    app_identifier: str
    certificate_serial: str
    cert_not_before: str
    cert_not_after: str
    requested_elements: List[str]
    base_rate_cents: int
    trust_state: str
    listed_at: Optional[str]
    query_count: int
    volume_discount_pct: float


class TrustListSnapshot(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    interop_profile_id: str
    snapshot_sequence: int
    effective_from: str
    effective_until: str
    listed_reader_app_count: int
    revocation_pointer_sequence: int
    revocation_pointer_stale: bool
    pending_delta_count: int
    standard_version: str
    published_at: str


class PresentationSession(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    credential_id: str
    reader_app_id: str
    context: str
    purpose: str
    requested_elements: List[str]
    handset_handling: str
    retention_days: int
    state: str
    minimized_elements: List[str]
    withheld_elements: List[str]
    disclosed_element_count: int
    excess_element_count: int
    billed_amount_cents: int
    billing_state: str
    consent_unlock_method: Optional[str]
    abort_reason: Optional[str]
    age_attestation_only: bool
    opened_at: str


class PresentationLogEntry(TypedDict):
    """Append-only: carries only id and created_at, no updated_at or version."""

    id: str
    created_at: str
    presentation_session_id: str
    verifier_id: str
    credential_pseudonym: str
    outcome: str
    disclosed_element_count: int
    excess_element_count: int
    retention_days_declared: int
    billed_amount_cents: int
    billing_state: str
    pseudonym_reuse_index: int
    recorded_at: str


# --------------------------------------------------------------------------
# Computed read models (projections, not stored resources)
# --------------------------------------------------------------------------
class AssurancePreview(TypedDict):
    preview_score: int
    preview_assurance_level: str
    adjudication_score: int
    adjudication_assurance_level: str
    submission_count: int
    evidence_type_count: int


class RevocationStatus(TypedDict):
    credential_id: str
    status: str
    entry_sequence: int
    effective_at: Optional[str]
    staleness_seconds: int
    is_fresh: bool


class ExposureIndexReport(TypedDict):
    rolling_window_index: int
    rolling_window_entry_count: int
    since_last_attestation_index: int
    since_attestation_entry_count: int
    computed_at: str


class InvoiceReport(TypedDict):
    invoice_amount_cents: int
    line_count: int
    surcharge_pct: float
    billable_query_balance_cents: int


class ClockReading(TypedDict):
    current_utc: str
