"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (PsmAdmin, PsmManager, TrainingCoordinator) use shared constants:
their X-User-ID is not tied to any persisted entity.

Entity-backed roles (Requester, TechnicalReviewer, OpsApprover, PssrLead,
Investigator, Auditor) MUST use the per-instance builders with the acting
Personnel record's id whenever the call is ownership-gated (PRD §2.1: for
these roles X-User-ID is the id of the acting Personnel record and ownership
checks compare resource foreign-key fields to it).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "admin_headers": build_user_headers("test-psm-admin-1", "PsmAdmin"),
    "manager_headers": build_user_headers("test-psm-manager-1", "PsmManager"),
    "coordinator_headers": build_user_headers("test-training-coordinator-1", "TrainingCoordinator"),
    # Entity-backed roles — fallback constants ONLY for calls whose success
    # does not depend on the caller owning the subject resource (e.g. 404s).
    "requester_headers": build_user_headers("test-requester-1", "Requester"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "TechnicalReviewer"),
    "approver_headers": build_user_headers("test-approver-1", "OpsApprover"),
    "pssr_lead_headers": build_user_headers("test-pssr-lead-1", "PssrLead"),
    "investigator_headers": build_user_headers("test-investigator-1", "Investigator"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


# Per-instance builders — pass the actual Personnel.id for ownership-gated calls.
def make_requester_headers(user_id: str) -> dict:
    """Requester headers bound to a specific Personnel record."""
    return build_user_headers(user_id, "Requester")


def make_reviewer_headers(user_id: str) -> dict:
    """TechnicalReviewer headers bound to a specific Personnel record."""
    return build_user_headers(user_id, "TechnicalReviewer")


def make_approver_headers(user_id: str) -> dict:
    """OpsApprover headers bound to a specific Personnel record."""
    return build_user_headers(user_id, "OpsApprover")


def make_pssr_lead_headers(user_id: str) -> dict:
    """PssrLead headers bound to a specific Personnel record."""
    return build_user_headers(user_id, "PssrLead")


def make_investigator_headers(user_id: str) -> dict:
    """Investigator headers bound to a specific Personnel record."""
    return build_user_headers(user_id, "Investigator")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers bound to a specific Personnel record."""
    return build_user_headers(user_id, "Auditor")


def make_manager_headers(user_id: str = "test-psm-manager-1") -> dict:
    """PsmManager headers (opaque id; override only to exercise verifier SoD)."""
    return build_user_headers(user_id, "PsmManager")
