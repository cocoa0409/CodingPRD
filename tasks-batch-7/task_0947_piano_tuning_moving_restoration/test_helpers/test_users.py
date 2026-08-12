"""Pre-built role headers for every role in the PRD.

Two of the six roles are entity-backed and their `X-User-ID` is compared to a real
row's id: `Technician` (compared to RouteDay.technician_id and
ServiceOrder.assigned_technician_id) and `Client` (compared to the addressed
resource's client_id).  Ownership-gated calls MUST use the per-instance builders
below with the real entity id; the shared constants are only safe for opaque roles
and for calls that never reach an ownership check.

Four operations additionally demand a distinct operator identity (milestone
release, claim adjudication, agreement creation, sale recording).  The
`make_shop_manager_headers` / `make_showroom_agent_headers` builders exist so that
tests can supply genuinely different `X-User-ID` values for the two sides of each
segregation-of-duties pair.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles, and calls that do not exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-ops-1", "PlatformAdmin"),
    "shop_manager_headers": build_user_headers("mgr-shop-1", "ShopManager"),
    "move_coordinator_headers": build_user_headers("coord-move-1", "MoveCoordinator"),
    "showroom_agent_headers": build_user_headers("agent-showroom-1", "ShowroomAgent"),
    # Entity-backed roles: fallbacks for tests that never reach an ownership check.
    "technician_headers": build_user_headers("tech-unbound-1", "Technician"),
    "client_headers": build_user_headers("client-unbound-1", "Client"),
}


# --- Per-instance builders for the two entity-backed roles (mandatory) --------
def make_technician_headers(technician_id: str) -> dict:
    """For the Technician role. Pass the acting Technician row's id."""
    return build_user_headers(technician_id, "Technician")


def make_client_headers(client_id: str) -> dict:
    """For the Client role. Pass the acting Client row's id."""
    return build_user_headers(client_id, "Client")


# --- Per-instance builders for the opaque operator identities ----------------
def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_shop_manager_headers(user_id: str) -> dict:
    """Distinct ShopManager operator identity (milestone release vs adjudication)."""
    return build_user_headers(user_id, "ShopManager")


def make_move_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MoveCoordinator")


def make_showroom_agent_headers(user_id: str) -> dict:
    """Distinct ShowroomAgent operator identity (agreement creation vs sale)."""
    return build_user_headers(user_id, "ShowroomAgent")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary (user_id, role) pair — used by the role-rejection tests."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = "somebody") -> dict:
    """Headers carrying no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> dict:
    """Headers carrying no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
