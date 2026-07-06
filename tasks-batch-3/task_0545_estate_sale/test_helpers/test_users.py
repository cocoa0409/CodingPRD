"""Pre-built role headers for every role in the Estate Sale PRD.

Four roles (PlatformAdmin, SaleManager, Appraiser, Cashier) carry an opaque
identity — the X-User-ID is an operator identifier not tied to any entity. The
Client role is entity-backed: its X-User-ID must equal the acting Client's id on
ownership-gated project transitions, so ownership-sensitive calls MUST use
make_client_headers(client_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "sale_manager_headers": build_user_headers("mgr-1", "SaleManager"),
    "appraiser_headers": build_user_headers("appr-1", "Appraiser"),
    "cashier_headers": build_user_headers("cashier-1", "Cashier"),
    # Client is entity-backed: this placeholder id equals no real Client, so it is
    # only valid for tests that expect an ownership rejection.
    "client_headers": build_user_headers("client-placeholder", "Client"),
}


# Per-instance builders. Opaque roles accept an explicit user_id so segregation-of-duties
# scenarios can pin distinct operator identities; the Client builder is mandatory for
# ownership-gated transitions.
def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_sale_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SaleManager")


def make_appraiser_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Appraiser")


def make_cashier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Cashier")


def make_client_headers(user_id: str) -> dict:
    """For the Client role (entity-backed). Pass the acting Client.id as user_id
    whenever the project transition is ownership-gated (COUNTERED / CONTRACTED)."""
    return build_user_headers(user_id, "Client")
