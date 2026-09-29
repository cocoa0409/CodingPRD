"""Pre-built role headers for every role in the PRD.

Every request carries `X-User-ID` and `X-User-Role`. The three publisher-side
roles (`PublisherAdmin`, `ReleaseManager`, `ComplianceOfficer`) are
account-backed and must additionally carry `X-Publisher-Account-Id` naming the
`PublisherAccount` the operator acts for. The four platform-side roles
(`PlatformReviewer`, `PlatformAppealBoard`, `PlatformPolicyAdmin`, `Auditor`)
carry an opaque identity and never send `X-Publisher-Account-Id`.
"""
from prd_bench_local_runner.testing import build_user_headers

ACCOUNT_HEADER = "X-Publisher-Account-Id"

DEFAULT_PUBLISHER_ADMIN_ID = "u-pubadmin-1"
DEFAULT_RELEASE_MANAGER_ID = "u-release-1"
DEFAULT_COMPLIANCE_OFFICER_ID = "u-compliance-1"
DEFAULT_POLICY_ADMIN_ID = "u-policy-1"
DEFAULT_REVIEWER_ID = "u-reviewer-1"
DEFAULT_APPEAL_BOARD_ID = "u-board-1"
DEFAULT_AUDITOR_ID = "u-auditor-1"


# --- Shared constants: safe for the opaque platform roles, and for tests that
# --- do not exercise tenancy ownership.
TEST_USERS = {
    "policy_admin_headers": build_user_headers(DEFAULT_POLICY_ADMIN_ID, "PlatformPolicyAdmin"),
    "reviewer_headers": build_user_headers(DEFAULT_REVIEWER_ID, "PlatformReviewer"),
    "appeal_board_headers": build_user_headers(DEFAULT_APPEAL_BOARD_ID, "PlatformAppealBoard"),
    "auditor_headers": build_user_headers(DEFAULT_AUDITOR_ID, "Auditor"),
}


def _account_headers(user_id: str, role: str, account_id: str) -> dict:
    headers = build_user_headers(user_id, role)
    headers[ACCOUNT_HEADER] = account_id
    return headers


def make_publisher_admin_headers(account_id: str, user_id: str = DEFAULT_PUBLISHER_ADMIN_ID) -> dict:
    """For PublisherAdmin. `account_id` is the real PublisherAccount.id and goes
    into `X-Publisher-Account-Id`, the tenancy subject."""
    return _account_headers(user_id, "PublisherAdmin", account_id)


def make_release_manager_headers(account_id: str, user_id: str = DEFAULT_RELEASE_MANAGER_ID) -> dict:
    """For ReleaseManager. `account_id` is the real PublisherAccount.id."""
    return _account_headers(user_id, "ReleaseManager", account_id)


def make_compliance_officer_headers(
    account_id: str, user_id: str = DEFAULT_COMPLIANCE_OFFICER_ID
) -> dict:
    """For ComplianceOfficer. `account_id` is the real PublisherAccount.id."""
    return _account_headers(user_id, "ComplianceOfficer", account_id)


def make_policy_admin_headers(user_id: str = DEFAULT_POLICY_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "PlatformPolicyAdmin")


def make_reviewer_headers(user_id: str = DEFAULT_REVIEWER_ID) -> dict:
    return build_user_headers(user_id, "PlatformReviewer")


def make_appeal_board_headers(user_id: str = DEFAULT_APPEAL_BOARD_ID) -> dict:
    return build_user_headers(user_id, "PlatformAppealBoard")


def make_auditor_headers(user_id: str = DEFAULT_AUDITOR_ID) -> dict:
    return build_user_headers(user_id, "Auditor")


ACCOUNT_BACKED_BUILDERS = {
    "PublisherAdmin": make_publisher_admin_headers,
    "ReleaseManager": make_release_manager_headers,
    "ComplianceOfficer": make_compliance_officer_headers,
}

OPAQUE_BUILDERS = {
    "PlatformReviewer": make_reviewer_headers,
    "PlatformAppealBoard": make_appeal_board_headers,
    "PlatformPolicyAdmin": make_policy_admin_headers,
    "Auditor": make_auditor_headers,
}


def headers_for_role(role: str, account_id: str = None, user_id: str = None) -> dict:
    """Build well-formed headers for any of the seven roles."""
    if role in ACCOUNT_BACKED_BUILDERS:
        builder = ACCOUNT_BACKED_BUILDERS[role]
        if user_id is None:
            return builder(account_id)
        return builder(account_id, user_id)
    builder = OPAQUE_BUILDERS[role]
    if user_id is None:
        return builder()
    return builder(user_id)
