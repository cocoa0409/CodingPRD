"""Pre-built role headers for every role in the PRD.

Four roles (Petitioner, CourtExaminer, Judge, CourtClerk) carry an opaque
identity: X-User-ID is an operator string never tied to an entity. The shared
constants below are the canonical form for those roles.

The Fiduciary role is entity-backed: X-User-ID is the id of the acting Fiduciary
entity. Ownership-gated calls MUST use make_fiduciary_headers(fiduciary_id) with
the actual entity id; the shared constant is only a fallback for non-ownership
tests (e.g. a 403 role-rejection where no real fiduciary exists).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Fiduciary ownership.
TEST_USERS = {
    "petitioner_headers": build_user_headers("pet-1", "Petitioner"),
    "examiner_headers": build_user_headers("exam-1", "CourtExaminer"),
    "judge_headers": build_user_headers("judge-1", "Judge"),
    "clerk_headers": build_user_headers("clerk-1", "CourtClerk"),
    # entity_backed role: this shared constant is a fallback for non-ownership
    # tests only (e.g. role-rejection 403s). Real fiduciary calls thread the id.
    "fiduciary_headers": build_user_headers("fiduciary-fallback", "Fiduciary"),
}


# Per-instance builders.
def make_petitioner_headers(user_id: str) -> dict:
    """Petitioner (opaque). Pass a stable operator id so segregation-of-duties
    checks can compare it against the recorded petitioner_user_id."""
    return build_user_headers(user_id, "Petitioner")


def make_examiner_headers(user_id: str) -> dict:
    """CourtExaminer (opaque). Pass a stable operator id for segregation checks."""
    return build_user_headers(user_id, "CourtExaminer")


def make_judge_headers(user_id: str) -> dict:
    """Judge (opaque). Pass a stable operator id for segregation checks."""
    return build_user_headers(user_id, "Judge")


def make_clerk_headers(user_id: str) -> dict:
    """CourtClerk (opaque)."""
    return build_user_headers(user_id, "CourtClerk")


def make_fiduciary_headers(fiduciary_id: str) -> dict:
    """Fiduciary (entity_backed:Fiduciary). Pass the actual Fiduciary.id as the
    user id whenever the call is ownership-gated (bond post, inventory file,
    budget submit, expenditure create/disburse, accounting submit, care-plan)."""
    return build_user_headers(fiduciary_id, "Fiduciary")
