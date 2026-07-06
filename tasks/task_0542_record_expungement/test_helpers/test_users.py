"""Pre-built role headers for every role in the PRD.

Only ``Petitioner`` is entity-backed (its ``X-User-ID`` must equal the acting
Petitioner entity's ``id`` for ownership-gated calls); ``Clerk``, ``Agency`` and
``Judge`` carry opaque operator identifiers not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Clerk/Agency/Judge) and for tests that
# do not exercise Petitioner ownership.
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-001", "Clerk"),
    "agency_headers": build_user_headers("agency-001", "Agency"),
    "judge_headers": build_user_headers("judge-001", "Judge"),
    # Fallback only: for ownership-gated Petitioner calls use make_petitioner_headers(id).
    "petitioner_headers": build_user_headers("petitioner-001", "Petitioner"),
}


def make_petitioner_headers(user_id: str) -> dict:
    """For the Petitioner role (entity_backed:Petitioner). Pass the acting
    Petitioner entity's ``id`` as ``user_id`` whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Petitioner")


def make_clerk_headers(user_id: str = "clerk-001") -> dict:
    return build_user_headers(user_id, "Clerk")


def make_agency_headers(user_id: str = "agency-001") -> dict:
    return build_user_headers(user_id, "Agency")


def make_judge_headers(user_id: str = "judge-001") -> dict:
    return build_user_headers(user_id, "Judge")
