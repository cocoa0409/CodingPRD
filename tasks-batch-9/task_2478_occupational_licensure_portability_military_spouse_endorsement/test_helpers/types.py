"""TypedDict shapes for the Licensure Portability API resources.

Most resources carry the standard audit triplet (`created_at`, `updated_at`,
`version`).  `FeeLedgerEntry` is the single exception: it is append-only and
carries only `id` and `created_at`, so its shape deliberately omits the other
two keys.
"""

from typing import Any, Dict, List, Optional, TypedDict


class AuditedResource(TypedDict):
    """The identity and audit fields shared by every mutable resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Profession(AuditedResource, total=False):
    profession_code: str
    title: str
    required_scope_elements: List[str]
    critical_scope_elements: List[str]
    required_practice_hours: int
    requirement_hours_total: float
    exam_waiver_min_score: float
    jurisprudence_exam_required: bool
    universal_recognition_min_residency_months: int
    standard_processing_days: int
    base_fee_cents: int
    endorsement_fee_cents: int
    exam_fee_cents: int
    jurisprudence_fee_cents: int
    permit_fee_cents: int
    expedite_surcharge_pct: float


class ReciprocalAgreement(AuditedResource, total=False):
    profession_id: str
    partner_state: str
    fee_waiver_pct: float
    exam_waiver_allowed: bool
    jurisprudence_waiver_allowed: bool
    expires_on: str


class Applicant(AuditedResource, total=False):
    full_name: str
    state_code: str
    residency_months: int
    military_status: str
    disciplinary_risk_index_reported: float
    disciplinary_risk_index_effective: float
    good_standing_flag: bool
    fee_waiver_eligible: bool


class OutOfStateCredential(AuditedResource, total=False):
    applicant_id: str
    issuing_state: str
    license_number: str
    scope_elements: List[str]
    practice_hours: int
    status: str
    verified_good_standing: bool
    issued_at: str


class MilitaryTrainingRecord(AuditedResource, total=False):
    applicant_id: str
    category: str
    documented_hours: int
    source_document: str
    verified: bool


class DisciplinaryRecord(AuditedResource, total=False):
    applicant_id: str
    source_state: str
    source_database: str
    severity: str
    action_effective_at: str
    reported_at: str
    resolved: bool
    resolved_at: Optional[str]


class LicenseApplication(AuditedResource, total=False):
    applicant_id: str
    profession_id: str
    primary_credential_id: str
    pathway: str
    expedited: bool
    status: str
    deficiency_cycle_count: int
    submitted_at: Optional[str]
    review_deadline_at: Optional[str]
    decided_at: Optional[str]
    processing_elapsed_days: int
    processing_standard_met: Optional[bool]
    statutory_waiver_pct: float
    gross_total_cents: int
    fee_balance_cents: int
    requirement_hours_satisfied: float
    requirement_hours_remaining: float
    national_exam_passed: bool
    jurisprudence_exam_passed: bool
    pathway_risk_index: float
    scope_reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]


class CredentialEvaluation(AuditedResource, total=False):
    application_id: str
    credential_id: str
    variant: str
    scope_review_status: str
    discipline_review_status: str
    overall_status: str
    matched_scope_elements: List[str]
    missing_scope_elements: List[str]
    equivalency_score: Optional[float]
    exam_waiver_granted: bool
    finalized_at: Optional[str]
    reviewed_by_user_id: Optional[str]


class CreditAward(AuditedResource, total=False):
    application_id: str
    training_record_id: str
    awarded_hours: float
    status: str
    revoked_at: Optional[str]


class TemporaryPermit(AuditedResource, total=False):
    application_id: str
    effective_at: str
    expires_at: str
    permit_max_days: int
    permit_fee_cents: int
    status: str
    converted_at: Optional[str]
    revoked_at: Optional[str]
    revocation_reason_code: Optional[str]


class License(AuditedResource, total=False):
    application_id: str
    profession_id: str
    converted_from_permit_id: Optional[str]
    license_number: str
    status: str
    issued_at: str
    expires_at: str


class Evaluator(AuditedResource, total=False):
    full_name: str
    profession_code: str
    status: str
    max_concurrent_reviews: int
    open_assignment_count: int


class ReviewAssignment(AuditedResource, total=False):
    evaluator_id: str
    application_id: str
    window_start_at: str
    window_end_at: str
    status: str
    closed_at: Optional[str]


class FeeLedgerEntry(TypedDict, total=False):
    """Append-only ledger movement: `id` and `created_at` only, by design."""

    id: str
    created_at: str
    application_id: str
    entry_type: str
    amount_cents: int
    memo: str


# Loose alias for envelope payloads whose shape is not being asserted.
JsonDict = Dict[str, Any]
