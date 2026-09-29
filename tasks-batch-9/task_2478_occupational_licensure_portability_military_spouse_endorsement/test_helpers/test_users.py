"""Identity headers for the five agency roles.

Two roles are entity-backed: an `Applicant` presents the `id` of their own
applicant row as `X-User-ID`, and an `Evaluator` presents the `id` of their own
evaluator row.  Those identities cannot be constants, so they are built per test
with `make_applicant_headers()` / `make_evaluator_headers()`.

The other three roles are opaque operator identifiers, so shared constants are
appropriate for them.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AGENCY_ADMIN,
    ROLE_APPLICANT,
    ROLE_BOARD_DEPUTY,
    ROLE_EVALUATOR,
    ROLE_LICENSING_ANALYST,
)

# ─── Opaque operator identities ───────────────────────

ADMIN_USER_ID = "adm_1"
ADMIN_USER_ID_2 = "adm_2"
ANALYST_USER_ID = "anl_1"
ANALYST_USER_ID_2 = "anl_2"
DEPUTY_USER_ID = "dep_1"
DEPUTY_USER_ID_2 = "dep_2"

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_AGENCY_ADMIN)
ADMIN_HEADERS_2 = build_user_headers(ADMIN_USER_ID_2, ROLE_AGENCY_ADMIN)
ANALYST_HEADERS = build_user_headers(ANALYST_USER_ID, ROLE_LICENSING_ANALYST)
ANALYST_HEADERS_2 = build_user_headers(ANALYST_USER_ID_2, ROLE_LICENSING_ANALYST)
DEPUTY_HEADERS = build_user_headers(DEPUTY_USER_ID, ROLE_BOARD_DEPUTY)
DEPUTY_HEADERS_2 = build_user_headers(DEPUTY_USER_ID_2, ROLE_BOARD_DEPUTY)


# ─── Entity-backed identities ─────────────────────────

def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """Headers for the `Applicant` whose persisted row has this `id`."""
    return build_user_headers(applicant_id, ROLE_APPLICANT)


def make_evaluator_headers(evaluator_id: str) -> Dict[str, str]:
    """Headers for the `Evaluator` whose persisted row has this `id`."""
    return build_user_headers(evaluator_id, ROLE_EVALUATOR)


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named `LicensingAnalyst` operator identifier."""
    return build_user_headers(user_id, ROLE_LICENSING_ANALYST)


def make_deputy_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named `BoardDeputy` operator identifier."""
    return build_user_headers(user_id, ROLE_BOARD_DEPUTY)


def make_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named `AgencyAdmin` operator identifier."""
    return build_user_headers(user_id, ROLE_AGENCY_ADMIN)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user/role pair."""
    return build_user_headers(user_id, role)


# ─── Malformed identities ─────────────────────────────

def headers_without_user_id(role: str = ROLE_AGENCY_ADMIN) -> Dict[str, str]:
    """Headers carrying `X-User-Role` but no `X-User-ID`."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers carrying `X-User-ID` but no `X-User-Role`."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(
    user_id: str = ADMIN_USER_ID, role: Optional[str] = "Registrar"
) -> Dict[str, str]:
    """Headers whose `X-User-Role` is not one of the five recognised roles."""
    return build_user_headers(user_id, role or "Registrar")
