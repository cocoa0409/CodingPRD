"""TypedDict shapes for every stored resource and computed read.

Ordinary resources carry ``id``, ``created_at``, ``updated_at`` and
``version``. The two immutable streams — scorecard events and budget ledger
entries — carry only ``id`` and ``created_at``, because they are never
updated and therefore have no version to advance.
"""

from typing import TypedDict


class CommonFields(TypedDict):
    """Fields every ordinary resource carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class StreamFields(TypedDict):
    """Fields an append-only stream row carries."""

    id: str
    created_at: str


class Client(CommonFields):
    legal_name: str
    primary_state: str
    matter_count: int


class Matter(CommonFields):
    client_id: str
    name: str
    document_count: int
    unbatched_document_count: int
    deadline_utc: str
    complexity_tier: str
    required_languages: list[str]
    required_bar_states: list[str]
    subject_matter_tags: list[str]
    pricing_model: str
    per_document_rate_cents: int | None
    hourly_rate_cents: int | None
    budget_cap_cents: int
    min_staffed_reviewers: int
    onsite_seat_count: int
    remote_work_permitted: bool
    status: str
    suspension_reason: str | None
    staffed_reviewer_count: int
    committed_spend_cents: int
    required_pace_dph: float


class ReviewProtocol(CommonFields):
    matter_id: str
    revision_number: int
    issue_codes: list[str]
    privilege_criteria: list[str]
    qc_sample_pct: float
    privilege_sample_pct: float
    max_discrepancy_pct: float
    min_pace_dph: int
    second_level_required: bool
    status: str
    change_notes: str | None
    approved_at: str | None


class Reviewer(CommonFields):
    full_name: str
    bar_admissions: list[str]
    languages: list[str]
    subject_matter_tags: list[str]
    tier: str
    hourly_cost_cents: int
    max_concurrent_batches: int
    remote_work_authorized: bool
    credential_status: str
    engagement_status: str
    scorecard_strikes: int
    accuracy_score: float
    pace_dph: float
    active_assignment_count: int
    removed_at: str | None


class ConflictsScreening(CommonFields):
    reviewer_id: str
    matter_id: str
    declared_adverse_parties: list[str]
    status: str
    decision_note: str | None
    screened_at: str | None
    waiver_granted: bool | None


class ConfidentialityAgreement(CommonFields):
    reviewer_id: str
    matter_id: str
    coverage_start_utc: str
    coverage_end_utc: str
    remote_work_addendum: bool
    status: str
    executed_at: str | None
    signature_name: str | None
    revocation_reason: str | None


class SecureEnvironmentSession(CommonFields):
    reviewer_id: str
    matter_id: str
    workstation_class: str
    starts_at_utc: str
    ends_at_utc: str
    status: str
    activated_at: str | None
    closed_at: str | None


class Batch(CommonFields):
    matter_id: str
    batch_number: int
    document_count: int
    priority_rank: int | None
    status: str
    privilege_entry_count: int
    qc_sample_target_size: int
    released_at: str | None


class Assignment(CommonFields):
    batch_id: str
    reviewer_id: str
    reassigned_from_assignment_id: str | None
    pass_type: str
    status: str
    documents_coded: int
    minutes_logged: int
    privilege_hits_logged: int
    billable_minutes: int
    effective_per_document_cents: int
    committed_amount_cents: int
    billable_amount_cents: int
    pace_dph: float
    accuracy_pct: float | None
    started_at: str | None
    submitted_at: str | None
    voided_at: str | None
    void_reason: str | None


class QCSample(CommonFields):
    batch_id: str
    validated_by_reviewer_id: str
    sampled_document_count: int
    coding_error_count: int | None
    privilege_error_count: int | None
    discrepancy_rate: float | None
    outcome: str
    validated_at: str | None


class PrivilegeLogEntry(CommonFields):
    matter_id: str
    batch_id: str
    authored_by_reviewer_id: str
    document_ref: str
    privilege_basis: str
    disposition: str
    status: str
    challenge_note: str | None
    validated_at: str | None


class ScorecardEvent(StreamFields):
    """Append-only reviewer scorecard row; no updated_at and no version."""

    reviewer_id: str
    event_type: str
    strike_delta: int
    note: str | None
    source_batch_number: int | None


class BudgetLedgerEntry(StreamFields):
    """Append-only budget ledger row; no updated_at and no version."""

    matter_id: str
    assignment_id: str | None
    entry_type: str
    amount_cents: int
    description: str | None


class ScorecardRead(TypedDict):
    """The dedicated reviewer scorecard computed view."""

    reviewer_id: str
    weighting_applied: str
    accuracy_score: float
    sampled_document_count: int
    total_error_count: int
    scorecard_strikes: int
    pace_dph: float
    engagement_status: str
    removal_threshold: int
    removal_recommended: bool


class SpendProjectionRead(TypedDict):
    """The spend-projection computed view."""

    matter_id: str
    basis_applied: str
    remaining_work_basis_cents: int
    ledger_replay_basis_cents: int
    variance_cents: int
    gross_billable_cents: int
    qc_surcharge_cents: int
    provisional_total_cents: int
    volume_discount_pct: float
    volume_discount_cents: int
    invoice_total_cents: int
    budget_cap_cents: int
    budget_headroom_cents: int


class ClockRead(TypedDict):
    """The logical clock control response."""

    current_utc: str
