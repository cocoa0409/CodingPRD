"""Pre-built role headers for every role in the PRD (§2.1).

Contestant and Judge are entity-backed roles: X-User-ID must equal the id of
the acting Contestant/Judge entity. Use the per-instance builders with the
real entity id for any ownership- or identity-gated call; the shared
constants are fallbacks for tests that do not exercise ownership
(401/403/404 paths, or opaque roles).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles (PRD §2.1: never compared to any persisted entity id).
    "committee_admin_headers": build_user_headers(
        "test-committee-admin-1", "CommitteeAdmin"
    ),
    "entry_office_headers": build_user_headers("test-entry-office-1", "EntryOffice"),
    "veterinarian_headers": build_user_headers("test-veterinarian-1", "Veterinarian"),
    "box_office_headers": build_user_headers("test-box-office-1", "BoxOffice"),
    # entity_backed fallbacks — NOT usable for ownership-gated calls.
    "contestant_headers": build_user_headers("test-contestant-1", "Contestant"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
}


def make_contestant_headers(user_id: str) -> dict:
    """Contestant is entity-backed: pass the actual Contestant.id as user_id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Contestant")


def make_judge_headers(user_id: str) -> dict:
    """Judge is entity-backed: pass the actual Judge.id as user_id whenever
    the call is identity-gated (result submission/amendment, PRD §3.4)."""
    return build_user_headers(user_id, "Judge")
