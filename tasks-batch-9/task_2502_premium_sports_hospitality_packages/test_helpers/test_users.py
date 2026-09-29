"""Role header builders (PRD §2.1).

The six operator roles carry an opaque ``X-User-ID`` that is never compared to
any entity's ``id``, so each gets a stable constant identifier. The
``ClientPortalUser`` is different: its ``X-User-ID`` is the ``id`` of the
acting ``Client``, so it has no constant and must be built per client with
``make_client_portal_user_headers``.

The two commercial operators are deliberately distinct users because
publication is blocked when the acting user is the same user who priced the
package (§3.4 segregation of duties).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLIENT_PORTAL_USER,
    ROLE_CLIENT_SERVICE_AGENT,
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_COMMERCIAL_MANAGER,
    ROLE_FINANCE_CONTROLLER,
    ROLE_OPERATIONS_MANAGER,
    ROLE_RIGHTS_MANAGER,
)

# Opaque operator identifiers.
USER_RIGHTS_MANAGER = "u_rights"
USER_COMMERCIAL_MANAGER = "u_pricer"
USER_COMMERCIAL_DIRECTOR = "u_director"
USER_CLIENT_SERVICE_AGENT = "u_csa"
USER_OPERATIONS_MANAGER = "u_ops"
USER_FINANCE_CONTROLLER = "u_fin"

# A second commercial manager, for probes that need two distinct pricers.
USER_COMMERCIAL_MANAGER_ALT = "u_pricer_alt"
# A second director, for probes that need a non-pricing approver.
USER_COMMERCIAL_DIRECTOR_ALT = "u_director_alt"

RIGHTS_MANAGER = build_user_headers(USER_RIGHTS_MANAGER, ROLE_RIGHTS_MANAGER)
COMMERCIAL_MANAGER = build_user_headers(USER_COMMERCIAL_MANAGER, ROLE_COMMERCIAL_MANAGER)
COMMERCIAL_DIRECTOR = build_user_headers(USER_COMMERCIAL_DIRECTOR, ROLE_COMMERCIAL_DIRECTOR)
CLIENT_SERVICE_AGENT = build_user_headers(USER_CLIENT_SERVICE_AGENT, ROLE_CLIENT_SERVICE_AGENT)
OPERATIONS_MANAGER = build_user_headers(USER_OPERATIONS_MANAGER, ROLE_OPERATIONS_MANAGER)
FINANCE_CONTROLLER = build_user_headers(USER_FINANCE_CONTROLLER, ROLE_FINANCE_CONTROLLER)

# A CommercialDirector acting under the pricer's own identity, which is what
# makes an attempt to price and publish with one pair of hands observable.
COMMERCIAL_DIRECTOR_AS_PRICER = build_user_headers(
    USER_COMMERCIAL_MANAGER, ROLE_COMMERCIAL_DIRECTOR
)

COMMERCIAL_MANAGER_ALT = build_user_headers(
    USER_COMMERCIAL_MANAGER_ALT, ROLE_COMMERCIAL_MANAGER
)
COMMERCIAL_DIRECTOR_ALT = build_user_headers(
    USER_COMMERCIAL_DIRECTOR_ALT, ROLE_COMMERCIAL_DIRECTOR
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_RIGHTS_MANAGER: RIGHTS_MANAGER,
    ROLE_COMMERCIAL_MANAGER: COMMERCIAL_MANAGER,
    ROLE_COMMERCIAL_DIRECTOR: COMMERCIAL_DIRECTOR,
    ROLE_CLIENT_SERVICE_AGENT: CLIENT_SERVICE_AGENT,
    ROLE_OPERATIONS_MANAGER: OPERATIONS_MANAGER,
    ROLE_FINANCE_CONTROLLER: FINANCE_CONTROLLER,
}


def make_client_portal_user_headers(client_id: str) -> Dict[str, str]:
    """Headers for a ClientPortalUser acting as the given client.

    PRD §2.1: when ``X-User-Role`` is ``ClientPortalUser``, ``X-User-ID`` is the
    ``id`` of the acting ``Client``.
    """
    return build_user_headers(client_id, ROLE_CLIENT_PORTAL_USER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, for segregation and scope probes."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """A request that omits ``X-User-ID`` entirely (§2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """A request that omits ``X-User-Role`` entirely (§2.1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
