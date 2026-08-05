"""Pre-built role headers for every role in the PRD (§2.1).

Header role strings are spelled exactly: Recruiter, AccountManager,
CredentialingCoordinator, ClientContact, PlatformAdmin.

Four roles are entity-backed: Recruiter/AccountManager/CredentialingCoordinator
are backed by a StaffUser id, and ClientContact is backed by a Client id. For
ownership-gated calls the X-User-ID MUST be the real backing entity's id, so use
the per-instance builders below. The shared TEST_USERS constants are only for
tests whose success does not depend on the caller owning the subject resource
(e.g. 401/403/404 checks and PlatformAdmin's opaque provisioning role).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "recruiter_headers": build_user_headers("test-recruiter-1", "Recruiter"),
    "account_manager_headers": build_user_headers("test-am-1", "AccountManager"),
    "credentialing_coordinator_headers": build_user_headers(
        "test-coord-1", "CredentialingCoordinator"
    ),
    "client_contact_headers": build_user_headers("test-client-1", "ClientContact"),
}


def make_recruiter_headers(user_id: str) -> dict:
    """For Recruiter (entity_backed:StaffUser). Pass the acting recruiter's
    StaffUser.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Recruiter")


def make_account_manager_headers(user_id: str) -> dict:
    """For AccountManager (entity_backed:StaffUser). Pass the acting AM's
    StaffUser.id; also the id compared by the fee-waive four-eyes control."""
    return build_user_headers(user_id, "AccountManager")


def make_credentialing_coordinator_headers(user_id: str) -> dict:
    """For CredentialingCoordinator (entity_backed:StaffUser)."""
    return build_user_headers(user_id, "CredentialingCoordinator")


def make_client_contact_headers(client_id: str) -> dict:
    """For ClientContact (entity_backed:Client). Pass the Client.id the contact
    represents; ownership on openings/applications/offers compares this id."""
    return build_user_headers(client_id, "ClientContact")


def make_platform_admin_headers(user_id: str = "platform-admin-1") -> dict:
    """For PlatformAdmin (opaque)."""
    return build_user_headers(user_id, "PlatformAdmin")
