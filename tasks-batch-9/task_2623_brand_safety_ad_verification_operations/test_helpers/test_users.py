"""Pre-built caller headers for every role the PRD declares.

For the five opaque roles (PlatformAdmin, ClassificationAnalyst, DisputeOfficer,
AccreditationAuditor, MeasurementOperator) X-User-ID is an operator identifier
that is never compared to any entity id, so the shared constants below are the
canonical form. The two entity-backed roles (Advertiser, Publisher) must carry
the acting entity's own id, so every ownership-gated call uses the per-instance
builders instead.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable operator identities. Distinct identities matter for the
# segregation-of-duties rules: the analyst who authored or reviewed a
# classification may not decide the appeal against it, and the auditor who
# authored a methodology version may not conclude its audit.
ADMIN_USER_ID = "admin-1"
ANALYST_AUTHOR_USER_ID = "analyst-1"
ANALYST_REVIEWER_USER_ID = "analyst-2"
ANALYST_THIRD_USER_ID = "analyst-7"
OFFICER_USER_ID = "officer-1"
OFFICER_SECOND_USER_ID = "officer-2"
AUDITOR_AUTHOR_USER_ID = "auditor-1"
AUDITOR_CONCLUDER_USER_ID = "auditor-2"
OPERATOR_USER_ID = "op-1"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    # entity_backed roles: shared constants are a fallback for tests that do
    # not exercise ownership (bad payloads, missing resources, role lockouts).
    "advertiser_headers": build_user_headers("test-advertiser-1", "Advertiser"),
    "publisher_headers": build_user_headers("test-publisher-1", "Publisher"),
    "analyst_headers": build_user_headers(ANALYST_AUTHOR_USER_ID, "ClassificationAnalyst"),
    "analyst_reviewer_headers": build_user_headers(
        ANALYST_REVIEWER_USER_ID, "ClassificationAnalyst"
    ),
    "officer_headers": build_user_headers(OFFICER_USER_ID, "DisputeOfficer"),
    "officer_second_headers": build_user_headers(OFFICER_SECOND_USER_ID, "DisputeOfficer"),
    "auditor_headers": build_user_headers(AUDITOR_AUTHOR_USER_ID, "AccreditationAuditor"),
    "auditor_concluder_headers": build_user_headers(
        AUDITOR_CONCLUDER_USER_ID, "AccreditationAuditor"
    ),
    "operator_headers": build_user_headers(OPERATOR_USER_ID, "MeasurementOperator"),
}


# ---- per-instance builders: mandatory for the entity-backed roles ----------
def make_advertiser_headers(advertiser_id: str) -> dict:
    """Advertiser caller. X-User-ID must be the acting advertiser's own id."""
    return build_user_headers(advertiser_id, "Advertiser")


def make_publisher_headers(publisher_id: str) -> dict:
    """Publisher caller. X-User-ID must be the acting publisher's own id."""
    return build_user_headers(publisher_id, "Publisher")


# ---- opaque-role builders, for tests that need a specific operator identity -
def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_analyst_headers(user_id: str = ANALYST_AUTHOR_USER_ID) -> dict:
    return build_user_headers(user_id, "ClassificationAnalyst")


def make_officer_headers(user_id: str = OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "DisputeOfficer")


def make_auditor_headers(user_id: str = AUDITOR_AUTHOR_USER_ID) -> dict:
    return build_user_headers(user_id, "AccreditationAuditor")


def make_operator_headers(user_id: str = OPERATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "MeasurementOperator")


def make_headers(role: str, user_id: str) -> dict:
    """Arbitrary role/identity pair, for role-lockout and authentication tests."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> dict:
    """Headers naming a role but omitting X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = ADMIN_USER_ID) -> dict:
    """Headers omitting X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
