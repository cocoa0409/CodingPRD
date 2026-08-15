"""Pre-built role headers for every role in the PRD (§2.1).

`Entrant` and `Judge` are entity-backed roles: when a call is ownership-gated
(an entry's `entrant_id`, an assignment's `judge_id`, a declaration's judge),
the caller MUST build headers with the actual entity id via
`make_entrant_headers(entrant["id"])` / `make_judge_headers(judge["id"])`.
The shared constants for those two roles are fallbacks for tests that do not
exercise ownership (for example 400/404 rejection paths).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: the canonical form (PRD §2.1 — not tied to any entity).
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "vendor_headers": build_user_headers("test-vendor-1", "FulfillmentVendor"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # Entity-backed roles: fallback only for non-ownership-gated calls.
    "entrant_headers": build_user_headers("test-entrant-1", "Entrant"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
}


def make_entrant_headers(user_id: str) -> dict:
    """Entrant is entity-backed (PRD §2.1): pass the acting Entrant.id whenever
    the call is ownership-gated (entries, materials, invoices, finalists,
    appeals)."""
    return build_user_headers(user_id, "Entrant")


def make_judge_headers(user_id: str) -> dict:
    """Judge is entity-backed (PRD §2.1): pass the acting Judge.id whenever the
    call is ownership-gated (accept/decline, assignment confirm/recuse, score
    create/submit, declarations)."""
    return build_user_headers(user_id, "Judge")
