"""Header builders for each acting capacity.

Identity semantics differ by role, and the builders encode that difference:

* ``FranchiseeOwner`` is entity-backed — the presented ``X-User-ID`` must be the
  ``id`` of the acting ``FranchiseeAccount``, which is also the ``franchisee_id``
  of every property it may act on. There is therefore no fixed owner id: callers
  must thread the franchisee id they created through
  ``make_franchisee_owner_headers``.
* ``BrandManager`` and ``BrandInspector`` are opaque operator identifiers not tied
  to any persisted entity, so fixed ids are used. Two of each exist because the
  segregation-of-duties rule and the assigned-inspector rule both need a second,
  differently identified operator of the same role.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_FRANCHISEE_OWNER = "FranchiseeOwner"
ROLE_BRAND_MANAGER = "BrandManager"
ROLE_BRAND_INSPECTOR = "BrandInspector"

ALL_ROLES = (ROLE_FRANCHISEE_OWNER, ROLE_BRAND_MANAGER, ROLE_BRAND_INSPECTOR)

# Opaque operator identifiers.
BRAND_MANAGER_USER_ID = "bm-001"
OTHER_BRAND_MANAGER_USER_ID = "bm-002"
INSPECTOR_USER_ID = "bi-007"
OTHER_INSPECTOR_USER_ID = "bi-008"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "brand_manager": {"user_id": BRAND_MANAGER_USER_ID, "role": ROLE_BRAND_MANAGER},
    "other_brand_manager": {"user_id": OTHER_BRAND_MANAGER_USER_ID, "role": ROLE_BRAND_MANAGER},
    "inspector": {"user_id": INSPECTOR_USER_ID, "role": ROLE_BRAND_INSPECTOR},
    "other_inspector": {"user_id": OTHER_INSPECTOR_USER_ID, "role": ROLE_BRAND_INSPECTOR},
    # The franchisee owner has no fixed id: see make_franchisee_owner_headers.
    "franchisee_owner": {"user_id": "", "role": ROLE_FRANCHISEE_OWNER},
}


def make_franchisee_owner_headers(franchisee_id: str) -> Dict[str, str]:
    """Owner headers whose ``X-User-ID`` is the acting ``FranchiseeAccount`` id."""
    return build_user_headers(franchisee_id, ROLE_FRANCHISEE_OWNER)


def make_brand_manager_headers(user_id: str = BRAND_MANAGER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BRAND_MANAGER)


def make_brand_inspector_headers(user_id: str = INSPECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BRAND_INSPECTOR)


BRAND_MANAGER_HEADERS = make_brand_manager_headers()
OTHER_BRAND_MANAGER_HEADERS = make_brand_manager_headers(OTHER_BRAND_MANAGER_USER_ID)
INSPECTOR_HEADERS = make_brand_inspector_headers()
OTHER_INSPECTOR_HEADERS = make_brand_inspector_headers(OTHER_INSPECTOR_USER_ID)


# ---------------------------------------------------------------------------
# Malformed identity headers, for the authentication ladder
# ---------------------------------------------------------------------------


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying ``X-User-ID`` but no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying ``X-User-Role`` but no ``X-User-ID`` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_role(user_id: str, role: str) -> Dict[str, str]:
    """Headers with an arbitrary role string, including unrecognised ones."""
    return build_user_headers(user_id, role)


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    return build_user_headers("", role)


def headers_with_oversized_user_id(role: str, length: int = 65) -> Dict[str, str]:
    """A user id longer than the 64-character limit."""
    return build_user_headers("u" * length, role)


__all__ = [
    "ROLE_FRANCHISEE_OWNER",
    "ROLE_BRAND_MANAGER",
    "ROLE_BRAND_INSPECTOR",
    "ALL_ROLES",
    "BRAND_MANAGER_USER_ID",
    "OTHER_BRAND_MANAGER_USER_ID",
    "INSPECTOR_USER_ID",
    "OTHER_INSPECTOR_USER_ID",
    "TEST_USERS",
    "make_franchisee_owner_headers",
    "make_brand_manager_headers",
    "make_brand_inspector_headers",
    "BRAND_MANAGER_HEADERS",
    "OTHER_BRAND_MANAGER_HEADERS",
    "INSPECTOR_HEADERS",
    "OTHER_INSPECTOR_HEADERS",
    "headers_without_role",
    "headers_without_user_id",
    "headers_with_role",
    "headers_with_empty_user_id",
    "headers_with_oversized_user_id",
]
