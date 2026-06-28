"""Pre-built role headers for every role in the PRD.

FranchiseAdmin, CenterDirector, and Instructor carry opaque X-User-ID values
that the server never compares to a persisted entity's id (PRD §2.1). Parent is
entity-backed: X-User-ID must equal the acting Family's id, and ownership checks
compare it to the resource's family_id. Use make_parent_headers(family_id) for
any ownership-gated Parent call.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# Parent ownership.
TEST_USERS = {
    "franchise_admin_headers": build_user_headers("admin-1", "FranchiseAdmin"),
    "center_director_headers": build_user_headers("director-1", "CenterDirector"),
    "instructor_headers": build_user_headers("instr-1", "Instructor"),
    # Parent shared constant: a fallback for non-ownership tests only (its id
    # equals no real Family, so any ownership check would reject it).
    "parent_headers": build_user_headers("parent-fallback", "Parent"),
}


def make_franchise_admin_headers(user_id: str = "admin-1") -> dict:
    """Headers for a FranchiseAdmin (opaque identity)."""
    return build_user_headers(user_id, "FranchiseAdmin")


def make_center_director_headers(user_id: str = "director-1") -> dict:
    """Headers for a CenterDirector (opaque identity)."""
    return build_user_headers(user_id, "CenterDirector")


def make_instructor_headers(user_id: str = "instr-1") -> dict:
    """Headers for an Instructor (opaque identity recorded as audit only)."""
    return build_user_headers(user_id, "Instructor")


def make_parent_headers(family_id: str) -> dict:
    """For Parent (entity_backed:Family). Pass the actual Family.id as user_id
    whenever the call is ownership-gated (e.g. paying own family's invoice)."""
    return build_user_headers(family_id, "Parent")
