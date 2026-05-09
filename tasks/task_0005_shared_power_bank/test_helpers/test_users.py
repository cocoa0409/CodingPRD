"""
Pre-built role headers for the shared power bank API (PRD §2.1).

Two role identity models live here side-by-side:

* ``Admin`` and ``Operator`` are *opaque* in the PRD — ``X-User-ID`` is not
  compared against any entity's ``id``. Shared-constant headers therefore
  work fine for those roles, and tests use ``ADMIN_HEADERS`` / ``OPERATOR_HEADERS``.

* ``User`` (entity_backed:User) and ``Partner`` (entity_backed:LocationPartner)
  are *entity-backed*: PRD §2.1 explicitly requires ``X-User-ID`` to equal the
  acting User's ``id`` (or LocationPartner's ``id``). Shared constants would
  fail every ownership check the PRD mandates, so fixtures MUST use the per-
  instance builders ``make_user_headers(user_id)`` / ``make_partner_headers(
  partner_id)`` after creating the underlying entity. The shared
  ``USER_HEADERS`` / ``PARTNER_HEADERS`` constants below are reserved for
  tests that exercise non-ownership paths (e.g. 401-on-missing-header,
  404-on-non-existent-rental, 403-on-wrong-role).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Stable opaque IDs for Admin / Operator (any string is acceptable per PRD §2.1)
# ---------------------------------------------------------------------------

ADMIN_USER_ID = "a0000000-0000-0000-0000-000000000001"
OPERATOR_USER_ID = "o0000000-0000-0000-0000-000000000001"
OPERATOR_2_USER_ID = "o0000000-0000-0000-0000-000000000002"

# Placeholder IDs for shared-constant User / Partner — these resolve to
# non-existent entities, which is the correct shape for tests that must
# observe behaviour BEFORE any ownership compare runs (auth-missing,
# 404-on-resource-missing, role-permitted-but-wrong-role).
PLACEHOLDER_USER_ID = "u0000000-0000-0000-0000-000000000001"
PLACEHOLDER_PARTNER_ID = "p0000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Shared header constants (opaque roles — safe to share)
# ---------------------------------------------------------------------------

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, "Admin")
OPERATOR_HEADERS = build_user_headers(OPERATOR_USER_ID, "Operator")
OPERATOR_2_HEADERS = build_user_headers(OPERATOR_2_USER_ID, "Operator")

# Shared header constants for entity-backed roles. These are NOT used by
# fixtures for ownership-gated calls; see module docstring.
USER_HEADERS_PLACEHOLDER = build_user_headers(PLACEHOLDER_USER_ID, "User")
PARTNER_HEADERS_PLACEHOLDER = build_user_headers(
    PLACEHOLDER_PARTNER_ID, "Partner"
)

# Empty headers — used to exercise the priority-1 ERR_UNAUTHENTICATED gate.
NO_AUTH_HEADERS: Dict[str, str] = {}


TEST_USERS = {
    "admin_headers": ADMIN_HEADERS,
    "operator_headers": OPERATOR_HEADERS,
    "operator2_headers": OPERATOR_2_HEADERS,
    "user_headers_placeholder": USER_HEADERS_PLACEHOLDER,
    "partner_headers_placeholder": PARTNER_HEADERS_PLACEHOLDER,
    "no_auth_headers": NO_AUTH_HEADERS,
}


# ---------------------------------------------------------------------------
# Per-instance builders (mandatory for entity-backed roles per PRD §2.1)
# ---------------------------------------------------------------------------


def make_user_headers(user_id: str) -> Dict[str, str]:
    """Build headers for the ``User`` role (PRD §2.1 — entity-backed).

    Pass the actual ``User.id`` returned by ``POST /users``. PRD §2.1 says
    "When ``X-User-Role`` is ``User``, ``X-User-ID`` is the ``id`` of the
    acting ``User``"; ownership checks (§2.7 priority 7) compare
    ``Rental.user_id`` to this value, so fixtures must thread the real id
    through.
    """
    return build_user_headers(user_id, "User")


def make_partner_headers(partner_id: str) -> Dict[str, str]:
    """Build headers for the ``Partner`` role (PRD §2.1 — entity-backed).

    Pass the actual ``LocationPartner.id``. PRD §2.1: "When ``X-User-Role``
    is ``Partner``, ``X-User-ID`` is the ``id`` of the acting
    ``LocationPartner``"; settlement reads (§3.9) are scoped by this value.
    """
    return build_user_headers(partner_id, "Partner")


def make_operator_headers(operator_id: str) -> Dict[str, str]:
    """Build headers for a specific operator id.

    ``Operator`` is opaque, but tests sometimes need two distinct operator
    identities (e.g. assignment race) — this helper makes that explicit.
    """
    return build_user_headers(operator_id, "Operator")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """Build headers for a specific admin id (Admin is opaque per PRD §2.1)."""
    return build_user_headers(admin_id, "Admin")
