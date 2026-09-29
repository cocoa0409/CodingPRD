"""Typed shapes for every resource in the certificate authority API.

Modifiable resources carry the identity quartet `id`, `created_at`,
`updated_at` and `version` (PRD 2.4). The three append-only resources -
CT log submissions, CRL publications and root program communications -
carry only `id` and `created_at`, so they extend `AppendOnlyEntity`.
"""

from typing import Any, Dict, List, Optional, TypedDict


class AppendOnlyEntity(TypedDict):
    """Identity fields of an immutable, append-only resource."""

    id: str
    created_at: str


class ModifiableEntity(AppendOnlyEntity):
    """Identity fields of a resource that can be modified after creation."""

    updated_at: str
    version: int


class CertificateProfile(ModifiableEntity, total=False):
    name: str
    validation_type: str
    status: str
    status_service_posture: str
    max_validity_days: int
    dcv_reuse_days: int
    max_dcv_reuse_count: int
    org_vetting_reuse_days: int
    allowed_dcv_methods: List[str]
    required_sct_count: int
    required_vetting_level: str
    base_fee_cents: int
    crl_trigger_threshold: int
    max_crl_validity_hours: int
    pending_crl_entry_count: int
    revoked_certificate_count: int
    total_crl_entries_published: int
    last_crl_number: Optional[int]
    last_crl_this_update: Optional[str]
    last_crl_next_update: Optional[str]
    activated_at: Optional[str]
    retired_at: Optional[str]


class Subscriber(ModifiableEntity, total=False):
    legal_name: str
    jurisdiction_code: str
    registry_id: str
    contact_email: str
    callback_phone: str
    account_status: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    issued_certificate_count: int
    revocation_pending_count: int
    risk_score_operational: int
    risk_score_audit_final: Optional[float]
    suspended_at: Optional[str]


class OrganizationVetting(ModifiableEntity, total=False):
    subscriber_id: str
    required_level: str
    registry_check_status: str
    callback_check_status: str
    authority_check_status: str
    registry_checked_by_user_id: Optional[str]
    callback_checked_by_user_id: Optional[str]
    authority_checked_by_user_id: Optional[str]
    vetting_state: str
    approved_at: Optional[str]
    approved_by_user_id: Optional[str]
    rejected_at: Optional[str]


class DomainAuthorization(ModifiableEntity, total=False):
    subscriber_id: str
    profile_id: str
    domain_name: str
    method: str
    challenge_token: str
    state: str
    attempt_count: int
    validated_at: Optional[str]
    expires_at: Optional[str]
    reuse_count: int
    invalidated_at: Optional[str]
    invalidation_count: int


class CertificateRequest(ModifiableEntity, total=False):
    subscriber_id: str
    profile_id: str
    requested_domains: List[str]
    requested_validity_days: int
    expedited: bool
    csr_key_bits: int
    state: str
    return_count: int
    submitted_at: Optional[str]
    validation_cleared_by_user_id: Optional[str]
    validation_cleared_at: Optional[str]
    consumed_authorization_ids: List[str]
    projected_not_before: Optional[str]
    projected_not_after: Optional[str]
    projected_charge_cents: Optional[int]
    issued_certificate_id: Optional[str]
    rejected_reason: Optional[str]
    blocked_reason: Optional[str]


class Certificate(ModifiableEntity, total=False):
    serial_number: str
    request_id: str
    subscriber_id: str
    profile_id: str
    ceremony_id: str
    supersedes_certificate_id: Optional[str]
    lifecycle_status: str
    revocation_status: str
    not_before: str
    not_after: str
    validity_days_final: int
    dcv_methods_used: List[str]
    sct_count: int
    charged_amount_cents: int
    refunded_at: Optional[str]
    activated_at: Optional[str]
    revoked_at: Optional[str]
    revocation_reason_code: Optional[str]
    crl_number: Optional[int]
    crl_published_at: Optional[str]


class HsmPartition(ModifiableEntity, total=False):
    label: str
    serial: str
    state: str
    quarantined_at: Optional[str]
    attested_ceremony_count: int


class KeyCeremony(ModifiableEntity, total=False):
    partition_id: str
    window_start: str
    window_end: str
    attestation_valid_days: int
    state: str
    witness_user_ids: List[str]
    witness_count: int
    attested_at: Optional[str]
    attested_by_user_id: Optional[str]
    attestation_expires_at: Optional[str]
    attestation_revoked_at: Optional[str]
    issued_certificate_count: int


class CtLogSubmission(AppendOnlyEntity, total=False):
    certificate_id: str
    log_operator: str
    outcome: str
    rejection_reason: Optional[str]
    sct_timestamp: Optional[str]
    counted_toward_sct: bool


class RevocationRequest(ModifiableEntity, total=False):
    certificate_id: str
    incident_id: Optional[str]
    reason_code: str
    evidence_ref: Optional[str]
    state: str
    origin: str
    requested_by_user_id: str
    requested_at: str
    deadline_at: str
    deadline_breached: bool
    executed_at: Optional[str]
    denied_at: Optional[str]
    denial_reason: Optional[str]
    superseded_at: Optional[str]


class CrlPublication(AppendOnlyEntity, total=False):
    profile_id: str
    crl_number: int
    this_update: str
    next_update: str
    entry_count: int
    revoked_serials: List[str]
    published_by_user_id: str


class MisissuanceIncident(ModifiableEntity, total=False):
    title: str
    category: str
    subscriber_id: Optional[str]
    scope_profile_id: str
    scope_dcv_method: Optional[str]
    scope_issued_from: str
    scope_issued_to: str
    discovered_at: str
    disclosure_due_at: str
    disclosure_breached: bool
    disclosed_at: Optional[str]
    state: str
    revoked_certificate_count: int
    remaining_scope_count: int
    penalty_total_cents: int
    closed_at: Optional[str]


class RootProgramAudit(ModifiableEntity, total=False):
    root_program: str
    period_start: str
    period_end: str
    state: str
    finding_count: int
    critical_finding_count: int
    opinion_at: Optional[str]
    opined_by_user_id: Optional[str]
    assessed_subscriber_count: int
    retired_profile_count: int


class RootProgramCommunication(AppendOnlyEntity, total=False):
    incident_id: Optional[str]
    audit_id: Optional[str]
    root_program: str
    kind: str
    body: Optional[str]
    sent_at: str
    within_deadline: bool
    sent_by_user_id: str


# Envelope shapes (PRD 2.2 / 2.3).
class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    response_type: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorBody(TypedDict, total=False):
    error_id: str
    message: str
    details: Dict[str, Any]
