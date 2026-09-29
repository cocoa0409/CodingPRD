"""Role names, canonical staff user ids and pre-built auth header dicts.

Two roles are entity-backed: a FacilityAdmin's X-User-ID is a Facility id and a
Requester's X-User-ID is a Requester id.  Any call whose outcome depends on
ownership MUST use make_facility_admin_headers()/make_requester_headers() with
the real entity id rather than a placeholder from TEST_USERS.
"""

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------- role names
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_FACILITY_ADMIN = "FacilityAdmin"
ROLE_INTAKE_SPECIALIST = "IntakeSpecialist"
ROLE_RECORDS_ANALYST = "RecordsAnalyst"
ROLE_RELEASE_REVIEWER = "ReleaseReviewer"
ROLE_BILLING_CLERK = "BillingClerk"
ROLE_PRIVACY_OFFICER = "PrivacyOfficer"
ROLE_REQUESTER = "Requester"

ALL_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_FACILITY_ADMIN,
    ROLE_INTAKE_SPECIALIST,
    ROLE_RECORDS_ANALYST,
    ROLE_RELEASE_REVIEWER,
    ROLE_BILLING_CLERK,
    ROLE_PRIVACY_OFFICER,
    ROLE_REQUESTER,
]

# ---------------------------------------------------------------- opaque staff user ids
USER_ADMIN_1 = "u-admin-1"
USER_INTAKE_1 = "u-intake-1"
USER_INTAKE_2 = "u-intake-2"
USER_ANALYST_1 = "u-analyst-1"
USER_ANALYST_2 = "u-analyst-2"
USER_REVIEW_1 = "u-review-1"
USER_REVIEW_2 = "u-review-2"
USER_BILL_1 = "u-bill-1"
USER_BILL_2 = "u-bill-2"
USER_PRIVACY_1 = "u-privacy-1"
USER_PRIVACY_2 = "u-privacy-2"

# ---------------------------------------------------------------- header builders
def make_headers(user_id: str, role: str) -> dict:
    """Auth headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def make_facility_admin_headers(facility_id: str) -> dict:
    """FacilityAdmin acting as the facility it administers."""
    return build_user_headers(facility_id, ROLE_FACILITY_ADMIN)


def make_requester_headers(requester_id: str) -> dict:
    """Requester acting as the requesting party it is."""
    return build_user_headers(requester_id, ROLE_REQUESTER)


# ---------------------------------------------------------------- ready-made headers
PLATFORM_ADMIN = build_user_headers(USER_ADMIN_1, ROLE_PLATFORM_ADMIN)
INTAKE_1 = build_user_headers(USER_INTAKE_1, ROLE_INTAKE_SPECIALIST)
INTAKE_2 = build_user_headers(USER_INTAKE_2, ROLE_INTAKE_SPECIALIST)
ANALYST_1 = build_user_headers(USER_ANALYST_1, ROLE_RECORDS_ANALYST)
ANALYST_2 = build_user_headers(USER_ANALYST_2, ROLE_RECORDS_ANALYST)
REVIEWER_1 = build_user_headers(USER_REVIEW_1, ROLE_RELEASE_REVIEWER)
REVIEWER_2 = build_user_headers(USER_REVIEW_2, ROLE_RELEASE_REVIEWER)
BILLING_1 = build_user_headers(USER_BILL_1, ROLE_BILLING_CLERK)
BILLING_2 = build_user_headers(USER_BILL_2, ROLE_BILLING_CLERK)
PRIVACY_1 = build_user_headers(USER_PRIVACY_1, ROLE_PRIVACY_OFFICER)
PRIVACY_2 = build_user_headers(USER_PRIVACY_2, ROLE_PRIVACY_OFFICER)

# A ReleaseReviewer whose X-User-ID is the analyst who applied a redaction --
# correct role, wrong human.  Used for segregation-of-duties probes.
REVIEWER_AS_ANALYST_1 = build_user_headers(USER_ANALYST_1, ROLE_RELEASE_REVIEWER)
# A ReleaseReviewer whose X-User-ID is the intake specialist.
REVIEWER_AS_INTAKE_1 = build_user_headers(USER_INTAKE_1, ROLE_RELEASE_REVIEWER)
# A PrivacyOfficer whose X-User-ID is the officer who issued a denial.
PRIVACY_AS_PRIVACY_1 = PRIVACY_1

# Headers that carry a role but no user id at all.
NO_USER_ID_HEADERS = {"X-User-Role": ROLE_PLATFORM_ADMIN, "Content-Type": "application/json"}
EMPTY_USER_ID_HEADERS = build_user_headers("", ROLE_PLATFORM_ADMIN)

TEST_USERS = {
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN,
    ROLE_INTAKE_SPECIALIST: INTAKE_1,
    ROLE_RECORDS_ANALYST: ANALYST_1,
    ROLE_RELEASE_REVIEWER: REVIEWER_1,
    ROLE_BILLING_CLERK: BILLING_1,
    ROLE_PRIVACY_OFFICER: PRIVACY_1,
}
