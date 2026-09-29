"""Caller identities and the two header values every request carries (PRD §2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# ─── Role names ───────────────────────────────────────
ROLE_DEVELOPER = "Developer"
ROLE_SHPO_REVIEWER = "ShpoReviewer"
ROLE_NPS_REVIEWER = "NpsReviewer"
ROLE_COMPLIANCE_MONITOR = "ComplianceMonitor"
ROLE_INVESTOR_ADMIN = "InvestorAdmin"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = (
    ROLE_DEVELOPER,
    ROLE_SHPO_REVIEWER,
    ROLE_NPS_REVIEWER,
    ROLE_COMPLIANCE_MONITOR,
    ROLE_INVESTOR_ADMIN,
    ROLE_PLATFORM_ADMIN,
)

# Roles whose X-User-ID must be the id of a stored row of a particular entity.
# For these the header can only be built once the backing row exists, so tests
# use the make_*_headers builders below with the freshly created id.
ENTITY_BACKED_ROLES = {
    ROLE_DEVELOPER: "Developer",
    ROLE_SHPO_REVIEWER: "Reviewer",
    ROLE_NPS_REVIEWER: "Reviewer",
    ROLE_INVESTOR_ADMIN: "InvestorInterest",
}

# Roles whose X-User-ID is an opaque principal identifier that is never
# compared against stored data, so a fixed constant is always acceptable.
OPAQUE_ROLE_USER_IDS = {
    ROLE_COMPLIANCE_MONITOR: "monitor-user-0001",
    ROLE_PLATFORM_ADMIN: "platform-admin-0001",
}

COMPLIANCE_MONITOR_USER_ID = OPAQUE_ROLE_USER_IDS[ROLE_COMPLIANCE_MONITOR]
PLATFORM_ADMIN_USER_ID = OPAQUE_ROLE_USER_IDS[ROLE_PLATFORM_ADMIN]

# Placeholders for the entity-backed roles, used only where the endpoint refuses
# the request before it ever compares the identifier to stored data (role
# authorization, or a path id that does not resolve).
PLACEHOLDER_DEVELOPER_USER_ID = "11111111-1111-4111-8111-111111111111"
PLACEHOLDER_REVIEWER_USER_ID = "22222222-2222-4222-8222-222222222222"
PLACEHOLDER_INVESTOR_USER_ID = "33333333-3333-4333-8333-333333333333"


def make_developer_headers(developer_id):
    """Headers for a Developer acting as the developer row with this id."""
    return build_user_headers(str(developer_id), ROLE_DEVELOPER)


def make_shpo_reviewer_headers(reviewer_id):
    """Headers for a SHPO reviewer acting as the reviewer row with this id."""
    return build_user_headers(str(reviewer_id), ROLE_SHPO_REVIEWER)


def make_nps_reviewer_headers(reviewer_id):
    """Headers for an NPS reviewer acting as the reviewer row with this id."""
    return build_user_headers(str(reviewer_id), ROLE_NPS_REVIEWER)


def make_investor_admin_headers(investor_interest_id):
    """Headers for an InvestorAdmin acting as the interest row with this id."""
    return build_user_headers(str(investor_interest_id), ROLE_INVESTOR_ADMIN)


def make_compliance_monitor_headers(user_id=COMPLIANCE_MONITOR_USER_ID):
    """Headers for a ComplianceMonitor, whose identifier is opaque."""
    return build_user_headers(str(user_id), ROLE_COMPLIANCE_MONITOR)


def make_platform_admin_headers(user_id=PLATFORM_ADMIN_USER_ID):
    """Headers for a PlatformAdmin, whose identifier is opaque."""
    return build_user_headers(str(user_id), ROLE_PLATFORM_ADMIN)


def make_headers(role, user_id):
    """Headers for an arbitrary role/identifier pair."""
    return build_user_headers(str(user_id), role)


def make_headers_without_user_id(role):
    """Headers that declare a role but omit X-User-ID entirely (PRD §2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_with_empty_user_id(role):
    """Headers that supply X-User-ID as the empty string (PRD §2.1)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


TEST_USERS = {
    ROLE_COMPLIANCE_MONITOR: make_compliance_monitor_headers(),
    ROLE_PLATFORM_ADMIN: make_platform_admin_headers(),
    # Entity-backed placeholders; only for pre-identity rejections.
    ROLE_DEVELOPER: make_developer_headers(PLACEHOLDER_DEVELOPER_USER_ID),
    ROLE_SHPO_REVIEWER: make_shpo_reviewer_headers(PLACEHOLDER_REVIEWER_USER_ID),
    ROLE_NPS_REVIEWER: make_nps_reviewer_headers(PLACEHOLDER_REVIEWER_USER_ID),
    ROLE_INVESTOR_ADMIN: make_investor_admin_headers(PLACEHOLDER_INVESTOR_USER_ID),
}

MONITOR = TEST_USERS[ROLE_COMPLIANCE_MONITOR]
PLATFORM_ADMIN = TEST_USERS[ROLE_PLATFORM_ADMIN]
