"""Pre-built role headers for every role in the PRD (PRD §2.1).

PlatformAdmin and IncidentCommander are opaque roles — the shared constant is
the canonical form. ResponderUser is entity_backed:Responder — ownership-gated
calls MUST use make_responder_headers(responder_id) with the real Responder.id,
not the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — shared constant is canonical.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "incident_commander_headers": build_user_headers("test-commander-1", "IncidentCommander"),
    # entity_backed role — shared constant is a fallback for non-ownership tests
    # only (e.g. 400/404 probes). Ownership-gated calls must use the builder.
    "responder_user_headers": build_user_headers("test-responder-1", "ResponderUser"),
}


def make_responder_headers(responder_id: str) -> dict:
    """For ResponderUser (entity_backed:Responder). Pass the actual Responder.id
    as X-User-ID whenever the call is ownership-gated (acknowledge, action-item
    start/complete, or resolve by a responder)."""
    return build_user_headers(responder_id, "ResponderUser")
