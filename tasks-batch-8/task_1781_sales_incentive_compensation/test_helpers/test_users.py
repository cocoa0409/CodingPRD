"""Pre-built role headers for every role in the PRD.

CompAdmin, CompAnalyst, and CompManager are opaque operator identities:
X-User-ID is not tied to any persisted entity (it is only recorded, e.g. as
created_by_user_id, for segregation-of-duties comparison). Rep is
identity-backed by the Rep entity: X-User-ID must be the acting rep's id, so
ownership-gated calls MUST use make_rep_headers(rep["id"]) — never the shared
fallback constant.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ANALYST_USER_ID,
    MANAGER_USER_ID,
    PLAN_CREATOR_USER_ID,
    PLAN_PUBLISHER_USER_ID,
)

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    # Plan creator (segregation of duties: cannot publish/revise own plan).
    "comp_admin_headers": build_user_headers(PLAN_CREATOR_USER_ID, "CompAdmin"),
    # Second admin (publishes/revises plans created by comp_admin_headers).
    "comp_admin_alt_headers": build_user_headers(PLAN_PUBLISHER_USER_ID, "CompAdmin"),
    "comp_analyst_headers": build_user_headers(ANALYST_USER_ID, "CompAnalyst"),
    "comp_manager_headers": build_user_headers(MANAGER_USER_ID, "CompManager"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g. wrong-role checks).
    "rep_headers": build_user_headers("test-rep-1", "Rep"),
}


def make_comp_admin_headers(user_id: str) -> dict:
    """CompAdmin is an opaque identity; any operator id is valid."""
    return build_user_headers(user_id, "CompAdmin")


def make_comp_analyst_headers(user_id: str) -> dict:
    """CompAnalyst is an opaque identity; any operator id is valid."""
    return build_user_headers(user_id, "CompAnalyst")


def make_comp_manager_headers(user_id: str) -> dict:
    """CompManager is an opaque identity; any operator id is valid."""
    return build_user_headers(user_id, "CompManager")


def make_rep_headers(rep_id: str) -> dict:
    """For Rep (identity-backed by the Rep entity). Pass the actual Rep.id
    whenever the call is ownership-gated (own assignments, credits, disputes,
    statements)."""
    return build_user_headers(rep_id, "Rep")
