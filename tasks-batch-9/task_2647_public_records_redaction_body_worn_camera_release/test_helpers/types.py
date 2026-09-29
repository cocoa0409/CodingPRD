"""TypedDict shapes for the persisted resources of the records API.

These describe what the API returns, so tests can index fields with editor and
type-checker support. Every resource carries `id` and `created_at`; every
resource except the append-only ledger entry additionally carries `updated_at`
and `version`.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(CommonFields):
    full_name: str
    role_type: str
    redaction_certification_level: int
    open_qa_assignment_count: int


class Requester(CommonFields):
    full_name: str
    email: str
    requester_type: str
    indigency_certified: bool
    fee_waiver_pct: float
    open_request_count: int


class VideoAsset(CommonFields):
    incident_number: str
    device_serial: str
    officer_badge: str
    recorded_start_at: str
    duration_ms: int
    classification: str
    retention_category: str
    scheduled_purge_at: str
    is_critical_incident: bool
    disposition_state: str
    retention_locked: bool
    suspended_by_hold_id: Optional[str]
    depicted_individual_count: int


class DepictedIndividual(CommonFields):
    video_asset_id: str
    display_label: str
    relationship: str
    notification_required: bool
    notification_status: str
    notice_method: Optional[str]
    notified_at: Optional[str]
    objection_deadline_at: Optional[str]
    objection_basis: Optional[str]


class PublicRecordsRequest(CommonFields):
    requester_id: str
    received_at: str
    subject_incident_number: str
    requested_date_from: str
    requested_date_to: str
    scope_narrative: str
    extension_days_granted: int
    scope_clarification_count: int
    processing_status: str
    fee_status: str
    is_critical_incident: bool
    tolled_days: int
    statutory_deadline_at: str
    responsive_record_count: int
    unadjudicated_claim_count: int
    open_notification_count: int
    billable_labor_minutes: int
    estimated_total_cents: int
    deposit_required_cents: int
    deposit_due_at: Optional[str]
    deposit_paid_cents: int
    deposit_balance_cents: int
    fee_recognized_cents: int
    waiver_credit_total_cents: int
    invoiced_total_cents: int


class ResponsiveRecord(CommonFields):
    request_id: str
    video_asset_id: str
    inclusion_status: str
    release_posture: str
    estimated_review_minutes: int
    presumptive_burden_minutes: int
    adjudicated_burden_minutes: int
    approved_labor_minutes: int
    unadjudicated_claim_count: int
    redacted_segment_ms: int
    released_at: Optional[str]


class ExemptionClaim(CommonFields):
    responsive_record_id: str
    exemption_code: str
    statutory_citation: str
    asserted_scope: str
    status: str
    claim_source: str
    asserted_by_staff_id: Optional[str]
    depicted_individual_id: Optional[str]
    estimated_redaction_minutes: int
    adjudicated_by_staff_id: Optional[str]
    adjudicated_at: Optional[str]
    adjudication_note: Optional[str]


class RedactionTask(CommonFields):
    responsive_record_id: str
    exemption_claim_id: Optional[str]
    target_type: str
    clip_start_ms: int
    clip_end_ms: int
    assigned_technician_id: str
    status: str
    rework_count: int
    logged_labor_minutes: int
    approved_labor_minutes: int
    defect_codes: List[str]
    qa_reviewer_id: Optional[str]
    qa_window_start_at: Optional[str]
    qa_window_end_at: Optional[str]


class FeeEstimate(CommonFields):
    request_id: str
    basis: str
    media_type: str
    status: str
    sequence_number: int
    projected_review_minutes: int
    projected_burden_minutes: int
    billable_minutes: int
    estimated_labor_cents: int
    produced_minutes: int
    disc_count: int
    media_production_cents: int
    subtotal_cents: int
    effective_waiver_pct: float
    waiver_credit_cents: int
    estimated_total_cents: int
    deposit_required_cents: int


class FeeLedgerEntry(TypedDict):
    """The append-only ledger line: `id` and `created_at` only, no version."""

    id: str
    created_at: str
    request_id: str
    entry_type: str
    amount_cents: int
    memo: Optional[str]
    source_kind: str
    reverses_entry_id: Optional[str]


class ReleasePackage(CommonFields):
    request_id: str
    media_type: str
    package_kind: str
    included_record_count: int
    waived_notification_count: int
    produced_minutes: int
    disc_count: int
    production_cost_cents: int
    released_at: str


class DenialLetter(CommonFields):
    request_id: str
    denial_type: str
    status: str
    appeal_pathway_note: str
    appeal_authority: str
    statutory_citations: List[str]
    withheld_record_count: int
    issued_at: str
    appeal_deadline_at: str
    appeal_grounds: Optional[str]
    appeal_filed_at: Optional[str]
    appeal_decided_at: Optional[str]


class LitigationHold(CommonFields):
    matter_number: str
    scope_incident_number: str
    hold_type: str
    status: str
    placed_at: str
    released_at: Optional[str]
    release_note: Optional[str]
    suspended_asset_count: int


Envelope = Dict[str, Any]
