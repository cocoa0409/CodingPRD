"""Identity headers.

Two of the five roles are entity-backed: an ``Operator`` caller's user id must
be the id of the operation they own and a ``Hauler`` caller's user id must be
the id of their hauler row. Those identities therefore cannot be fixed
constants — they are minted per test from the entity actually created, using
``make_operator_headers()`` / ``make_hauler_headers()``.

The remaining three roles (``CertifiedPlanner``, ``StateReviewer``,
``ComplianceAdmin``) carry opaque user ids, so stable constants are fine.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque-identity users: any stable id works for these roles.
TEST_USERS = {
    "admin": {"user_id": "admin-1", "role": UserRole.COMPLIANCE_ADMIN.value},
    "planner": {"user_id": "planner-1", "role": UserRole.CERTIFIED_PLANNER.value},
    "planner_2": {"user_id": "planner-2", "role": UserRole.CERTIFIED_PLANNER.value},
    "reviewer": {"user_id": "reviewer-1", "role": UserRole.STATE_REVIEWER.value},
    "reviewer_2": {"user_id": "reviewer-2", "role": UserRole.STATE_REVIEWER.value},
}

ADMIN_HEADERS = build_user_headers(
    TEST_USERS["admin"]["user_id"], TEST_USERS["admin"]["role"]
)
PLANNER_HEADERS = build_user_headers(
    TEST_USERS["planner"]["user_id"], TEST_USERS["planner"]["role"]
)
PLANNER_2_HEADERS = build_user_headers(
    TEST_USERS["planner_2"]["user_id"], TEST_USERS["planner_2"]["role"]
)
REVIEWER_HEADERS = build_user_headers(
    TEST_USERS["reviewer"]["user_id"], TEST_USERS["reviewer"]["role"]
)
REVIEWER_2_HEADERS = build_user_headers(
    TEST_USERS["reviewer_2"]["user_id"], TEST_USERS["reviewer_2"]["role"]
)


def make_operator_headers(operation_id: str) -> dict:
    """Headers for the operator who owns ``operation_id``."""
    return build_user_headers(operation_id, UserRole.OPERATOR.value)


def make_hauler_headers(hauler_id: str) -> dict:
    """Headers for the hauler whose row is ``hauler_id``."""
    return build_user_headers(hauler_id, UserRole.HAULER.value)


def make_planner_headers(user_id: str) -> dict:
    """Headers for an arbitrary certified planner user id."""
    return build_user_headers(user_id, UserRole.CERTIFIED_PLANNER.value)


def make_reviewer_headers(user_id: str) -> dict:
    """Headers for an arbitrary state reviewer user id."""
    return build_user_headers(user_id, UserRole.STATE_REVIEWER.value)


def make_admin_headers(user_id: str) -> dict:
    """Headers for an arbitrary compliance administrator user id."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_ADMIN.value)


def make_headers(user_id: str, role) -> dict:
    """Headers for any explicit user id / role pair."""
    return build_user_headers(user_id, role.value if hasattr(role, "value") else role)


def headers_without_identity() -> dict:
    """Headers that omit the identity headers entirely."""
    return {"Content-Type": "application/json"}
