"""Pre-built auth headers per role (PRD §2.1).

`ArtisticDirector`, `RegistrarStaff` and `FinanceOfficer` carry an opaque
operator identifier, so a module-level constant is enough. `Guardian` and
`Panelist` are entity-backed — their `X-User-ID` must be the acting musician's
or adjudicator's real `id` — so those headers are built per test from a live
entity id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers (PRD §2.1: "an opaque operator identifier not
# tied to any persisted entity").
DIRECTOR_USER_ID = "director-001"
DIRECTOR_USER_ID_2 = "director-002"
REGISTRAR_USER_ID = "registrar-001"
REGISTRAR_USER_ID_2 = "registrar-002"
FINANCE_USER_ID = "finance-001"
FINANCE_USER_ID_2 = "finance-002"

DIRECTOR_HEADERS = build_user_headers(DIRECTOR_USER_ID, UserRole.ARTISTIC_DIRECTOR.value)
DIRECTOR_HEADERS_2 = build_user_headers(
    DIRECTOR_USER_ID_2, UserRole.ARTISTIC_DIRECTOR.value
)
REGISTRAR_HEADERS = build_user_headers(REGISTRAR_USER_ID, UserRole.REGISTRAR_STAFF.value)
REGISTRAR_HEADERS_2 = build_user_headers(
    REGISTRAR_USER_ID_2, UserRole.REGISTRAR_STAFF.value
)
FINANCE_HEADERS = build_user_headers(FINANCE_USER_ID, UserRole.FINANCE_OFFICER.value)
FINANCE_HEADERS_2 = build_user_headers(FINANCE_USER_ID_2, UserRole.FINANCE_OFFICER.value)


def guardian_headers(member_id: str) -> Dict[str, str]:
    """Guardian headers whose `X-User-ID` is the acting musician's `id`."""
    return build_user_headers(member_id, UserRole.GUARDIAN.value)


def panelist_headers(panelist_id: str) -> Dict[str, str]:
    """Panelist headers whose `X-User-ID` is the acting adjudicator's `id`."""
    return build_user_headers(panelist_id, UserRole.PANELIST.value)


def headers_for_role(role: str, user_id: str = "opaque-operator") -> Dict[str, str]:
    """Headers for an arbitrary role string, useful for authorization sweeps."""
    return build_user_headers(user_id, role)


# Headers that omit one or both required headers (PRD §2.1).
NO_HEADERS: Dict[str, str] = {}
ONLY_USER_ID_HEADERS = {"X-User-ID": DIRECTOR_USER_ID, "Content-Type": "application/json"}
ONLY_ROLE_HEADERS = {
    "X-User-Role": UserRole.ARTISTIC_DIRECTOR.value,
    "Content-Type": "application/json",
}
INVALID_ROLE_HEADERS = build_user_headers(DIRECTOR_USER_ID, "Conductor")
