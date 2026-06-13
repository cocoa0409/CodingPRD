"""Pre-built role headers for every role in the PRD.

Per PRD 2.1: Clerk, Judge, and SystemAdmin are opaque operator identities; their
X-User-ID is not tied to any persisted entity. The Attorney role is entity-backed
by the Party record: when X-User-Role is Attorney, X-User-ID is the opaque
attorney identifier that appears as attorney_user_id on the parties that attorney
represents. Ownership checks compare that party's attorney_user_id to X-User-ID.

Concretely, the attorney identity is the attorney_user_id STRING supplied when a
party is created (e.g. "att_1"), NOT the Party's id. The per-instance builder
make_attorney_headers(attorney_user_id) must be called with that string for any
ownership-gated attorney call (withdraw motion, resubmit fee waiver).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constants are the canonical form.
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    "clerk_headers": build_user_headers("clerk-1", "Clerk"),
    "judge_headers": build_user_headers("judge-1", "Judge"),
    # Attorney shared constant — safe only for non-ownership tests (403 on bad
    # payload, 404 on missing resource, or e-filing where no ownership of the
    # acting resource is checked). The default identity is "att_1".
    "attorney_headers": build_user_headers("att_1", "Attorney"),
}


def make_attorney_headers(attorney_user_id: str) -> dict:
    """For the Attorney role (entity_backed:Party). Pass the attorney_user_id
    string that was supplied on the represented party (e.g. "att_1") whenever the
    call is ownership-gated."""
    return build_user_headers(attorney_user_id, "Attorney")


def make_clerk_headers(user_id: str = "clerk-1") -> dict:
    return build_user_headers(user_id, "Clerk")


def make_judge_headers(user_id: str = "judge-1") -> dict:
    return build_user_headers(user_id, "Judge")


def make_system_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")
