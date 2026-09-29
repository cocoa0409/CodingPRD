"""Pre-built role headers for every role the PRD recognises.

`GrowerManager`, `IrrigationTech` and `QualityInspector` are opaque roles: their
`X-User-ID` is an operator identifier that is never resolved against a stored row,
so the shared constants below are the canonical form for them.

`IPMScout`, `IPMCoordinator` and `HarvestSupervisor` are entity-backed: their
`X-User-ID` must be the `id` of the acting worker row. Every ownership-gated call
by one of those three roles MUST use the matching `make_*_headers(worker_id)`
builder with the real worker id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used by the three roles that are never resolved
# against a worker row.
GROWER_MANAGER_USER_ID = "gm-1"
IRRIGATION_TECH_USER_ID = "it-1"
QUALITY_INSPECTOR_USER_ID = "qi-1"
SECOND_QUALITY_INSPECTOR_USER_ID = "qi-2"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "grower_manager_headers": build_user_headers(
        GROWER_MANAGER_USER_ID, "GrowerManager"
    ),
    "irrigation_tech_headers": build_user_headers(
        IRRIGATION_TECH_USER_ID, "IrrigationTech"
    ),
    "quality_inspector_headers": build_user_headers(
        QUALITY_INSPECTOR_USER_ID, "QualityInspector"
    ),
    "second_quality_inspector_headers": build_user_headers(
        SECOND_QUALITY_INSPECTOR_USER_ID, "QualityInspector"
    ),
    # Entity-backed roles — these shared constants deliberately do NOT resolve to
    # any worker row. They are only for tests that assert role authorisation or
    # actor resolution failure, never for ownership-gated success paths.
    "ipm_scout_headers": build_user_headers(
        "33333333-3333-4333-8333-333333333333", "IPMScout"
    ),
    "ipm_coordinator_headers": build_user_headers(
        "44444444-4444-4444-8444-444444444444", "IPMCoordinator"
    ),
    "harvest_supervisor_headers": build_user_headers(
        "55555555-5555-4555-8555-555555555555", "HarvestSupervisor"
    ),
}

UNKNOWN_WORKER_USER_ID = "33333333-3333-4333-8333-333333333333"


def make_grower_manager_headers(user_id: str = GROWER_MANAGER_USER_ID) -> dict:
    """GrowerManager is opaque; any non-empty operator identifier is acceptable."""
    return build_user_headers(user_id, "GrowerManager")


def make_irrigation_tech_headers(user_id: str = IRRIGATION_TECH_USER_ID) -> dict:
    """IrrigationTech is opaque; any non-empty operator identifier is acceptable."""
    return build_user_headers(user_id, "IrrigationTech")


def make_quality_inspector_headers(user_id: str = QUALITY_INSPECTOR_USER_ID) -> dict:
    """QualityInspector is opaque; the identifier is recorded but never resolved."""
    return build_user_headers(user_id, "QualityInspector")


def make_ipm_scout_headers(user_id: str) -> dict:
    """IPMScout is entity-backed: pass the id of a worker whose skill is SCOUT."""
    return build_user_headers(user_id, "IPMScout")


def make_ipm_coordinator_headers(user_id: str) -> dict:
    """IPMCoordinator is entity-backed: pass the id of a worker whose skill is SCOUT."""
    return build_user_headers(user_id, "IPMCoordinator")


def make_harvest_supervisor_headers(user_id: str) -> dict:
    """HarvestSupervisor is entity-backed: pass the id of a worker whose skill is HARVEST."""
    return build_user_headers(user_id, "HarvestSupervisor")


def headers_without_user_id(role: str) -> dict:
    """Headers carrying a role but an empty X-User-ID, for authentication tests."""
    return build_user_headers("", role)


def headers_without_role(user_id: str = GROWER_MANAGER_USER_ID) -> dict:
    """Headers carrying a user id but an empty X-User-Role, for authentication tests."""
    return build_user_headers(user_id, "")
