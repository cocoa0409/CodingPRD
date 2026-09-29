"""Pre-built request headers for each role in the PRD's access-control model.

PRD §2.1: nine of the eleven roles carry an opaque identifier that the server
only records. The remaining two are entity-backed: a ChainAdmin's
``X-User-ID`` is the acting ChainAccount id, and a ServicePartnerUser's
``X-User-ID`` is the acting ServicePartner id. For those two roles the tests
must build headers from the row that was actually created, which is what
``make_chain_admin_headers`` and ``make_service_partner_headers`` are for.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque user identifiers used consistently across the suite.
COMPLIANCE_ENGINEER_USER_ID = "ce-1"
LISTING_REVIEWER_USER_ID = "lr-1"
APPLICATION_ENGINEER_USER_ID = "eng-1"
ENGINEERING_APPROVER_USER_ID = "appr-1"
PRODUCTION_PLANNER_USER_ID = "pp-1"
CONNECTED_OPS_ENGINEER_USER_ID = "ops-1"
CHANNEL_MANAGER_USER_ID = "chm-1"
WARRANTY_ADJUDICATOR_USER_ID = "wad-1"
PLATFORM_ADMIN_USER_ID = "admin-1"


TEST_USERS: dict[str, dict[str, str]] = {
    "compliance_engineer": build_user_headers(
        COMPLIANCE_ENGINEER_USER_ID, UserRole.COMPLIANCE_ENGINEER.value
    ),
    "listing_reviewer": build_user_headers(
        LISTING_REVIEWER_USER_ID, UserRole.LISTING_REVIEWER.value
    ),
    "application_engineer": build_user_headers(
        APPLICATION_ENGINEER_USER_ID, UserRole.APPLICATION_ENGINEER.value
    ),
    "engineering_approver": build_user_headers(
        ENGINEERING_APPROVER_USER_ID, UserRole.ENGINEERING_APPROVER.value
    ),
    "production_planner": build_user_headers(
        PRODUCTION_PLANNER_USER_ID, UserRole.PRODUCTION_PLANNER.value
    ),
    "connected_ops_engineer": build_user_headers(
        CONNECTED_OPS_ENGINEER_USER_ID, UserRole.CONNECTED_OPS_ENGINEER.value
    ),
    "channel_manager": build_user_headers(
        CHANNEL_MANAGER_USER_ID, UserRole.CHANNEL_MANAGER.value
    ),
    "warranty_adjudicator": build_user_headers(
        WARRANTY_ADJUDICATOR_USER_ID, UserRole.WARRANTY_ADJUDICATOR.value
    ),
    "platform_admin": build_user_headers(
        PLATFORM_ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value
    ),
}


def make_chain_admin_headers(chain_account_id: str) -> dict[str, str]:
    """Headers for a ChainAdmin acting on behalf of ``chain_account_id``."""
    return build_user_headers(chain_account_id, UserRole.CHAIN_ADMIN.value)


def make_service_partner_headers(service_partner_id: str) -> dict[str, str]:
    """Headers for a ServicePartnerUser acting as ``service_partner_id``."""
    return build_user_headers(service_partner_id, UserRole.SERVICE_PARTNER_USER.value)


def make_headers(user_id: str, role: str) -> dict[str, str]:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def make_compliance_engineer_headers(user_id: str) -> dict[str, str]:
    return build_user_headers(user_id, UserRole.COMPLIANCE_ENGINEER.value)


def make_listing_reviewer_headers(user_id: str) -> dict[str, str]:
    return build_user_headers(user_id, UserRole.LISTING_REVIEWER.value)


def make_application_engineer_headers(user_id: str) -> dict[str, str]:
    return build_user_headers(user_id, UserRole.APPLICATION_ENGINEER.value)


def make_engineering_approver_headers(user_id: str) -> dict[str, str]:
    return build_user_headers(user_id, UserRole.ENGINEERING_APPROVER.value)
