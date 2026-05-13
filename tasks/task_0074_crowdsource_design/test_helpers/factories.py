"""Payload factories — one per input-bearing endpoint.

Each factory emits ONLY the fields PRD declares as `source: input`.
Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


_OMIT = "__OMIT__"


# ---------------------------------------------------------------------------
# Unique-suffix helpers
# ---------------------------------------------------------------------------
def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def _alpha_suffix(n: int = 10) -> str:
    """Generate an uppercase A-Z-only suffix (no digits) for fields that
    PRD constrains to letters/underscores."""
    import secrets
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def unique_code(prefix: str = "CAT") -> str:
    """PRD §3.1: code is uppercase A-Z and underscores only. No digits."""
    return f"{prefix}_{_alpha_suffix(10)}"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{unique_suffix()}@example.com"


def unique_name(prefix: str = "Entity") -> str:
    return f"{prefix} {unique_suffix()}"


def unique_display_name(prefix: str = "Designer") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_https_url(prefix: str = "asset") -> str:
    return f"https://cdn.example.com/{prefix}/{unique_suffix()}.png"


def unique_idempotency_key(prefix: str = "idem") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_reviewer_id(prefix: str = "rev") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_corpus_id(prefix: str = "corpus") -> str:
    return f"{prefix}-{unique_suffix()}"


# ---------------------------------------------------------------------------
# DesignCategory  POST /design-categories  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_design_category_payload(
    *,
    code: Optional[str] = None,
    name: Optional[str] = None,
    similarity_corpus_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Each category carries a stable uppercase code (with
    only A-Z letters and underscores, unique across the catalog), a
    human-readable name, and a similarity_corpus_id that identifies the
    public-image corpus the platform's preliminary plagiarism scan
    compares submissions against.'"""
    payload: Dict[str, Any] = {
        "code": code or unique_code("LOGO"),
        "name": name or unique_name("Category"),
        "similarity_corpus_id": similarity_corpus_id or unique_corpus_id(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Client  POST /clients  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_client_payload(
    *,
    company_name: Optional[str] = None,
    contact_email: Optional[str] = None,
    tax_jurisdiction: str = "RESIDENT",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Clients are registered by PlatformOps with company_name
    (1 to 200 characters), contact_email validated as an RFC 5322
    address, and tax_jurisdiction set to either RESIDENT or
    NON_RESIDENT.'"""
    payload: Dict[str, Any] = {
        "company_name": company_name or unique_name("ClientCo"),
        "contact_email": contact_email or unique_email("client"),
        "tax_jurisdiction": tax_jurisdiction,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Designer  POST /designers  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_designer_payload(
    *,
    display_name: Optional[str] = None,
    qualification_level: str = "NOVICE",
    categories: Optional[List[str]] = None,
    tax_residency: str = "RESIDENT",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Designers are likewise registered by PlatformOps, with
    display_name (1 to 80 characters, unique across all designers),
    qualification_level (defaulting to NOVICE), a categories array drawn
    as a non-empty subset of the DesignCategory.code set, and
    tax_residency (RESIDENT or NON_RESIDENT).'"""
    payload: Dict[str, Any] = {
        "display_name": display_name or unique_display_name(),
        "qualification_level": qualification_level,
        "categories": categories if categories is not None else ["LOGO"],
        "tax_residency": tax_residency,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReviewerPool  POST /reviewer-pool  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_reviewer_payload(
    *,
    reviewer_id: Optional[str] = None,
    name: Optional[str] = None,
    categories: Optional[List[str]] = None,
    max_concurrent_assignments: int = 20,
    conflict_designer_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Reviewers are added to the platform's reviewer pool
    with a unique opaque reviewer_id, a display name, the categories
    they are qualified to score, an integer max_concurrent_assignments
    (1 to 100, default 20), and an optional conflict_designer_ids
    list — the designers whose work this reviewer must never see —
    defaulting to an empty list.'"""
    payload: Dict[str, Any] = {
        "reviewer_id": reviewer_id or unique_reviewer_id(),
        "name": name or unique_name("Reviewer"),
        "categories": categories if categories is not None else ["LOGO"],
        "max_concurrent_assignments": max_concurrent_assignments,
        "conflict_designer_ids": (conflict_designer_ids
                                   if conflict_designer_ids is not None
                                   else []),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Project  POST /projects  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_project_payload(
    *,
    client_id: str,
    category_code: str,
    title: Optional[str] = None,
    brief: Optional[str] = None,
    reference_material_urls: Optional[List[str]] = None,
    prize_pool_cents: int = 1_000_000,
    opens_at: str = "2026-06-01T00:00:00.000Z",
    submission_deadline: str = "2026-06-10T00:00:00.000Z",
    final_decision_deadline: str = "2026-06-30T00:00:00.000Z",
    max_submissions_per_designer: Any = _OMIT,
    client_participates_final: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'The request carries the owning client_id, the
    category_code from the catalog, a title (1 to 200 characters), a
    brief (1 to 5000 characters), reference_material_urls (0 to 20
    entries, each a valid HTTPS URL), the prize_pool_cents budget, the
    timeline triple — opens_at, submission_deadline,
    final_decision_deadline — and two optional governance knobs:
    max_submissions_per_designer (1 to 10, default 3) and
    client_participates_final (default false).'"""
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "category_code": category_code,
        "title": title or unique_name("Project"),
        "brief": brief or "A creative brief for design competition.",
        "reference_material_urls": (
            reference_material_urls
            if reference_material_urls is not None else []
        ),
        "prize_pool_cents": prize_pool_cents,
        "opens_at": opens_at,
        "submission_deadline": submission_deadline,
        "final_decision_deadline": final_decision_deadline,
    }
    if max_submissions_per_designer is not _OMIT:
        payload["max_submissions_per_designer"] = max_submissions_per_designer
    if client_participates_final is not _OMIT:
        payload["client_participates_final"] = client_participates_final
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PrizeTier  POST /projects/{id}/prize-tiers  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_prize_tier_payload(
    *,
    rank: int = 1,
    gross_amount_cents: int = 1_000_000,
    tier_kind: str = "MAIN",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'Each PrizeTier carries an integer rank of at least 1
    (unique within the project), a gross_amount_cents of at least 0,
    and a tier_kind of either MAIN or CONSOLATION.'"""
    payload: Dict[str, Any] = {
        "rank": rank,
        "gross_amount_cents": gross_amount_cents,
        "tier_kind": tier_kind,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReviewStage  POST /projects/{id}/review-stages  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_review_stage_payload(
    *,
    stage_kind: str = "PRELIMINARY",
    passing_threshold: float = 60.00,
    reviewer_quorum: int = 3,
    rubric: Optional[Dict[str, float]] = None,
    starts_at: str = "2026-06-10T00:00:00.000Z",
    ends_at: str = "2026-06-15T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'Each ReviewStage is created for one of the three
    values of stage_kind (PRELIMINARY, SEMIFINAL, FINAL) and carries a
    passing_threshold in the range 0.00 to 100.00, a reviewer_quorum of
    at least 3, a rubric mapping each criterion code to a non-negative
    weight, and the stage window pair starts_at and ends_at.'"""
    payload: Dict[str, Any] = {
        "stage_kind": stage_kind,
        "passing_threshold": passing_threshold,
        "reviewer_quorum": reviewer_quorum,
        "rubric": rubric if rubric is not None else {"creativity": 50,
                                                      "execution": 50},
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Submission  POST /projects/{id}/submissions  (PRD §3.3)
# ---------------------------------------------------------------------------
def create_submission_payload(
    *,
    designer_id: str,
    title: Optional[str] = None,
    asset_urls: Optional[List[str]] = None,
    original_work_declared: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'Each submission carries designer_id (which must match
    X-User-ID for the Designer role), title (1 to 120 characters),
    asset_urls (1 to 10 HTTPS URLs), and original_work_declared, which
    must be true on creation; a missing or false declaration is
    rejected with ERR_ORIGINAL_DECLARATION_REQUIRED.'"""
    payload: Dict[str, Any] = {
        "designer_id": designer_id,
        "title": title or unique_name("Submission"),
        "asset_urls": asset_urls if asset_urls is not None
                                else [unique_https_url()],
        "original_work_declared": original_work_declared,
    }
    payload.update(overrides)
    return payload


def patch_submission_payload(
    *,
    title: Any = _OMIT,
    asset_urls: Any = _OMIT,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'A designer may modify or withdraw their own
    submission while the modify window is still open.'"""
    payload: Dict[str, Any] = {}
    if title is not _OMIT:
        payload["title"] = title
    if asset_urls is not _OMIT:
        payload["asset_urls"] = asset_urls
    if version is not _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReviewAssignment  POST /review-assignments  (PRD §3.4)
# ---------------------------------------------------------------------------
def create_review_assignment_payload(
    *,
    review_stage_id: str,
    submission_id: str,
    reviewer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'An assignment carries the review_stage_id, the
    submission_id, and the reviewer_id.'"""
    payload: Dict[str, Any] = {
        "review_stage_id": review_stage_id,
        "submission_id": submission_id,
        "reviewer_id": reviewer_id,
    }
    payload.update(overrides)
    return payload


def submit_scores_payload(
    *,
    criterion_scores: Dict[str, float],
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'The reviewer scores the submission by supplying
    criterion_scores, a map from criterion code to a numeric score on
    the 0 to 100 scale.'"""
    payload: Dict[str, Any] = {"criterion_scores": criterion_scores}
    if version is not _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CopyrightTransfer  POST /copyright-transfers  (PRD §3.8)
# ---------------------------------------------------------------------------
def create_copyright_transfer_payload(
    *,
    project_id: str,
    submission_id: str,
    scope: str = "FULL",
    usage_rights: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'A PlatformOps operator may also create a transfer
    manually for a winning or runner-up submission when the auto-draft
    is missing, supplying project_id, submission_id, scope, and
    usage_rights when applicable.'"""
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "submission_id": submission_id,
        "scope": scope,
    }
    if usage_rights is not None:
        payload["usage_rights"] = usage_rights
    elif scope == "FULL":
        payload["usage_rights"] = []
    else:
        payload["usage_rights"] = ["print", "digital"]
    payload.update(overrides)
    return payload


def sign_transfer_payload(
    *,
    signer_party_kind: str,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'Each sign call supplies a signer_party_kind of CLIENT,
    DESIGNER, or PLATFORM_NOTARY and (optionally) version.'"""
    payload: Dict[str, Any] = {"signer_party_kind": signer_party_kind}
    if version is not _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


def void_transfer_payload(
    *,
    dispute_id: str,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'In all three paths, the void call carries the
    originating dispute_id and supports version.'"""
    payload: Dict[str, Any] = {"dispute_id": dispute_id}
    if version is not _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PrizePayment dispatch  POST /prize-payments/{id}/dispatch  (PRD §3.9)
# ---------------------------------------------------------------------------
def dispatch_payment_payload(
    *,
    idempotency_key: Optional[str] = None,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: 'The dispatch call supplies an idempotency_key that
    must be unique across the pair (project_id, prize_tier_id).'"""
    payload: Dict[str, Any] = {
        "idempotency_key": idempotency_key or unique_idempotency_key(),
    }
    if version is not _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Dispute  POST /disputes  (PRD §3.6)
# ---------------------------------------------------------------------------
def create_dispute_payload(
    *,
    project_id: str,
    dispute_type: str,
    subject_ref_kind: str,
    subject_ref_id: str,
    filer_kind: str,
    filer_id: str,
    evidence_urls: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'Each filing carries a scoping project_id, a
    dispute_type from PLAGIARISM, SCORING_FAIRNESS, COPYRIGHT, or
    PAYMENT, a subject_ref_kind describing what the dispute is about
    (SUBMISSION, REVIEW_ASSIGNMENT, COPYRIGHT_TRANSFER, or
    PRIZE_PAYMENT), a subject_ref_id matching that kind, a filer_kind
    declaring which class of party is filing, and a filer_id that
    resolves to the corresponding entity.'"""
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "dispute_type": dispute_type,
        "subject_ref_kind": subject_ref_kind,
        "subject_ref_id": subject_ref_id,
        "filer_kind": filer_kind,
        "filer_id": filer_id,
    }
    if evidence_urls is not None:
        payload["evidence_urls"] = evidence_urls
    payload.update(overrides)
    return payload


def resolve_dispute_payload(
    *,
    outcome: str,
    resolution_note: str = "Final resolution note.",
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'PlatformOps resolves the dispute by supplying an
    outcome of either UPHELD or REJECTED and a resolution_note.'"""
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "resolution_note": resolution_note,
    }
    if version is not _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Award  POST /projects/{id}/award  (PRD §3.7)
# ---------------------------------------------------------------------------
def award_payload(
    *,
    tier_assignments: List[Dict[str, str]],
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'The award call accepts tier_assignments, an ordered
    list of pairs of prize_tier_id and submission_id that names a
    winning submission for every PrizeTier of this project.'"""
    payload: Dict[str, Any] = {"tier_assignments": tier_assignments}
    if version is not _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock & inbound events  (PRD §2.11)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §2.11: 'an administrative capability advances the virtual
    clock to a supplied ISO 8601 instant: the request body carries a to
    field.'"""
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


def emit_event_payload(
    *,
    event_type: str,
    subject_id: str,
    payload: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §2.11: 'the request body carries event_type, the subject_id
    of the targeted resource, and an optional payload.'"""
    body: Dict[str, Any] = {
        "event_type": event_type,
        "subject_id": subject_id,
    }
    if payload is not _OMIT:
        body["payload"] = payload
    body.update(overrides)
    return body


__all__ = [
    "unique_suffix", "unique_code", "unique_email", "unique_name",
    "unique_display_name", "unique_https_url", "unique_idempotency_key",
    "unique_reviewer_id", "unique_corpus_id",
    "create_design_category_payload",
    "create_client_payload",
    "create_designer_payload",
    "create_reviewer_payload",
    "create_project_payload",
    "create_prize_tier_payload",
    "create_review_stage_payload",
    "create_submission_payload",
    "patch_submission_payload",
    "create_review_assignment_payload",
    "submit_scores_payload",
    "create_copyright_transfer_payload",
    "sign_transfer_payload",
    "void_transfer_payload",
    "dispatch_payment_payload",
    "create_dispute_payload",
    "resolve_dispute_payload",
    "award_payload",
    "clock_advance_payload",
    "emit_event_payload",
]
