"""Pre-built role headers for every role in the PRD.

RmaAdmin is an opaque operator identity — its X-User-ID is not compared against
any entity id, so a shared constant is the canonical form for it.

Agent and LossAdjuster are both entity_backed:Agent — their X-User-ID must equal
the id of a real Agent entity for ownership / assignment / segregation checks to
pass. Use the per-instance builders (make_agent_headers / make_lossadjuster_headers)
with the actual Agent.id whenever a call is ownership-gated. The shared constants
are only a fallback for tests that never exercise ownership (e.g. 403 / 401 / 422
on a bad payload, or GET-only reads).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque operator role — shared constant is canonical.
    "rma_admin_headers": build_user_headers("test-rma-admin-1", "RmaAdmin"),
    # entity_backed roles — shared constants are non-ownership fallbacks only.
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "loss_adjuster_headers": build_user_headers("test-adjuster-1", "LossAdjuster"),
}


def make_rma_admin_headers(user_id: str = "test-rma-admin-1") -> dict:
    """RmaAdmin (opaque). user_id is recorded but not compared to any entity id."""
    return build_user_headers(user_id, "RmaAdmin")


def make_agent_headers(user_id: str) -> dict:
    """For Agent (entity_backed:Agent). Pass the acting Agent entity's id as user_id
    whenever the call is ownership-gated (selling agent_id checks)."""
    return build_user_headers(user_id, "Agent")


def make_lossadjuster_headers(user_id: str) -> dict:
    """For LossAdjuster (entity_backed:Agent). Pass the adjuster Agent entity's id as
    user_id whenever the call is assignment- or segregation-gated."""
    return build_user_headers(user_id, "LossAdjuster")
