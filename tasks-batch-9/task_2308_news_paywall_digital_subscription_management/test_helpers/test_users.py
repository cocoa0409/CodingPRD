"""Pre-built role headers for every role the PRD defines.

Two roles are entity-backed and their ``X-User-ID`` must be a real row id:

- ``Reader``     — ``X-User-ID`` is the ``id`` of the acting Reader.
- ``GroupAdmin`` — ``X-User-ID`` is the ``id`` of the acting GroupAccount.

For those two, always use the per-instance builders below and pass the actual
entity id whenever the call is ownership-gated. The other three roles are
opaque operator identities that the server never compares to an entity id, so
the shared constants are the canonical form for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque compliance-desk identities. Two distinct officers are needed wherever
# the segregation-of-duties comparand matters: the officer who dispatches the
# notices may never be the officer who applies the increase.
OFFICER_ONE_ID = "officer-1"
OFFICER_TWO_ID = "officer-2"
OFFICER_NINE_ID = "officer-9"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Entity-backed roles: shared constants are only for tests that do not
    # exercise ownership (missing-body, unknown-id, role-refusal scenarios).
    "reader_headers": build_user_headers("test-reader-1", UserRole.READER.value),
    "group_admin_headers": build_user_headers(
        "test-group-admin-1", UserRole.GROUP_ADMIN.value
    ),
    # Opaque operator identities.
    "ops_agent_headers": build_user_headers(
        "test-ops-agent-1", UserRole.SUBSCRIPTION_OPS_AGENT.value
    ),
    "revenue_manager_headers": build_user_headers(
        "test-revenue-manager-1", UserRole.REVENUE_MANAGER.value
    ),
    "compliance_officer_headers": build_user_headers(
        OFFICER_ONE_ID, UserRole.COMPLIANCE_OFFICER.value
    ),
    "compliance_officer_two_headers": build_user_headers(
        OFFICER_TWO_ID, UserRole.COMPLIANCE_OFFICER.value
    ),
    "compliance_officer_nine_headers": build_user_headers(
        OFFICER_NINE_ID, UserRole.COMPLIANCE_OFFICER.value
    ),
}


def make_reader_headers(reader_id: str) -> Dict[str, str]:
    """Headers for a Reader acting on their own rows. Pass the Reader's id."""
    return build_user_headers(reader_id, UserRole.READER.value)


def make_group_admin_headers(group_account_id: str) -> Dict[str, str]:
    """Headers for a GroupAdmin. Pass the GroupAccount's id."""
    return build_user_headers(group_account_id, UserRole.GROUP_ADMIN.value)


def make_ops_agent_headers(user_id: str = "test-ops-agent-1") -> Dict[str, str]:
    """Headers for the opaque operations identity."""
    return build_user_headers(user_id, UserRole.SUBSCRIPTION_OPS_AGENT.value)


def make_revenue_manager_headers(
    user_id: str = "test-revenue-manager-1",
) -> Dict[str, str]:
    """Headers for the opaque commercial-team identity."""
    return build_user_headers(user_id, UserRole.REVENUE_MANAGER.value)


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named compliance-desk identity.

    The acting id is recorded as ``notice_sent_by_user_id`` when notices are
    dispatched, and is the comparand for the segregation-of-duties check, so
    tests must be explicit about which officer acts.
    """
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


# Convenience aliases for the two officers used across the price pipeline.
OFFICER_ONE_HEADERS = make_compliance_officer_headers(OFFICER_ONE_ID)
OFFICER_TWO_HEADERS = make_compliance_officer_headers(OFFICER_TWO_ID)
OFFICER_NINE_HEADERS = make_compliance_officer_headers(OFFICER_NINE_ID)

OPS_AGENT_HEADERS = TEST_USERS["ops_agent_headers"]
REVENUE_MANAGER_HEADERS = TEST_USERS["revenue_manager_headers"]
