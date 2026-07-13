"""Pre-built role headers for every role in the PRD (§2.1).

RinkManager and FrontDesk carry opaque operator identifiers not tied to any
entity, so a shared constant is the canonical form. Skater is entity-backed:
its X-User-ID must equal the acting skater's id, so ownership-gated calls MUST
use make_skater_headers(skater_id) with the real skater id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "rink_manager_headers": build_user_headers("test-rink-manager-1", "RinkManager"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    # Skater is entity_backed; this shared constant is a fallback for non-ownership
    # tests only (e.g. 401/404 checks). Ownership-gated calls use the builder below.
    "skater_headers": build_user_headers("test-skater-1", "Skater"),
}


def make_skater_headers(user_id: str) -> dict:
    """For the Skater role (entity_backed:Skater). Pass the actual Skater.id as
    user_id whenever the call is ownership-gated (act on one's own resource)."""
    return build_user_headers(user_id, "Skater")
