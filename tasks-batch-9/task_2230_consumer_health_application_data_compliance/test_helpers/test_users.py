"""Role identities and request-header builders.

Five of the six roles are operator roles whose ``X-User-ID`` is an opaque
identifier that is never matched against a stored entity id. The sixth role,
``Consumer``, is entity-backed: its ``X-User-ID`` must be the id of the
``Consumer`` row it is acting for, so its headers are always built from a
runtime id.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PRIVACY_OFFICER = "PrivacyOfficer"
ROLE_COMPLIANCE_APPROVER = "ComplianceApprover"
ROLE_DATA_STEWARD = "DataSteward"
ROLE_SECURITY_ENGINEER = "SecurityEngineer"
ROLE_CONSUMER = "Consumer"

# Default operator identifiers. Distinct per role so that separation-of-duty
# checks, which compare one operator's id with another's, have something to
# compare.
USER_PLATFORM_ADMIN = "pa-1"
USER_PRIVACY_OFFICER = "po-1"
USER_PRIVACY_OFFICER_ALT = "po-2"
USER_COMPLIANCE_APPROVER = "ca-1"
USER_COMPLIANCE_APPROVER_ALT = "ca-2"
USER_DATA_STEWARD = "ds-1"
USER_SECURITY_ENGINEER = "se-1"
# One identifier used in both the authoring and the approving capacity, to
# provoke separation-of-duty refusals.
USER_DUAL_HAT = "u-dual"

TEST_USERS: dict[str, dict[str, str]] = {
    "platform_admin": {"user_id": USER_PLATFORM_ADMIN, "role": ROLE_PLATFORM_ADMIN},
    "privacy_officer": {"user_id": USER_PRIVACY_OFFICER, "role": ROLE_PRIVACY_OFFICER},
    "privacy_officer_alt": {
        "user_id": USER_PRIVACY_OFFICER_ALT,
        "role": ROLE_PRIVACY_OFFICER,
    },
    "compliance_approver": {
        "user_id": USER_COMPLIANCE_APPROVER,
        "role": ROLE_COMPLIANCE_APPROVER,
    },
    "compliance_approver_alt": {
        "user_id": USER_COMPLIANCE_APPROVER_ALT,
        "role": ROLE_COMPLIANCE_APPROVER,
    },
    "data_steward": {"user_id": USER_DATA_STEWARD, "role": ROLE_DATA_STEWARD},
    "security_engineer": {
        "user_id": USER_SECURITY_ENGINEER,
        "role": ROLE_SECURITY_ENGINEER,
    },
}


def make_platform_admin_headers(user_id: str = USER_PLATFORM_ADMIN) -> dict[str, str]:
    """Headers for a PlatformAdmin caller."""
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_privacy_officer_headers(user_id: str = USER_PRIVACY_OFFICER) -> dict[str, str]:
    """Headers for a PrivacyOfficer caller."""
    return build_user_headers(user_id, ROLE_PRIVACY_OFFICER)


def make_compliance_approver_headers(
    user_id: str = USER_COMPLIANCE_APPROVER,
) -> dict[str, str]:
    """Headers for a ComplianceApprover caller."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_APPROVER)


def make_data_steward_headers(user_id: str = USER_DATA_STEWARD) -> dict[str, str]:
    """Headers for a DataSteward caller."""
    return build_user_headers(user_id, ROLE_DATA_STEWARD)


def make_security_engineer_headers(
    user_id: str = USER_SECURITY_ENGINEER,
) -> dict[str, str]:
    """Headers for a SecurityEngineer caller."""
    return build_user_headers(user_id, ROLE_SECURITY_ENGINEER)


def make_consumer_headers(consumer_id: str) -> dict[str, str]:
    """Headers for a Consumer caller acting for the given consumer row."""
    return build_user_headers(consumer_id, ROLE_CONSUMER)
