"""Pre-built role headers for every role in the PRD (PRD §2.1).

Of the five roles, only ``EnforcementOfficer`` is entity-backed: its
``X-User-ID`` must equal the ``id`` of an actual ``Officer`` created via
``POST /officers``. Ownership checks (opening/closing a shift, issuing a
citation) compare the shift's ``officer_id`` against ``X-User-ID`` and
reject a mismatch with ``ERR_NOT_RESOURCE_OWNER``.

``Admin``, ``Supervisor``, ``HearingOfficer``, and ``Motorist`` are opaque:
their ``X-User-ID`` is accepted for auth but never compared to any entity,
so the shared constants below are the canonical form for them.

The shared ``enforcement_officer_headers`` constant carries a placeholder
``X-User-ID`` and is safe ONLY for tests that don't exercise ownership
(e.g., 403-on-wrong-role). Ownership-gated success paths MUST call
``make_enforcement_officer_headers(officer["id"])``.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
    "hearing_officer_headers": build_user_headers("test-hearing-officer-1", "HearingOfficer"),
    "motorist_headers": build_user_headers("test-motorist-1", "Motorist"),
    # Placeholder — safe only for non-ownership (negative-path) tests.
    "enforcement_officer_headers": build_user_headers("test-officer-1", "EnforcementOfficer"),
}

# Headers carrying no recognized X-User-Role — for the unauthenticated path.
ANON_HEADERS = {"Content-Type": "application/json"}


def make_enforcement_officer_headers(officer_id: str) -> dict:
    """Headers for an EnforcementOfficer bound to a specific Officer.id (PRD §2.1).

    Pass the real Officer.id whenever the call (open/close shift, issue
    citation) is ownership-gated."""
    return build_user_headers(officer_id, "EnforcementOfficer")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
