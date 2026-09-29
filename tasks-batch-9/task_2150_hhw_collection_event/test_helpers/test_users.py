"""Pre-built request headers for every role in the contract.

Seven roles carry an opaque identity that is never resolved against a stored
row; `Resident` is the single exception, whose `X-User-ID` is the acting
resident's own `id`. Ownership-gated calls therefore MUST go through
`make_resident_headers(resident_id)`.

Two `ContainmentInspector` identities are kept apart on purpose: the inspector
who drives a site to APPROVED may not file that site's event-day inspections.
"""

from prd_bench_local_runner.testing import build_user_headers

# Distinct operator identities used by the segregation-of-duties rules.
SITE_APPROVER_USER_ID = "insp-site-approver"
EVENT_INSPECTOR_USER_ID = "insp-event-daily"
CONTRACTOR_USER_ID = "contractor-9"
TECH_USER_ID = "tech-77"

TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "event_coordinator_headers": build_user_headers(
        "test-coordinator-1", "EventCoordinator"
    ),
    # The day-of inspector: independent of the site approver above.
    "containment_inspector_headers": build_user_headers(
        EVENT_INSPECTOR_USER_ID, "ContainmentInspector"
    ),
    "site_approver_headers": build_user_headers(
        SITE_APPROVER_USER_ID, "ContainmentInspector"
    ),
    "eligibility_clerk_headers": build_user_headers("test-clerk-1", "EligibilityClerk"),
    # Shared Resident constant — safe only for calls that are not ownership-gated.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    "unload_tech_headers": build_user_headers(TECH_USER_ID, "UnloadTech"),
    "packing_contractor_headers": build_user_headers(
        CONTRACTOR_USER_ID, "PackingContractor"
    ),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}

ADMIN = TEST_USERS["program_admin_headers"]
COORDINATOR = TEST_USERS["event_coordinator_headers"]
INSPECTOR = TEST_USERS["containment_inspector_headers"]
SITE_APPROVER = TEST_USERS["site_approver_headers"]
CLERK = TEST_USERS["eligibility_clerk_headers"]
TECH = TEST_USERS["unload_tech_headers"]
CONTRACTOR = TEST_USERS["packing_contractor_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def make_resident_headers(resident_id: str) -> dict:
    """Headers for the acting Resident. Pass the resident's own `id`: ownership
    checks compare a resource's `resident_id` against this `X-User-ID`."""
    return build_user_headers(resident_id, "Resident")


def make_inspector_headers(user_id: str) -> dict:
    """Headers for a named ContainmentInspector identity."""
    return build_user_headers(user_id, "ContainmentInspector")


def make_contractor_headers(user_id: str) -> dict:
    """Headers for a named PackingContractor identity."""
    return build_user_headers(user_id, "PackingContractor")


def make_unload_tech_headers(user_id: str) -> dict:
    """Headers for a named UnloadTech identity."""
    return build_user_headers(user_id, "UnloadTech")


def make_admin_headers(user_id: str) -> dict:
    """Headers for a named ProgramAdmin identity."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_coordinator_headers(user_id: str) -> dict:
    """Headers for a named EventCoordinator identity."""
    return build_user_headers(user_id, "EventCoordinator")


def make_clerk_headers(user_id: str) -> dict:
    """Headers for a named EligibilityClerk identity."""
    return build_user_headers(user_id, "EligibilityClerk")
