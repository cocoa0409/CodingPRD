"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (QCReviewer, PlatformAdmin) and for
# tests that don't exercise entity ownership (400/404/RBAC-denial scenarios).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "qc_headers": build_user_headers("test-qc-1", "QCReviewer"),
    # Fallbacks for entity_backed roles — use ONLY for non-ownership tests.
    "author_headers": build_user_headers("test-author-1", "Author"),
    "narrator_headers": build_user_headers("test-narrator-1", "Narrator"),
}


# Per-instance builders — required for every entity_backed role. Pass the actual
# entity id so ownership checks (PRD §2.1) resolve against a real record.
def make_author_headers(author_id: str) -> dict:
    """For Author (entity_backed:Author). Pass the acting Author.id."""
    return build_user_headers(author_id, "Author")


def make_narrator_headers(narrator_id: str) -> dict:
    """For Narrator (entity_backed:Narrator). Pass the acting Narrator.id."""
    return build_user_headers(narrator_id, "Narrator")


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


def qc_headers() -> dict:
    return TEST_USERS["qc_headers"]
