"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque roles — safe anywhere, since their
# X-User-ID is never compared against an entity id.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "DistrictProgramAdmin"),
    "claims_headers": build_user_headers("claims-1", "ClaimsCoordinator"),
    "auditor_headers": build_user_headers("aud-1", "StateGrantAuditor"),
    # Fallbacks for entity-backed roles: usable ONLY where the call is not
    # ownership-gated (e.g. shared GET reads).
    "farm_manager_headers": build_user_headers("test-farm-1", "FarmManager"),
    "kitchen_manager_headers": build_user_headers("test-kitchen-1", "KitchenManager"),
}


def make_farm_manager_headers(farm_id: str) -> dict:
    """FarmManager is entity-backed by Farm: pass the real Farm.id whenever the
    call is ownership-gated (documents, offerings, sign, deliveries, invoices)."""
    return build_user_headers(farm_id, "FarmManager")


def make_kitchen_manager_headers(kitchen_id: str) -> dict:
    """KitchenManager is entity-backed by Kitchen: pass the real Kitchen.id
    whenever the call is ownership-gated (windows, check-in, accept, reject)."""
    return build_user_headers(kitchen_id, "KitchenManager")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "DistrictProgramAdmin")


def make_claims_coordinator_headers(user_id: str = "claims-1") -> dict:
    return build_user_headers(user_id, "ClaimsCoordinator")


def make_auditor_headers(user_id: str = "aud-1") -> dict:
    return build_user_headers(user_id, "StateGrantAuditor")
