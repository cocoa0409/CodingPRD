"""Acting identities and header builders.

Three of the five roles are backed by a staff-member row, so any call that is
ownership-gated must present the identifier of the staff member who actually
owns the resource. Use the ``make_*_headers`` builders for those calls and pass
the real row identifier; ``TEST_USERS`` only supplies a stand-in identifier for
calls whose outcome does not depend on the acting person.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers, UserRole

TEST_USERS: Dict[str, Dict[str, str]] = {
    "firm_admin": {
        "user_id": "11111111-1111-4111-8111-111111111111",
        "role": UserRole.FIRM_ADMIN.value,
    },
    "scheduling_manager": {
        "user_id": "22222222-2222-4222-8222-222222222222",
        "role": UserRole.SCHEDULING_MANAGER.value,
    },
    "engagement_partner": {
        "user_id": "33333333-3333-4333-8333-333333333333",
        "role": UserRole.ENGAGEMENT_PARTNER.value,
    },
    "engagement_staff": {
        "user_id": "44444444-4444-4444-8444-444444444444",
        "role": UserRole.ENGAGEMENT_STAFF.value,
    },
    "independence_officer": {
        "user_id": "55555555-5555-4555-8555-555555555555",
        "role": UserRole.INDEPENDENCE_OFFICER.value,
    },
}


def _headers(key: str) -> Headers:
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


def firm_admin_headers() -> Headers:
    return _headers("firm_admin")


def scheduling_manager_headers() -> Headers:
    return _headers("scheduling_manager")


def independence_officer_headers() -> Headers:
    return _headers("independence_officer")


def make_firm_admin_headers(user_id: str) -> Headers:
    return build_user_headers(user_id, UserRole.FIRM_ADMIN.value)


def make_scheduling_manager_headers(user_id: str) -> Headers:
    return build_user_headers(user_id, UserRole.SCHEDULING_MANAGER.value)


def make_engagement_partner_headers(user_id: str) -> Headers:
    """Headers for a partner acting as the staff member ``user_id``."""

    return build_user_headers(user_id, UserRole.ENGAGEMENT_PARTNER.value)


def make_engagement_staff_headers(user_id: str) -> Headers:
    """Headers for a staff member acting as the staff member ``user_id``."""

    return build_user_headers(user_id, UserRole.ENGAGEMENT_STAFF.value)


def make_independence_officer_headers(user_id: str) -> Headers:
    return build_user_headers(user_id, UserRole.INDEPENDENCE_OFFICER.value)


def make_headers(role: str, user_id: str) -> Headers:
    """Headers for an arbitrary role/identity pair."""

    return build_user_headers(user_id, role)


def headers_with_blank_user_id(role: str) -> Headers:
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str) -> Headers:
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


__all__ = [
    "TEST_USERS",
    "firm_admin_headers",
    "scheduling_manager_headers",
    "independence_officer_headers",
    "make_firm_admin_headers",
    "make_scheduling_manager_headers",
    "make_engagement_partner_headers",
    "make_engagement_staff_headers",
    "make_independence_officer_headers",
    "make_headers",
    "headers_with_blank_user_id",
    "headers_with_blank_role",
]
