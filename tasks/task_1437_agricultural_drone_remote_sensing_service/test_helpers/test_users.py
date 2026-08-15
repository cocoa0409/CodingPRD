"""Pre-built role headers for every role in the PRD (section 2.1).

OpsAdmin, FlightCoordinator, ClaimsAdjuster and ProcessingEngine are opaque:
their X-User-ID is an operator identifier never compared to any entity id, so
the shared constants are the canonical form.

RemotePilot, Agronomist and Grower are entity-backed: ownership checks compare
X-User-ID to a PilotProfile.id / Grower.id, so callers on ownership-gated
endpoints MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical form.
    "ops_admin_headers": build_user_headers("ops-admin-1", "OpsAdmin"),
    "flight_coordinator_headers": build_user_headers("fc-1", "FlightCoordinator"),
    "claims_adjuster_headers": build_user_headers("adjuster-1", "ClaimsAdjuster"),
    "processing_engine_headers": build_user_headers("proc-eng-1", "ProcessingEngine"),
    # Entity-backed roles — fallback constants for non-ownership calls only.
    "remote_pilot_headers": build_user_headers("pilot-unbound", "RemotePilot"),
    "agronomist_headers": build_user_headers("agronomist-unbound", "Agronomist"),
    "grower_headers": build_user_headers("grower-unbound", "Grower"),
}


def make_pilot_headers(user_id: str) -> dict:
    """RemotePilot is entity-backed: pass the acting PilotProfile.id whenever
    the call is ownership-gated (launch / capture / abort-weather)."""
    return build_user_headers(user_id, "RemotePilot")


def make_agronomist_headers(user_id: str) -> dict:
    """Agronomist is entity-backed (a PilotProfile.id): pass the reviewing
    pilot's id for claim / review / release calls."""
    return build_user_headers(user_id, "Agronomist")


def make_grower_headers(user_id: str) -> dict:
    """Grower is entity-backed: pass the acting Grower.id for claims and any
    ownership-scoped reads."""
    return build_user_headers(user_id, "Grower")
