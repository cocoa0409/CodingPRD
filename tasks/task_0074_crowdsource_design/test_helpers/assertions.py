"""Entity assertions and domain invariant checkers.

For every entity defined in PRD §2.4 + §3, assert_<entity>(data) verifies
the structural contract: id, timestamps, version (when applicable), and
field types/enums. Entities that PRD §2.4 declares as carrying ONLY
id + created_at (DesignCategory, ReviewerPool, AuditEvent) MUST NOT
have updated_at / version asserted — checking those fields would force
the implementer to ship fields PRD told them not to expose.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Enum value sets (PRD §2.12)
# ---------------------------------------------------------------------------
CLIENT_STATUSES = {"ACTIVE", "SUSPENDED"}
CLIENT_TAX_JURISDICTIONS = {"RESIDENT", "NON_RESIDENT"}
DESIGNER_QUALIFICATION_LEVELS = {"NOVICE", "JUNIOR", "SENIOR", "EXPERT"}
DESIGNER_TAX_RESIDENCIES = {"RESIDENT", "NON_RESIDENT"}
DESIGNER_STATUSES = {"ACTIVE", "SUSPENDED", "BANNED"}
PROJECT_STATUSES = {
    "DRAFT", "UNDER_PLATFORM_REVIEW", "ON_SHELF", "IN_PRELIMINARY",
    "IN_SEMIFINAL", "IN_FINAL", "AWARDED", "CLOSED", "REJECTED", "CANCELLED",
}
STAGE_KINDS = {"PRELIMINARY", "SEMIFINAL", "FINAL"}
STAGE_STATUSES = {"PENDING", "OPEN", "AGGREGATING", "PUBLISHED", "EXPIRED"}
SUBMISSION_STATUSES = {
    "DRAFT", "SCREENING", "SCREEN_REJECTED", "ACCEPTED",
    "ADVANCING_SEMIFINAL", "ADVANCING_FINAL",
    "WINNER", "RUNNER_UP", "ELIMINATED", "WITHDRAWN",
}
ORIGINALITY_VARIANTS = {"PRELIMINARY_SCAN", "FINAL_CROSSCHECK"}
REVIEW_ASSIGNMENT_STATUSES = {"PENDING", "SUBMITTED", "DISPUTED", "VOIDED"}
DISPUTE_TYPES = {"PLAGIARISM", "SCORING_FAIRNESS", "COPYRIGHT", "PAYMENT"}
DISPUTE_SUBJECT_REF_KINDS = {
    "SUBMISSION", "REVIEW_ASSIGNMENT", "COPYRIGHT_TRANSFER", "PRIZE_PAYMENT",
}
DISPUTE_FILER_KINDS = {"CLIENT", "DESIGNER", "REVIEWER", "PLATFORM"}
DISPUTE_STATUSES = {
    "FILED", "MEDIATING_STAGE1", "MEDIATING_STAGE2", "ARBITRATION",
    "RESOLVED_UPHELD", "RESOLVED_REJECTED", "WITHDRAWN",
}
COPYRIGHT_SCOPES = {"FULL", "LIMITED"}
COPYRIGHT_STATUSES = {
    "DRAFTED", "PENDING_SIGNATURES", "ALL_SIGNED",
    "REGISTERING", "REGISTERED", "VOIDED",
}
SIGNER_PARTY_KINDS = {"CLIENT", "DESIGNER", "PLATFORM_NOTARY"}
PRIZE_TIER_KINDS = {"MAIN", "CONSOLATION"}
PRIZE_PAYMENT_STATUSES = {"SCHEDULED", "PAYING", "PAID", "FAILED", "REVERSED"}
AUDIT_ACTION_KINDS = {
    "REVIEW_SUBMITTED", "REVIEW_VOIDED", "REVIEW_DISPUTED", "STAGE_PUBLISHED",
    "COPYRIGHT_DRAFTED", "COPYRIGHT_SIGNED", "COPYRIGHT_REGISTERED",
    "COPYRIGHT_VOIDED", "DISPUTE_FILED", "DISPUTE_RESOLVED", "PRIZE_PAID",
}
AUDIT_ACTOR_KINDS = {"CLIENT", "DESIGNER", "REVIEWER", "PLATFORM", "SYSTEM"}
AUDIT_SUBJECT_KINDS = {
    "SUBMISSION", "REVIEW_ASSIGNMENT", "REVIEW_STAGE",
    "COPYRIGHT_TRANSFER", "DISPUTE", "PRIZE_PAYMENT",
}


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------
def _assert_common_full(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: most entities share id, created_at, updated_at, version."""
    assert "id" in data, f"{label}.id missing"
    assert is_valid_uuid(data["id"]), f"{label}.id must be UUID, got {data['id']!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be int, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{label}.version must be >= 1"


def _assert_common_append_only(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: DesignCategory, ReviewerPool, AuditEvent carry ONLY
    id and created_at."""
    assert "id" in data, f"{label}.id missing"
    assert is_valid_uuid(data["id"]), f"{label}.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_client(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "Client")
    assert isinstance(data["company_name"], str) and 1 <= len(data["company_name"]) <= 200
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert data["status"] in CLIENT_STATUSES
    assert data["tax_jurisdiction"] in CLIENT_TAX_JURISDICTIONS


def assert_designer(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "Designer")
    assert isinstance(data["display_name"], str)
    assert data["qualification_level"] in DESIGNER_QUALIFICATION_LEVELS
    assert isinstance(data["categories"], list) and len(data["categories"]) >= 1
    assert data["tax_residency"] in DESIGNER_TAX_RESIDENCIES
    assert data["status"] in DESIGNER_STATUSES
    # PRD §2.6: trust_score is a real number on [0,100] with two decimals.
    assert isinstance(data["trust_score"], (int, float))
    assert 0 <= float(data["trust_score"]) <= 100


def assert_design_category(data: Dict[str, Any]) -> None:
    _assert_common_append_only(data, "DesignCategory")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["similarity_corpus_id"], str)


def assert_reviewer_pool(data: Dict[str, Any]) -> None:
    _assert_common_append_only(data, "ReviewerPool")
    assert isinstance(data["reviewer_id"], str) and data["reviewer_id"]
    assert isinstance(data["name"], str)
    assert isinstance(data["categories"], list)
    assert isinstance(data["max_concurrent_assignments"], int)
    assert 1 <= data["max_concurrent_assignments"] <= 100
    assert isinstance(data.get("conflict_designer_ids", []), list)


def assert_project(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "Project")
    assert data["status"] in PROJECT_STATUSES
    assert isinstance(data["client_id"], str)
    assert isinstance(data["category_code"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["brief"], str)
    assert isinstance(data["reference_material_urls"], list)
    assert isinstance(data["prize_pool_cents"], int)
    assert is_iso8601_timestamp(data["opens_at"])
    assert is_iso8601_timestamp(data["submission_deadline"])
    assert is_iso8601_timestamp(data["final_decision_deadline"])
    assert isinstance(data["max_submissions_per_designer"], int)
    assert isinstance(data["client_participates_final"], bool)
    # published_winner_list defaults to [] until AWARDED.
    assert isinstance(data.get("published_winner_list", []), list)


def assert_review_stage(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "ReviewStage")
    assert data["stage_kind"] in STAGE_KINDS
    assert data["status"] in STAGE_STATUSES
    assert isinstance(data["passing_threshold"], (int, float))
    assert 0 <= float(data["passing_threshold"]) <= 100
    assert isinstance(data["reviewer_quorum"], int)
    assert data["reviewer_quorum"] >= 3
    assert isinstance(data["rubric"], dict)
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_submission(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "Submission")
    assert data["status"] in SUBMISSION_STATUSES
    assert isinstance(data["project_id"], str)
    # PRD §2.10: designer_id may be null for masked reads pre-AWARDED.
    if data.get("designer_id") is not None:
        assert isinstance(data["designer_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["asset_urls"], list)
    assert isinstance(data["original_work_declared"], bool)
    if data.get("originality_score") is not None:
        assert 0 <= float(data["originality_score"]) <= 100
    if data.get("originality_variant") is not None:
        assert data["originality_variant"] in ORIGINALITY_VARIANTS


def assert_review_assignment(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "ReviewAssignment")
    assert data["status"] in REVIEW_ASSIGNMENT_STATUSES
    assert isinstance(data["review_stage_id"], str)
    assert isinstance(data["submission_id"], str)
    assert isinstance(data["reviewer_id"], str)
    # anonymized_alias must always be present (server-minted).
    assert isinstance(data.get("anonymized_alias", ""), str)
    if data["status"] == "SUBMITTED":
        # aggregated_score is computed once SUBMITTED.
        assert "aggregated_score" in data
        assert isinstance(data["aggregated_score"], (int, float))
        assert 0 <= float(data["aggregated_score"]) <= 100


def assert_dispute(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "Dispute")
    assert data["dispute_type"] in DISPUTE_TYPES
    assert data["subject_ref_kind"] in DISPUTE_SUBJECT_REF_KINDS
    assert data["filer_kind"] in DISPUTE_FILER_KINDS
    assert data["status"] in DISPUTE_STATUSES
    assert isinstance(data.get("filed_within_window", True), bool)


def assert_copyright_transfer(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "CopyrightTransfer")
    assert data["status"] in COPYRIGHT_STATUSES
    assert data["scope"] in COPYRIGHT_SCOPES
    assert isinstance(data.get("usage_rights", []), list)
    # PRD §3.8: signers pre-populated in fixed order on issue.
    if data["status"] != "DRAFTED":
        assert isinstance(data.get("signers", []), list)


def assert_prize_tier(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "PrizeTier")
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert isinstance(data["gross_amount_cents"], int)
    assert data["gross_amount_cents"] >= 0
    assert data["tier_kind"] in PRIZE_TIER_KINDS


def assert_prize_payment(data: Dict[str, Any]) -> None:
    _assert_common_full(data, "PrizePayment")
    assert data["status"] in PRIZE_PAYMENT_STATUSES
    # PRD §2.6: integer cents end-to-end.
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["withholding_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    assert data["gross_amount_cents"] >= 0
    assert data["withholding_cents"] >= 0
    # PRD §3.7: net = gross - withholding.
    assert data["net_amount_cents"] == (
        data["gross_amount_cents"] - data["withholding_cents"]
    ), (
        f"net_amount_cents must equal gross - withholding; "
        f"got gross={data['gross_amount_cents']} - "
        f"withholding={data['withholding_cents']} != "
        f"net={data['net_amount_cents']}"
    )


def assert_audit_event(data: Dict[str, Any]) -> None:
    _assert_common_append_only(data, "AuditEvent")
    assert data["action_kind"] in AUDIT_ACTION_KINDS
    assert data["actor_kind"] in AUDIT_ACTOR_KINDS
    assert data["subject_kind"] in AUDIT_SUBJECT_KINDS
    assert isinstance(data.get("payload", {}), dict)
    assert is_iso8601_timestamp(data["occurred_at"])


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def find_first(items: Iterable[Dict[str, Any]],
               predicate: Callable[[Dict[str, Any]], bool]) -> Optional[Dict[str, Any]]:
    for item in items:
        if predicate(item):
            return item
    return None


def find_all(items: Iterable[Dict[str, Any]],
             predicate: Callable[[Dict[str, Any]], bool]) -> List[Dict[str, Any]]:
    return [item for item in items if predicate(item)]


__all__ = [
    "CLIENT_STATUSES", "CLIENT_TAX_JURISDICTIONS",
    "DESIGNER_QUALIFICATION_LEVELS", "DESIGNER_TAX_RESIDENCIES",
    "DESIGNER_STATUSES",
    "PROJECT_STATUSES",
    "STAGE_KINDS", "STAGE_STATUSES",
    "SUBMISSION_STATUSES", "ORIGINALITY_VARIANTS",
    "REVIEW_ASSIGNMENT_STATUSES",
    "DISPUTE_TYPES", "DISPUTE_SUBJECT_REF_KINDS",
    "DISPUTE_FILER_KINDS", "DISPUTE_STATUSES",
    "COPYRIGHT_SCOPES", "COPYRIGHT_STATUSES",
    "SIGNER_PARTY_KINDS",
    "PRIZE_TIER_KINDS", "PRIZE_PAYMENT_STATUSES",
    "AUDIT_ACTION_KINDS", "AUDIT_ACTOR_KINDS", "AUDIT_SUBJECT_KINDS",
    "assert_client", "assert_designer", "assert_design_category",
    "assert_reviewer_pool",
    "assert_project", "assert_review_stage", "assert_submission",
    "assert_review_assignment", "assert_dispute",
    "assert_copyright_transfer", "assert_prize_tier",
    "assert_prize_payment", "assert_audit_event",
    "find_first", "find_all",
]
