"""
Auth identities for the five PRD roles.

Four roles are opaque operator identities: any stable string is a valid
``X-User-ID`` for them, so the suite pins one identity per role plus three
distinct GroupSalesAgent identities because the four-eyes rule on
``confirm-definite`` compares the signer's id against the block creator's id.

The fifth role, ``Guest``, is entity-backed: its ``X-User-ID`` must be a real
``Guest.id``, so guest headers are minted per fixture through
``make_guest_headers``.
"""

from prd_bench_local_runner.testing import build_user_headers

# --- Opaque operator identities -------------------------------------------
REVENUE_MANAGER_USER_ID = "rm-001"
RESERVATION_AGENT_USER_ID = "ra-001"
GROUP_SALES_AGENT_USER_ID = "gsa-001"
GROUP_SALES_AGENT_2_USER_ID = "gsa-002"
GROUP_SALES_AGENT_3_USER_ID = "gsa-003"
PORT_OPS_COORDINATOR_USER_ID = "poc-001"

REVENUE_MANAGER = build_user_headers(REVENUE_MANAGER_USER_ID, "RevenueManager")
RESERVATION_AGENT = build_user_headers(RESERVATION_AGENT_USER_ID, "ReservationAgent")
GROUP_SALES_AGENT = build_user_headers(GROUP_SALES_AGENT_USER_ID, "GroupSalesAgent")
GROUP_SALES_AGENT_2 = build_user_headers(GROUP_SALES_AGENT_2_USER_ID, "GroupSalesAgent")
GROUP_SALES_AGENT_3 = build_user_headers(GROUP_SALES_AGENT_3_USER_ID, "GroupSalesAgent")
PORT_OPS_COORDINATOR = build_user_headers(
    PORT_OPS_COORDINATOR_USER_ID, "PortOpsCoordinator"
)

TEST_USERS = {
    "RevenueManager": REVENUE_MANAGER,
    "ReservationAgent": RESERVATION_AGENT,
    "GroupSalesAgent": GROUP_SALES_AGENT,
    "GroupSalesAgent2": GROUP_SALES_AGENT_2,
    "GroupSalesAgent3": GROUP_SALES_AGENT_3,
    "PortOpsCoordinator": PORT_OPS_COORDINATOR,
}


def make_guest_headers(guest_id: str) -> dict:
    """Headers for the entity-backed Guest role; X-User-ID is a Guest.id."""
    return build_user_headers(guest_id, "Guest")


def headers_with_role(role: str) -> dict:
    """Headers carrying a caller identity and an arbitrary role string."""
    return build_user_headers("probe-001", role)


# Header dicts that violate the authentication tier of PRD §2.10 priority 1-2.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS = {
    "X-User-ID": REVENUE_MANAGER_USER_ID,
    "Content-Type": "application/json",
}
MISSING_USER_HEADERS = {
    "X-User-Role": "RevenueManager",
    "Content-Type": "application/json",
}
EMPTY_USER_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": "RevenueManager",
    "Content-Type": "application/json",
}
EMPTY_ROLE_HEADERS = {
    "X-User-ID": REVENUE_MANAGER_USER_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = build_user_headers("who-001", "PortAuthorityInspector")
