"""Header builders for every role the PRD authorises.

The PRD authenticates every request with an ``X-User-ID`` header and an
``X-User-Role`` header. Four roles carry opaque identifiers; the ``Consumer``
role's identifier IS a ``Contact`` identifier, so consumer headers must always
be built from the identifier of the contact whose record is being read.

Segregation of duties is enforced *within* the single ``ComplianceOfficer``
role by user id, so several distinct officer identities are provided.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers, UserRole

# ---------------------------------------------------------------------------
# Opaque user identifiers
# ---------------------------------------------------------------------------

PLATFORM_ADMIN_USER_ID = "admin-1"

CAMPAIGN_MANAGER_USER_ID = "manager-1"
CAMPAIGN_MANAGER_BUILDER_USER_ID = "manager-builder"
CAMPAIGN_MANAGER_OTHER_USER_ID = "manager-2"

DIALER_OPERATOR_USER_ID = "operator-1"
DIALER_OPERATOR_OTHER_USER_ID = "operator-2"

# Distinct ComplianceOfficer identities. The officer who approves a campaign's
# AgentScript may not certify that campaign's launch, so the script approver and
# the launcher are always different people.
OFFICER_USER_ID = "officer-1"
OFFICER_SCRIPT_APPROVER_USER_ID = "officer-script-approver"
OFFICER_PROFILE_APPROVER_USER_ID = "officer-profile-approver"
OFFICER_LAUNCHER_USER_ID = "officer-launcher"
OFFICER_ADJUDICATOR_USER_ID = "officer-adjudicator"
OFFICER_SECOND_APPROVER_USER_ID = "officer-second-approver"
OFFICER_AUDITOR_USER_ID = "auditor-1"


TEST_USERS = {
    "platform_admin": {
        "user_id": PLATFORM_ADMIN_USER_ID,
        "role": UserRole.PLATFORM_ADMIN,
    },
    "campaign_manager": {
        "user_id": CAMPAIGN_MANAGER_USER_ID,
        "role": UserRole.CAMPAIGN_MANAGER,
    },
    "campaign_manager_builder": {
        "user_id": CAMPAIGN_MANAGER_BUILDER_USER_ID,
        "role": UserRole.CAMPAIGN_MANAGER,
    },
    "campaign_manager_other": {
        "user_id": CAMPAIGN_MANAGER_OTHER_USER_ID,
        "role": UserRole.CAMPAIGN_MANAGER,
    },
    "dialer_operator": {
        "user_id": DIALER_OPERATOR_USER_ID,
        "role": UserRole.DIALER_OPERATOR,
    },
    "dialer_operator_other": {
        "user_id": DIALER_OPERATOR_OTHER_USER_ID,
        "role": UserRole.DIALER_OPERATOR,
    },
    "compliance_officer": {
        "user_id": OFFICER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER,
    },
    "officer_script_approver": {
        "user_id": OFFICER_SCRIPT_APPROVER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER,
    },
    "officer_profile_approver": {
        "user_id": OFFICER_PROFILE_APPROVER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER,
    },
    "officer_launcher": {
        "user_id": OFFICER_LAUNCHER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER,
    },
    "officer_adjudicator": {
        "user_id": OFFICER_ADJUDICATOR_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER,
    },
    "officer_second_approver": {
        "user_id": OFFICER_SECOND_APPROVER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER,
    },
    "officer_auditor": {
        "user_id": OFFICER_AUDITOR_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER,
    },
}


# ---------------------------------------------------------------------------
# Header builders
# ---------------------------------------------------------------------------


def make_platform_admin_headers(
    user_id: str = PLATFORM_ADMIN_USER_ID,
) -> Headers:
    """Headers for a PlatformAdmin."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN)


def make_campaign_manager_headers(
    user_id: str = CAMPAIGN_MANAGER_USER_ID,
) -> Headers:
    """Headers for a CampaignManager."""
    return build_user_headers(user_id, UserRole.CAMPAIGN_MANAGER)


def make_dialer_operator_headers(
    user_id: str = DIALER_OPERATOR_USER_ID,
) -> Headers:
    """Headers for a DialerOperator."""
    return build_user_headers(user_id, UserRole.DIALER_OPERATOR)


def make_compliance_officer_headers(user_id: str = OFFICER_USER_ID) -> Headers:
    """Headers for a ComplianceOfficer acting under the given identity."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER)


def make_consumer_headers(contact_id: str) -> Headers:
    """Headers for a Consumer.

    The consumer's user identifier is the identifier of that consumer's own
    ``Contact`` row, so this builder must be handed a contact identifier.
    """
    return build_user_headers(contact_id, UserRole.CONSUMER)


def make_headers(user_id: str, role: str) -> Headers:
    """Headers for an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)


# Convenience singletons for the identities that recur throughout the suite.
def make_officer_script_approver_headers() -> Headers:
    """Headers for the officer who approves agent scripts."""
    return make_compliance_officer_headers(OFFICER_SCRIPT_APPROVER_USER_ID)


def make_officer_profile_approver_headers() -> Headers:
    """Headers for the officer who approves dialer profiles."""
    return make_compliance_officer_headers(OFFICER_PROFILE_APPROVER_USER_ID)


def make_officer_launcher_headers() -> Headers:
    """Headers for the officer who certifies campaign launches."""
    return make_compliance_officer_headers(OFFICER_LAUNCHER_USER_ID)


def make_officer_adjudicator_headers() -> Headers:
    """Headers for the officer who adjudicates complaints."""
    return make_compliance_officer_headers(OFFICER_ADJUDICATOR_USER_ID)
