"""Pre-built role headers for every role in the PRD.

Three roles (ResearchManager, PanelOps, FieldCoordinator) are opaque operator
identities: X-User-ID is never compared to any entity id, so the shared
constant form is canonical for them.

The Panelist role is entity-backed: X-User-ID must equal the acting Panelist's
id whenever the call is ownership-gated (participation start/submit/abandon,
payout create/cancel, booking create/cancel). Use make_panelist_headers(id)
with the real Panelist.id in those cases. The shared TEST_USERS["panelist_headers"]
is a fallback only for non-ownership negative tests.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "research_manager_headers": build_user_headers("op-research-manager-1", "ResearchManager"),
    "panel_ops_headers": build_user_headers("op-panel-ops-1", "PanelOps"),
    "field_coordinator_headers": build_user_headers("op-field-coordinator-1", "FieldCoordinator"),
    # entity-backed fallback: only valid where ownership is NOT exercised.
    "panelist_headers": build_user_headers("op-panelist-fallback-1", "Panelist"),
}


def make_research_manager_headers(user_id: str = "op-research-manager-1") -> dict:
    return build_user_headers(user_id, "ResearchManager")


def make_panel_ops_headers(user_id: str = "op-panel-ops-1") -> dict:
    return build_user_headers(user_id, "PanelOps")


def make_field_coordinator_headers(user_id: str = "op-field-coordinator-1") -> dict:
    return build_user_headers(user_id, "FieldCoordinator")


def make_panelist_headers(user_id: str) -> dict:
    """For the entity-backed Panelist role. Pass the actual Panelist.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Panelist")
