"""Caller identities.

Three roles are opaque operators whose ``X-User-ID`` is never compared against a
stored row, so fixed operator identifiers are enough for them. The two
entity-backed roles are different: a ``ShopManager`` must present the id of the
Shop it manages and a ``Technician`` must present the id of the Technician row it
acts as, so their headers must always be built from a live entity id through
``make_shop_manager_headers`` / ``make_technician_headers``.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers. Two distinct ContentPublisher identifiers exist
# because moving a version through validation and publication requires them, and
# two ComplianceOfficer identifiers make cascade attribution observable.
PLATFORM_ADMIN_USER_ID = "pa_1"
CONTENT_PUBLISHER_1_USER_ID = "cp_1"
CONTENT_PUBLISHER_2_USER_ID = "cp_2"
COMPLIANCE_OFFICER_1_USER_ID = "co_1"
COMPLIANCE_OFFICER_2_USER_ID = "co_2"

TEST_USERS = {
    "platform_admin": {
        "user_id": PLATFORM_ADMIN_USER_ID,
        "role": Role.PLATFORM_ADMIN,
    },
    "content_publisher_1": {
        "user_id": CONTENT_PUBLISHER_1_USER_ID,
        "role": Role.CONTENT_PUBLISHER,
    },
    "content_publisher_2": {
        "user_id": CONTENT_PUBLISHER_2_USER_ID,
        "role": Role.CONTENT_PUBLISHER,
    },
    "compliance_officer_1": {
        "user_id": COMPLIANCE_OFFICER_1_USER_ID,
        "role": Role.COMPLIANCE_OFFICER,
    },
    "compliance_officer_2": {
        "user_id": COMPLIANCE_OFFICER_2_USER_ID,
        "role": Role.COMPLIANCE_OFFICER,
    },
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


def make_content_publisher_headers(
    user_id: str = CONTENT_PUBLISHER_1_USER_ID,
) -> dict:
    return build_user_headers(user_id, Role.CONTENT_PUBLISHER)


def make_compliance_officer_headers(
    user_id: str = COMPLIANCE_OFFICER_1_USER_ID,
) -> dict:
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER)


def make_shop_manager_headers(shop_id: str) -> dict:
    """Headers for the manager of one shop; X-User-ID is that Shop's id."""
    return build_user_headers(shop_id, Role.SHOP_MANAGER)


def make_technician_headers(technician_id: str) -> dict:
    """Headers for one technician; X-User-ID is that Technician's id."""
    return build_user_headers(technician_id, Role.TECHNICIAN)


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(user_id, role)


# Headers carrying no identity at all, and headers declaring a role outside the
# five the API accepts.
NO_HEADERS = {"Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = build_user_headers("someone", "Mechanic")
MISSING_USER_ID_HEADERS = {
    "X-User-Role": Role.PLATFORM_ADMIN,
    "Content-Type": "application/json",
}
