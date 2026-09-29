"""Actor identities and the headers that carry them.

Every request must carry ``X-User-ID``, identifying the actor, and
``X-User-Role``, naming the capability set the actor is exercising.

For the six staff roles ``X-User-ID`` is an opaque operator identifier that is
not tied to any persisted entity, so the suite uses stable readable operator
identifiers and asserts on them wherever a workflow attributes an action to a
person. For the ``Customer`` role ``X-User-ID`` is the ``id`` of the acting
customer record, so those headers must always be built from a live customer id.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import Role

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------

ADMIN_USER_ID = "u_admin_1"
OFFICER_USER_ID = "u_officer_1"
MANAGER_USER_ID = "u_manager_1"
SALES_USER_ID = "u_sales_1"
COLLECTOR_USER_ID = "u_collector_1"
TECH_USER_ID = "u_tech_1"

#: An operator who wears two hats: it approves a verification and then attempts
#: the repossession, which is exactly what segregation of duties forbids.
DUAL_ROLE_USER_ID = "u_dual_1"


# ---------------------------------------------------------------------------
# Staff header builders
# ---------------------------------------------------------------------------


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for the configuration and break-glass role."""
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


def make_officer_headers(user_id: str = OFFICER_USER_ID) -> Dict[str, str]:
    """Headers for the role that approves or rejects customer verification."""
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER)


def make_manager_headers(user_id: str = MANAGER_USER_ID) -> Dict[str, str]:
    """Headers for the role that owns store operations and the day-close."""
    return build_user_headers(user_id, Role.STORE_MANAGER)


def make_sales_headers(user_id: str = SALES_USER_ID) -> Dict[str, str]:
    """Headers for the front counter."""
    return build_user_headers(user_id, Role.SALES_ASSOCIATE)


def make_collector_headers(user_id: str = COLLECTOR_USER_ID) -> Dict[str, str]:
    """Headers for the role that works delinquent accounts only."""
    return build_user_headers(user_id, Role.COLLECTIONS_AGENT)


def make_technician_headers(user_id: str = TECH_USER_ID) -> Dict[str, str]:
    """Headers for the field and bay role."""
    return build_user_headers(user_id, Role.SERVICE_TECHNICIAN)


# ---------------------------------------------------------------------------
# Renter header builder
# ---------------------------------------------------------------------------


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """Headers for the renter; ``X-User-ID`` must be the customer's own ``id``."""
    return build_user_headers(customer_id, Role.CUSTOMER)


# ---------------------------------------------------------------------------
# Ready-made staff headers for the common case
# ---------------------------------------------------------------------------

ADMIN = make_admin_headers()
OFFICER = make_officer_headers()
MANAGER = make_manager_headers()
SALES = make_sales_headers()
COLLECTOR = make_collector_headers()
TECHNICIAN = make_technician_headers()

#: Keyed by role name, for tests that walk several roles over one operation.
STAFF_HEADERS: Dict[str, Dict[str, str]] = {
    Role.PLATFORM_ADMIN: ADMIN,
    Role.COMPLIANCE_OFFICER: OFFICER,
    Role.STORE_MANAGER: MANAGER,
    Role.SALES_ASSOCIATE: SALES,
    Role.COLLECTIONS_AGENT: COLLECTOR,
    Role.SERVICE_TECHNICIAN: TECHNICIAN,
}
