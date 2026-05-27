"""Pre-built role headers for every role declared in the PRD (§2.1).

PRD §2.1: every request must carry X-User-ID and X-User-Role.
- PlanAdmin: X-User-ID is opaque (no entity ownership check).
- Custodian: X-User-ID is opaque (no entity ownership check).
- Participant: X-User-ID is the Participant entity's id; ownership-gated calls
  compare the resource's participant foreign key to this value.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (PlanAdmin, Custodian) and for
# tests that do NOT exercise Participant ownership (e.g., 401-on-missing-headers).
TEST_USERS = {
    "plan_admin_headers": build_user_headers("test-plan-admin-1", "PlanAdmin"),
    "custodian_headers": build_user_headers("test-custodian-1", "Custodian"),
    # Bare-bones fallback — only valid for tests where ownership is NOT exercised
    # (e.g., role-denial 403 tests that do not hit any Participant-owned resource).
    "participant_headers_fallback": build_user_headers(
        "00000000-0000-0000-0000-000000000001", "Participant"
    ),
}


def make_participant_headers(participant_id: str) -> dict:
    """For Participant role (entity_backed:Participant per PRD §2.1).

    Pass the actual Participant.id whenever the call is ownership-gated, so
    the resource's participant_id matches X-User-ID and the ownership check
    passes.
    """
    return build_user_headers(participant_id, "Participant")


def missing_headers() -> dict:
    """Strip X-User-* headers entirely (PRD §2.1: must return ERR_UNAUTHENTICATED).

    Keep Content-Type so the request body still parses, but omit both auth
    headers so the server's auth check fires.
    """
    return {"Content-Type": "application/json"}
