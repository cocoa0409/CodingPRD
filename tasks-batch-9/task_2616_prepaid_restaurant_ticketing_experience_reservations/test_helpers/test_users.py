"""
Identity header builders for the five roles.

The PRD makes role identity non-uniform, and the difference matters for every
ownership check: "When X-User-Role is Guest, X-User-ID is the id of the acting
Guest", "When X-User-Role is RestaurantManager, X-User-ID is the id of the
acting Restaurant", "When X-User-Role is KitchenLead, X-User-ID is likewise the
id of the acting Restaurant", while GuestServices and PlatformAdmin ids are
"an opaque operator identifier not tied to any persisted entity".

Consequently the three entity-backed roles MUST be built from the real entity
id created during setup — never from a fixed constant — and only the two opaque
roles get stable constants.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_GUEST,
    ROLE_GUEST_SERVICES,
    ROLE_KITCHEN_LEAD,
    ROLE_PLATFORM_ADMIN,
    ROLE_RESTAURANT_MANAGER,
)

# ─── opaque operator identifiers ──────────────────────────────────────────
#
# These are not entity ids and are never compared to one, so they may be any
# stable string. Several distinct GuestServices identifiers are provided
# because segregation of duties compares the acting id across the file /
# decide / issue / revoke chain.

PLATFORM_ADMIN_ID = "admin-operator-001"
GUEST_SERVICES_FILER_ID = "care-operator-filer"
GUEST_SERVICES_DECIDER_ID = "care-operator-decider"
GUEST_SERVICES_ISSUER_ID = "care-operator-issuer"
GUEST_SERVICES_REVOKER_ID = "care-operator-revoker"
GUEST_SERVICES_ID = GUEST_SERVICES_FILER_ID

ADMIN_HEADERS = build_user_headers(PLATFORM_ADMIN_ID, ROLE_PLATFORM_ADMIN)
CARE_HEADERS = build_user_headers(GUEST_SERVICES_FILER_ID, ROLE_GUEST_SERVICES)
CARE_FILER_HEADERS = build_user_headers(
    GUEST_SERVICES_FILER_ID, ROLE_GUEST_SERVICES
)
CARE_DECIDER_HEADERS = build_user_headers(
    GUEST_SERVICES_DECIDER_ID, ROLE_GUEST_SERVICES
)
CARE_ISSUER_HEADERS = build_user_headers(
    GUEST_SERVICES_ISSUER_ID, ROLE_GUEST_SERVICES
)
CARE_REVOKER_HEADERS = build_user_headers(
    GUEST_SERVICES_REVOKER_ID, ROLE_GUEST_SERVICES
)


# ─── entity-backed role header builders ───────────────────────────────────


def make_guest_headers(guest_id: str) -> dict:
    """Headers for a Guest, whose X-User-ID is the acting Guest's own id."""
    return build_user_headers(guest_id, ROLE_GUEST)


def make_restaurant_headers(restaurant_id: str) -> dict:
    """Headers for a RestaurantManager, whose X-User-ID is the Restaurant id."""
    return build_user_headers(restaurant_id, ROLE_RESTAURANT_MANAGER)


def make_manager_headers(restaurant_id: str) -> dict:
    """Alias of :func:`make_restaurant_headers`."""
    return build_user_headers(restaurant_id, ROLE_RESTAURANT_MANAGER)


def make_kitchen_headers(restaurant_id: str) -> dict:
    """Headers for a KitchenLead, whose X-User-ID is also the Restaurant id."""
    return build_user_headers(restaurant_id, ROLE_KITCHEN_LEAD)


def make_kitchen_lead_headers(restaurant_id: str) -> dict:
    """Alias of :func:`make_kitchen_headers`."""
    return build_user_headers(restaurant_id, ROLE_KITCHEN_LEAD)


def make_care_headers(operator_id: str) -> dict:
    """Headers for a GuestServices operator with a chosen opaque identifier."""
    return build_user_headers(operator_id, ROLE_GUEST_SERVICES)


def make_admin_headers(operator_id: str = PLATFORM_ADMIN_ID) -> dict:
    """Headers for a PlatformAdmin with a chosen opaque identifier."""
    return build_user_headers(operator_id, ROLE_PLATFORM_ADMIN)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary role, used by the role-matrix probes."""
    return build_user_headers(user_id, role)


def headers_without(headers: dict, header_name: str) -> dict:
    """A copy of ``headers`` with one header removed entirely."""
    stripped = dict(headers)
    stripped.pop(header_name, None)
    return stripped


def headers_with_blank(headers: dict, header_name: str) -> dict:
    """A copy of ``headers`` with one header present but empty."""
    blanked = dict(headers)
    blanked[header_name] = ""
    return blanked
