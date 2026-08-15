"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (Anonymous, HotlineSupervisor, DataProtectionOfficer, AgencyAdmin,
Analyst) carry an operator identifier never compared to any entity id, so the
shared constants below are canonical. Entity-backed roles (Caller, Counselor)
MUST be built per instance via the make_*_builders with the real entity id —
ownership and segregation-of-duties checks compare X-User-ID against the
entity's own id fields.
"""
from prd_bench_local_runner.testing import build_user_headers


def _anonymous_headers() -> dict:
    # PRD §2.1: X-User-ID is required for every role except Anonymous.
    headers = build_user_headers("test-anonymous-1", "Anonymous")
    headers.pop("X-User-ID", None)
    return headers


TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "anonymous_headers": _anonymous_headers(),
    "supervisor_headers": build_user_headers("test-supervisor-1", "HotlineSupervisor"),
    "dpo_headers": build_user_headers("test-dpo-1", "DataProtectionOfficer"),
    "agency_admin_headers": build_user_headers("test-agency-admin-1", "AgencyAdmin"),
    "analyst_headers": build_user_headers("test-analyst-1", "Analyst"),
    # Entity-backed fallbacks for NON-ownership tests only (400/404 probes).
    "caller_headers": build_user_headers("test-caller-1", "Caller"),
    "counselor_headers": build_user_headers("test-counselor-1", "Counselor"),
}


def make_caller_headers(caller_id: str) -> dict:
    """Caller is entity_backed: pass the real Caller.id for ownership-gated calls."""
    return build_user_headers(caller_id, "Caller")


def make_counselor_headers(counselor_id: str) -> dict:
    """Counselor is entity_backed: pass the real Counselor.id whenever the call
    is ownership- or segregation-of-duties-gated."""
    return build_user_headers(counselor_id, "Counselor")
