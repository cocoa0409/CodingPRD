"""Request identities for the eight roles PRD.md section 2.1 declares.

PRD.md splits the roles into two kinds:

* **Opaque identities** — ``PlantAdmin``, ``LogisticsPlanner`` and
  ``WarrantyAgent``. ``X-User-ID`` is any non-empty string; the service never
  resolves it to a stored row. These roles can therefore use the shared
  constants in ``TEST_USERS`` directly.
* **Entity-backed identities** — ``ResinTechnician``, ``MoldingOperator``,
  ``AssemblyTechnician`` and ``QualityInspector`` must each carry the id of a
  real ``Technician`` row whose ``role_code`` matches the asserted role, and
  ``Customer`` must carry the id of a real ``Customer`` row. Because every test
  starts against an empty database, those ids cannot be hardcoded: mint the row
  first, then build headers from the id it returns with the matching
  ``make_*_headers`` builder below.

The ``TEST_USERS`` entries for the five entity-backed roles hold deliberately
unresolvable identifiers. They exist only for negative tests that need a
well-formed header pair whose identity does not resolve; using one on a happy
path is a guaranteed identity failure, not a shortcut.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ASSEMBLY_TECHNICIAN,
    ROLE_CUSTOMER,
    ROLE_LOGISTICS_PLANNER,
    ROLE_MOLDING_OPERATOR,
    ROLE_PLANT_ADMIN,
    ROLE_QUALITY_INSPECTOR,
    ROLE_RESIN_TECHNICIAN,
    ROLE_WARRANTY_AGENT,
)
from .types import Headers

# Opaque identifiers. Any non-empty string is acceptable for these three roles.
PLANT_ADMIN_USER_ID = "admin-1"
LOGISTICS_PLANNER_USER_ID = "planner-1"
WARRANTY_AGENT_USER_ID = "agent-1"

# Well-formed but unresolvable identifiers, for identity-failure tests only.
UNRESOLVABLE_TECHNICIAN_ID = "00000000-0000-0000-0000-0000000000ff"
UNRESOLVABLE_CUSTOMER_ID = "00000000-0000-0000-0000-0000000000fe"


def make_plant_admin_headers(user_id: str = PLANT_ADMIN_USER_ID) -> Headers:
    """Headers for the PlantAdmin role; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_PLANT_ADMIN)


def make_logistics_planner_headers(
    user_id: str = LOGISTICS_PLANNER_USER_ID,
) -> Headers:
    """Headers for the LogisticsPlanner role; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_LOGISTICS_PLANNER)


def make_warranty_agent_headers(user_id: str = WARRANTY_AGENT_USER_ID) -> Headers:
    """Headers for the WarrantyAgent role; the identifier is opaque."""
    return build_user_headers(user_id, ROLE_WARRANTY_AGENT)


def make_resin_technician_headers(user_id: str) -> Headers:
    """Headers for a ResinTechnician; ``user_id`` must be a RESIN_TECH row id."""
    return build_user_headers(user_id, ROLE_RESIN_TECHNICIAN)


def make_molding_operator_headers(user_id: str) -> Headers:
    """Headers for a MoldingOperator; ``user_id`` must be a MOLDING_OPERATOR row id."""
    return build_user_headers(user_id, ROLE_MOLDING_OPERATOR)


def make_assembly_technician_headers(user_id: str) -> Headers:
    """Headers for an AssemblyTechnician; ``user_id`` must be an ASSEMBLY_TECH row id."""
    return build_user_headers(user_id, ROLE_ASSEMBLY_TECHNICIAN)


def make_quality_inspector_headers(user_id: str) -> Headers:
    """Headers for a QualityInspector; ``user_id`` must be a QUALITY_INSPECTOR row id."""
    return build_user_headers(user_id, ROLE_QUALITY_INSPECTOR)


def make_customer_headers(user_id: str) -> Headers:
    """Headers for a Customer; ``user_id`` must be a real Customer row id."""
    return build_user_headers(user_id, ROLE_CUSTOMER)


# role_code -> the builder that mints headers for that shop-floor role.
TECHNICIAN_HEADER_BUILDERS = {
    "RESIN_TECH": make_resin_technician_headers,
    "MOLDING_OPERATOR": make_molding_operator_headers,
    "ASSEMBLY_TECH": make_assembly_technician_headers,
    "QUALITY_INSPECTOR": make_quality_inspector_headers,
}

TEST_USERS: dict[str, Headers] = {
    ROLE_PLANT_ADMIN: make_plant_admin_headers(),
    ROLE_LOGISTICS_PLANNER: make_logistics_planner_headers(),
    ROLE_WARRANTY_AGENT: make_warranty_agent_headers(),
    # The five entries below do not resolve; see the module docstring.
    ROLE_RESIN_TECHNICIAN: make_resin_technician_headers(UNRESOLVABLE_TECHNICIAN_ID),
    ROLE_MOLDING_OPERATOR: make_molding_operator_headers(UNRESOLVABLE_TECHNICIAN_ID),
    ROLE_ASSEMBLY_TECHNICIAN: make_assembly_technician_headers(
        UNRESOLVABLE_TECHNICIAN_ID
    ),
    ROLE_QUALITY_INSPECTOR: make_quality_inspector_headers(UNRESOLVABLE_TECHNICIAN_ID),
    ROLE_CUSTOMER: make_customer_headers(UNRESOLVABLE_CUSTOMER_ID),
}

# Convenient aliases for the three roles that need no setup at all.
ADMIN_HEADERS: Headers = TEST_USERS[ROLE_PLANT_ADMIN]
PLANNER_HEADERS: Headers = TEST_USERS[ROLE_LOGISTICS_PLANNER]
AGENT_HEADERS: Headers = TEST_USERS[ROLE_WARRANTY_AGENT]

# Headers with a valid role but an identity that resolves to nothing.
NO_AUTH_HEADERS: Headers = {}
