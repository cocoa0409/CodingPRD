"""Identity headers for the five roles of PRD §2.1.

Three roles are opaque (``PlatformAdmin``, ``ComplianceOfficer``, ``CarrierAgent``)
and their ``X-User-ID`` is an arbitrary operator identifier, so shared constants
are fine.  Two roles are entity backed: for ``WineryOperator`` the ``X-User-ID``
must be the acting ``Winery.id`` and for ``Consumer`` it must be the acting
``Consumer.id``.  Those two must therefore always be built from a real row id via
``make_winery_operator_headers`` / ``make_consumer_headers``.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CARRIER_AGENT,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CONSUMER,
    ROLE_PLATFORM_ADMIN,
    ROLE_WINERY_OPERATOR,
)

# Opaque operator identifiers.
ADMIN_USER_ID = "admin_a"
OFFICER_A_USER_ID = "officer_a"
OFFICER_B_USER_ID = "officer_b"
CARRIER_USER_ID = "carrier_a"

TEST_USERS = {
    "admin": build_user_headers(ADMIN_USER_ID, ROLE_PLATFORM_ADMIN),
    "officer_a": build_user_headers(OFFICER_A_USER_ID, ROLE_COMPLIANCE_OFFICER),
    "officer_b": build_user_headers(OFFICER_B_USER_ID, ROLE_COMPLIANCE_OFFICER),
    "carrier": build_user_headers(CARRIER_USER_ID, ROLE_CARRIER_AGENT),
}

ADMIN = TEST_USERS["admin"]
OFFICER_A = TEST_USERS["officer_a"]
OFFICER_B = TEST_USERS["officer_b"]
CARRIER = TEST_USERS["carrier"]


def make_winery_operator_headers(winery_id):
    """Headers for a WineryOperator acting as the winery whose id is given."""
    return build_user_headers(str(winery_id), ROLE_WINERY_OPERATOR)


def make_consumer_headers(consumer_id):
    """Headers for a Consumer acting as the consumer whose id is given."""
    return build_user_headers(str(consumer_id), ROLE_CONSUMER)


def make_officer_headers(user_id):
    """Headers for a ComplianceOfficer with an explicit opaque identifier."""
    return build_user_headers(str(user_id), ROLE_COMPLIANCE_OFFICER)


def make_carrier_headers(user_id=CARRIER_USER_ID):
    """Headers for a CarrierAgent with an explicit opaque identifier."""
    return build_user_headers(str(user_id), ROLE_CARRIER_AGENT)


def make_admin_headers(user_id=ADMIN_USER_ID):
    """Headers for a PlatformAdmin with an explicit opaque identifier."""
    return build_user_headers(str(user_id), ROLE_PLATFORM_ADMIN)


def headers_for_role(role, user_id):
    """Generic builder used by the role-matrix tests."""
    return build_user_headers(str(user_id), role)
