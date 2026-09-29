"""Fixed caller identities, one per role, plus helpers for extra identities.

Five of the six roles are opaque: any stable identifier works. ``Licensee`` is
backed by a ``Client`` row, so a licensee's ``X-User-ID`` must be the client's
identifier and cannot be a fixed constant. Use ``make_licensee_headers`` with
the identifier of the client that was actually created.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque caller identifiers
SALES_MANAGER_ID = "sales-manager-1"
EVENT_SERVICES_MANAGER_ID = "event-services-1"
SETTLEMENT_ANALYST_ID = "analyst-1"
SETTLEMENT_ANALYST_TWO_ID = "analyst-2"
FACILITIES_PLANNER_ID = "planner-1"
VENUE_ADMIN_ID = "venue-admin-1"

# Aliases used by settlement segregation-of-duties scenarios
ANALYST_ONE = SETTLEMENT_ANALYST_ID
ANALYST_TWO = SETTLEMENT_ANALYST_TWO_ID


TEST_USERS: Dict[str, Dict[str, str]] = {
    "sales_manager": build_user_headers(SALES_MANAGER_ID, UserRole.SALES_MANAGER.value),
    "event_services_manager": build_user_headers(
        EVENT_SERVICES_MANAGER_ID, UserRole.EVENT_SERVICES_MANAGER.value
    ),
    "settlement_analyst": build_user_headers(
        SETTLEMENT_ANALYST_ID, UserRole.SETTLEMENT_ANALYST.value
    ),
    "settlement_analyst_two": build_user_headers(
        SETTLEMENT_ANALYST_TWO_ID, UserRole.SETTLEMENT_ANALYST.value
    ),
    "facilities_planner": build_user_headers(
        FACILITIES_PLANNER_ID, UserRole.FACILITIES_PLANNER.value
    ),
    "venue_admin": build_user_headers(VENUE_ADMIN_ID, UserRole.VENUE_ADMIN.value),
}


def make_licensee_headers(client_id: str) -> Dict[str, str]:
    """Headers for the licensee whose identity is the given client row."""
    return build_user_headers(client_id, UserRole.LICENSEE.value)


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for a settlement analyst with an arbitrary caller identifier."""
    return build_user_headers(user_id, UserRole.SETTLEMENT_ANALYST.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary caller identifier and role string."""
    return build_user_headers(user_id, role)


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
