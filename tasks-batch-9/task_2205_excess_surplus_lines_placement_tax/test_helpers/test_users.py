"""Role identities for the Surplus Lines Placement Tax API.

PRD 2.1 binds identity to entities differently by role. A `PlacementBroker`'s
`X-User-ID` is the `id` of the acting `Broker`, so broker headers must always
be minted per brokerage with :func:`make_placement_broker_headers`. The other
four roles carry opaque operator identifiers with no backing entity, so their
headers are fixed constants.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PLACEMENT_BROKER,
    ROLE_PLATFORM_ADMIN,
    ROLE_STATE_REGULATOR,
    ROLE_TAX_FILER,
)

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "pa-root"

COMPLIANCE_OFFICER_ANDERS_ID = "co-anders"
COMPLIANCE_OFFICER_BRIGID_ID = "co-brigid"

TAX_FILER_NINA_ID = "tf-nina"
TAX_FILER_OWEN_ID = "tf-owen"
TAX_FILER_OMAR_ID = "tf-omar"

STATE_REGULATOR_TX_ID = "sr-tx"
STATE_REGULATOR_CA_ID = "sr-ca"
STATE_REGULATOR_NV_ID = "sr-nv"
STATE_REGULATOR_GA_ID = "sr-ga"
STATE_REGULATOR_AZ_ID = "sr-az"

# ---------------------------------------------------------------------------
# Ready-made header dicts for the four opaque roles
# ---------------------------------------------------------------------------
PLATFORM_ADMIN = build_user_headers(PLATFORM_ADMIN_ID, ROLE_PLATFORM_ADMIN)

COMPLIANCE_OFFICER = build_user_headers(COMPLIANCE_OFFICER_ANDERS_ID, ROLE_COMPLIANCE_OFFICER)
COMPLIANCE_OFFICER_ANDERS = build_user_headers(
    COMPLIANCE_OFFICER_ANDERS_ID, ROLE_COMPLIANCE_OFFICER
)
COMPLIANCE_OFFICER_BRIGID = build_user_headers(
    COMPLIANCE_OFFICER_BRIGID_ID, ROLE_COMPLIANCE_OFFICER
)

TAX_FILER = build_user_headers(TAX_FILER_NINA_ID, ROLE_TAX_FILER)
TAX_FILER_NINA = build_user_headers(TAX_FILER_NINA_ID, ROLE_TAX_FILER)
TAX_FILER_OWEN = build_user_headers(TAX_FILER_OWEN_ID, ROLE_TAX_FILER)
TAX_FILER_OMAR = build_user_headers(TAX_FILER_OMAR_ID, ROLE_TAX_FILER)

STATE_REGULATOR = build_user_headers(STATE_REGULATOR_TX_ID, ROLE_STATE_REGULATOR)
STATE_REGULATOR_TX = build_user_headers(STATE_REGULATOR_TX_ID, ROLE_STATE_REGULATOR)
STATE_REGULATOR_CA = build_user_headers(STATE_REGULATOR_CA_ID, ROLE_STATE_REGULATOR)
STATE_REGULATOR_NV = build_user_headers(STATE_REGULATOR_NV_ID, ROLE_STATE_REGULATOR)
STATE_REGULATOR_GA = build_user_headers(STATE_REGULATOR_GA_ID, ROLE_STATE_REGULATOR)
STATE_REGULATOR_AZ = build_user_headers(STATE_REGULATOR_AZ_ID, ROLE_STATE_REGULATOR)

# Any of the five roles may read every GET endpoint and set the logical clock.
ANY_ROLE = PLATFORM_ADMIN


def make_placement_broker_headers(broker_id: str) -> Dict[str, str]:
    """Headers for a `PlacementBroker` acting as the brokerage `broker_id`."""
    return build_user_headers(broker_id, ROLE_PLACEMENT_BROKER)


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_tax_filer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TAX_FILER)


def make_state_regulator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_STATE_REGULATOR)


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user/role pair, for authentication and RBAC probes."""
    return build_user_headers(user_id, role)


# Headers for every role, keyed by role name. Used by RBAC sweeps that need
# to try an endpoint as each of the five roles in turn.
HEADERS_BY_ROLE = {
    ROLE_PLACEMENT_BROKER: build_user_headers("br-unowned", ROLE_PLACEMENT_BROKER),
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER_ANDERS,
    ROLE_TAX_FILER: TAX_FILER_NINA,
    ROLE_STATE_REGULATOR: STATE_REGULATOR_TX,
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN,
}
