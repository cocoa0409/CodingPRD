"""Pre-built role headers for every role in the PRD.

Every request carries X-User-ID and X-User-Role. Four of the five roles are
opaque -- their user id is never matched against a stored row -- so the shared
constants below are the canonical form for them. CarrierRepresentative is the
exception: the PRD matches its X-User-ID against Carrier.id, so any
ownership-gated call must use make_carrier_representative_headers(carrier_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque roles, and for CarrierRepresentative
# only in tests whose expected outcome does not depend on owning the subject.
TEST_USERS = {
    # entity_backed role: the shared constant owns nothing.
    "carrier_representative_headers": build_user_headers(
        "carrier-rep-1", "CarrierRepresentative"
    ),
    # opaque roles.
    "numbering_administrator_headers": build_user_headers(
        "admin-1", "NumberingAdministrator"
    ),
    "regulatory_approver_headers": build_user_headers("approver-1", "RegulatoryApprover"),
    "porting_operations_headers": build_user_headers("porting-1", "PortingOperations"),
    "public_commenter_headers": build_user_headers("commenter-1", "PublicCommenter"),
}

# Named opaque identities used where the PRD segregates duties by user id.
ADMIN_USER_ID = "admin-1"
SECOND_ADMIN_USER_ID = "admin-2"
APPROVER_USER_ID = "approver-1"
SECOND_APPROVER_USER_ID = "approver-2"
PORTING_USER_ID = "porting-1"
COMMENTER_USER_ID = "commenter-1"

ADMIN_HEADERS = TEST_USERS["numbering_administrator_headers"]
SECOND_ADMIN_HEADERS = build_user_headers(SECOND_ADMIN_USER_ID, "NumberingAdministrator")
APPROVER_HEADERS = TEST_USERS["regulatory_approver_headers"]
SECOND_APPROVER_HEADERS = build_user_headers(
    SECOND_APPROVER_USER_ID, "RegulatoryApprover"
)
PORTING_HEADERS = TEST_USERS["porting_operations_headers"]
COMMENTER_HEADERS = TEST_USERS["public_commenter_headers"]

# A request with neither identity header set.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_carrier_representative_headers(user_id: str) -> dict:
    """For CarrierRepresentative, whose X-User-ID is matched against Carrier.id.

    Pass the real carrier id whenever the call is ownership-gated: filing a
    utilization filing or an allocation request, withdrawing a request,
    attesting readiness, confirming an activation, surrendering or appealing a
    reclamation order, filing or concurring a port request, commenting on a
    relief plan.
    """
    return build_user_headers(user_id, "CarrierRepresentative")


def make_numbering_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NumberingAdministrator")


def make_regulatory_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatoryApprover")


def make_porting_operations_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PortingOperations")


def make_public_commenter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PublicCommenter")
