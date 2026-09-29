"""Identity headers for each role.

The five operator roles carry an opaque ``X-User-ID`` that the server never
compares to any entity id, so a shared constant per role is enough. A ``Patron``
header instead carries the id of the acting patron record, so it must be built
per patron with :func:`make_patron_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    AGENT_2_USER_ID,
    AGENT_USER_ID,
    APPROVER_USER_ID,
    GATE_OPERATOR_USER_ID,
    INVESTIGATOR_USER_ID,
)
from .types import Role

# ─── Opaque operator identities ───────────────────────────────────────────────

VENUE_ADMIN = build_user_headers(ADMIN_USER_ID, Role.VENUE_ADMIN)
BOX_OFFICE_AGENT = build_user_headers(AGENT_USER_ID, Role.BOX_OFFICE_AGENT)
#: A second box-office identity, for segregation-of-duties scenarios.
BOX_OFFICE_AGENT_2 = build_user_headers(AGENT_2_USER_ID, Role.BOX_OFFICE_AGENT)
TICKETING_APPROVER = build_user_headers(APPROVER_USER_ID, Role.TICKETING_APPROVER)
#: An approver acting under the submitting agent's identifier.
TICKETING_APPROVER_AS_AGENT = build_user_headers(AGENT_USER_ID, Role.TICKETING_APPROVER)
GATE_OPERATOR = build_user_headers(GATE_OPERATOR_USER_ID, Role.GATE_OPERATOR)
SECURITY_INVESTIGATOR = build_user_headers(INVESTIGATOR_USER_ID, Role.SECURITY_INVESTIGATOR)

#: One header set per role, keyed by the exact role spelling.
HEADERS_BY_ROLE = {
    Role.BOX_OFFICE_AGENT: BOX_OFFICE_AGENT,
    Role.TICKETING_APPROVER: TICKETING_APPROVER,
    Role.GATE_OPERATOR: GATE_OPERATOR,
    Role.SECURITY_INVESTIGATOR: SECURITY_INVESTIGATOR,
    Role.VENUE_ADMIN: VENUE_ADMIN,
}


# ─── Entity-backed patron identity ────────────────────────────────────────────


def make_patron_headers(patron_id: str) -> dict:
    """Headers for a `Patron` acting as the patron record ``patron_id``."""
    return build_user_headers(patron_id, Role.PATRON)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user id and role spelling."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str) -> dict:
    """Headers carrying only ``X-User-ID``, omitting ``X-User-Role``."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> dict:
    """Headers carrying only ``X-User-Role``, omitting ``X-User-ID``."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
