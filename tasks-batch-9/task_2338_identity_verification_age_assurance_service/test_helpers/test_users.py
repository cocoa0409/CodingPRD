"""Pre-built role headers for every role the PRD defines.

``ClientIntegrator`` is the only role whose ``X-User-ID`` is the id of a
persisted entity — it is the acting ``Client``'s ``id``. Every ownership-gated
call therefore MUST use ``make_client_integrator_headers(client["id"])``. The
shared ``TEST_USERS`` entry for that role is only safe where the request is
expected to fail before any ownership comparison (missing headers, unknown
role) or where no client resource is involved.

The other five roles carry opaque operator identifiers that the server merely
records, so their shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers reused across fixtures.
ADMIN_USER_ID = "admin-1"
COMPLIANCE_OFFICER_USER_ID = "co-1"
SECOND_COMPLIANCE_OFFICER_USER_ID = "co-2"
REVIEW_MANAGER_USER_ID = "rm-1"
SECOND_REVIEW_MANAGER_USER_ID = "rm-2"
MANUAL_REVIEWER_USER_ID = "mr-1"
SECOND_MANUAL_REVIEWER_USER_ID = "mr-2"
INCLUSION_REVIEWER_USER_ID = "ir-1"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "second_compliance_officer_headers": build_user_headers(
        SECOND_COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "review_manager_headers": build_user_headers(REVIEW_MANAGER_USER_ID, "ReviewManager"),
    "second_review_manager_headers": build_user_headers(
        SECOND_REVIEW_MANAGER_USER_ID, "ReviewManager"
    ),
    "manual_reviewer_headers": build_user_headers(MANUAL_REVIEWER_USER_ID, "ManualReviewer"),
    "second_manual_reviewer_headers": build_user_headers(
        SECOND_MANUAL_REVIEWER_USER_ID, "ManualReviewer"
    ),
    "inclusion_reviewer_headers": build_user_headers(
        INCLUSION_REVIEWER_USER_ID, "InclusionReviewer"
    ),
    # Fallback only — never use for an ownership-gated call.
    "client_integrator_headers": build_user_headers("test-client-integrator-1", "ClientIntegrator"),
}


def make_client_integrator_headers(client_id: str) -> dict:
    """Headers for a ClientIntegrator acting on its own traffic.

    ``client_id`` must be the acting Client's ``id`` because ownership checks
    compare the target resource's client reference against ``X-User-ID``.
    """
    return build_user_headers(client_id, "ClientIntegrator")


def make_platform_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_review_manager_headers(user_id: str = REVIEW_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "ReviewManager")


def make_manual_reviewer_headers(user_id: str = MANUAL_REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "ManualReviewer")


def make_inclusion_reviewer_headers(user_id: str = INCLUSION_REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "InclusionReviewer")
