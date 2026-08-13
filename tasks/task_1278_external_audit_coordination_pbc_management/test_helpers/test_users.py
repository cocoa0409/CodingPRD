"""Pre-built role headers for every role in the PRD.

All three roles are opaque (PRD §2.1): X-User-ID is an operator identifier
never compared to any entity id. It IS compared — as a plain string — to a
PBC request's `owner_user_id` and to a representation letter's
`prepared_by_user_id`, so ownership-gated and SoD-gated calls must pin the
X-User-ID via the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Shared constants — safe for calls whose success does not depend on the
    # caller's identity (creation, reads, role-violation probes).
    "controller_headers": build_user_headers("ctrl-1", "Controller"),
    "preparer_headers": build_user_headers("prep-1", "Preparer"),
    "auditor_headers": build_user_headers("aud-1", "ExternalAuditor"),
}


def make_controller_headers(user_id: str) -> dict:
    """Controller headers with a specific X-User-ID (rep-letter signing)."""
    return build_user_headers(user_id, "Controller")


def make_preparer_headers(user_id: str) -> dict:
    """Preparer headers with a specific X-User-ID. Mandatory for
    ownership-gated calls: pass the PBC request's owner_user_id."""
    return build_user_headers(user_id, "Preparer")


def make_auditor_headers(user_id: str) -> dict:
    """ExternalAuditor headers with a specific X-User-ID (visits, queries)."""
    return build_user_headers(user_id, "ExternalAuditor")
