"""Pre-built role headers for every role the program recognises (PRD 2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. ProgramAdmin, IntakeClerk and FinanceOfficer
# carry an X-User-ID that is never matched against an entity id, so the same
# constant is safe everywhere.
ADMIN_USER_ID = "admin-001"
ADMIN_ALT_USER_ID = "admin-002"
CLERK_USER_ID = "clerk-001"
FINANCE_USER_ID = "fin-001"
FINANCE_ALT_USER_ID = "fin-002"

TEST_USERS = {
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "program_admin_alt_headers": build_user_headers(ADMIN_ALT_USER_ID, "ProgramAdmin"),
    "intake_clerk_headers": build_user_headers(CLERK_USER_ID, "IntakeClerk"),
    "finance_officer_headers": build_user_headers(FINANCE_USER_ID, "FinanceOfficer"),
    "finance_officer_alt_headers": build_user_headers(FINANCE_ALT_USER_ID, "FinanceOfficer"),
    # Entity-backed roles: these shared constants are only safe for calls that
    # never touch an ownership or segregation-of-duties comparison.
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "property_owner_headers": build_user_headers("test-owner-1", "PropertyOwner"),
}


def make_supervisor_headers(officer_id: str) -> dict:
    """Supervisor acts with the acting Officer's id in X-User-ID."""
    return build_user_headers(officer_id, "Supervisor")


def make_inspector_headers(officer_id: str) -> dict:
    """Inspector acts with the acting Officer's id in X-User-ID."""
    return build_user_headers(officer_id, "Inspector")


def make_property_owner_headers(owner_id: str) -> dict:
    """PropertyOwner acts with the acting PropertyOwner record's id."""
    return build_user_headers(owner_id, "PropertyOwner")


def make_program_admin_headers(user_id: str) -> dict:
    """ProgramAdmin acting under an explicit operator identifier."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_finance_officer_headers(user_id: str) -> dict:
    """FinanceOfficer acting under an explicit operator identifier."""
    return build_user_headers(user_id, "FinanceOfficer")
