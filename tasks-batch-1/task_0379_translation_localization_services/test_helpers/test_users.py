"""Pre-built role headers for every role in the PRD (§2.1).

Two operations roles (ProjectManager, AccountsReceivable) are opaque identities:
their X-User-ID is not tied to any persisted entity, so the shared constant is the
canonical form.

Three roles are entity-backed:
  - Client      -> X-User-ID is the acting Client.id
  - Translator  -> X-User-ID is the acting Linguist.id
  - Reviewer    -> X-User-ID is the acting Linguist.id
For these, ownership-gated calls MUST use the per-instance builder with the actual
entity id; the shared constant is only a fallback for non-ownership tests
(e.g. 400-on-bad-payload, 403-on-forbidden-role).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operations roles — shared constant is canonical.
    "pm_headers": build_user_headers("test-pm-1", "ProjectManager"),
    "ar_headers": build_user_headers("test-ar-1", "AccountsReceivable"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "translator_headers": build_user_headers("test-translator-1", "Translator"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
}


# ─── Per-instance builders for entity-backed roles ────
def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id whenever the
    call is ownership-gated (e.g. approving one's own project)."""
    return build_user_headers(client_id, "Client")


def make_translator_headers(linguist_id: str) -> dict:
    """For Translator (entity_backed:Linguist). Pass the actual Linguist.id whenever
    the call is ownership-gated (accept/decline/submit-translation on own work)."""
    return build_user_headers(linguist_id, "Translator")


def make_reviewer_headers(linguist_id: str) -> dict:
    """For Reviewer (entity_backed:Linguist). Pass the actual Linguist.id whenever
    the call is ownership-gated (accept/decline/file-qa-report on own work)."""
    return build_user_headers(linguist_id, "Reviewer")
