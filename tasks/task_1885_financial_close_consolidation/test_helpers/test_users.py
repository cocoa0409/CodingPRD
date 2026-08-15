"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque (identity: opaque) — X-User-ID is an opaque operator
identifier, never tied to a persisted entity. Shared constants are therefore the
canonical form; per-instance builders exist purely for reader clarity at call
sites that exercise actor-vs-recorder (SoD) boundaries.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "controller_headers": build_user_headers("controller-1", "Controller"),
    "preparer_headers": build_user_headers("prep-1", "Preparer"),
    "approver_headers": build_user_headers("approver-1", "Approver"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
}


def make_controller_headers(user_id: str) -> dict:
    """Controller headers for a specific opaque operator id."""
    return build_user_headers(user_id, "Controller")


def make_preparer_headers(user_id: str) -> dict:
    """Preparer headers for a specific opaque operator id.

    Use when the call is SoD-gated or assignee-gated (JE preparer/post,
    task start/complete/unstart, recon review/clear, accrual work).
    """
    return build_user_headers(user_id, "Preparer")


def make_approver_headers(user_id: str) -> dict:
    """Approver headers for a specific opaque operator id.

    Use when the call is SoD-gated (approve, confirm, verify, write-off).
    """
    return build_user_headers(user_id, "Approver")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers for a specific opaque operator id (read-only)."""
    return build_user_headers(user_id, "Auditor")
