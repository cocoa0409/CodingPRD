"""Identity headers for each role in the PRD's role list (PRD §2.1).

Every request carries `X-User-ID` and `X-User-Role`.  For a ReporterAgent the
`X-User-ID` must be the acting ReportingEntity's `id`, so reporter identities
can only be built once the entity exists -- hence the builder below rather
than a constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque identities: the user id is not resolved against any resource
# ---------------------------------------------------------------------------

PROGRAM_ADMIN = build_user_headers("admin-1", UserRole.PROGRAM_ADMIN.value)
MARKET_ANALYST = build_user_headers("analyst-1", UserRole.MARKET_ANALYST.value)
COMPLIANCE_AUDITOR = build_user_headers("auditor-1", UserRole.COMPLIANCE_AUDITOR.value)
PENALTY_OFFICER = build_user_headers("officer-1", UserRole.PENALTY_OFFICER.value)
PUBLIC_USER = build_user_headers("public-1", UserRole.PUBLIC_USER.value)

# Second holders of the audit and penalty roles.  Segregation of duties bars
# one user from taking both steps of a pair, so a distinct second identity is
# required to finish what the first one started.
COMPLIANCE_AUDITOR_2 = build_user_headers("auditor-2", UserRole.COMPLIANCE_AUDITOR.value)
PENALTY_OFFICER_2 = build_user_headers("officer-2", UserRole.PENALTY_OFFICER.value)
PROGRAM_ADMIN_2 = build_user_headers("admin-2", UserRole.PROGRAM_ADMIN.value)

TEST_USERS = {
    "ProgramAdmin": PROGRAM_ADMIN,
    "MarketAnalyst": MARKET_ANALYST,
    "ComplianceAuditor": COMPLIANCE_AUDITOR,
    "PenaltyOfficer": PENALTY_OFFICER,
    "PublicUser": PUBLIC_USER,
}


# ---------------------------------------------------------------------------
# Entity-backed identity: ReporterAgent
# ---------------------------------------------------------------------------


def reporter_agent(reporting_entity_id):
    """Headers for the ReporterAgent acting on behalf of one ReportingEntity."""
    return build_user_headers(reporting_entity_id, UserRole.REPORTER_AGENT.value)


def compliance_auditor(user_id):
    """Headers for a named ComplianceAuditor identity."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_AUDITOR.value)


def penalty_officer(user_id):
    """Headers for a named PenaltyOfficer identity."""
    return build_user_headers(user_id, UserRole.PENALTY_OFFICER.value)


def program_admin(user_id):
    """Headers for a named ProgramAdmin identity."""
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def market_analyst(user_id):
    """Headers for a named MarketAnalyst identity."""
    return build_user_headers(user_id, UserRole.MARKET_ANALYST.value)


def public_user(user_id):
    """Headers for a named PublicUser identity."""
    return build_user_headers(user_id, UserRole.PUBLIC_USER.value)


# ---------------------------------------------------------------------------
# Deliberately malformed identities, for the authentication gate
# ---------------------------------------------------------------------------

HEADERS_WITHOUT_ROLE = {
    "X-User-ID": "admin-1",
    "Content-Type": "application/json",
}

HEADERS_WITHOUT_USER_ID = {
    "X-User-Role": UserRole.PROGRAM_ADMIN.value,
    "Content-Type": "application/json",
}

HEADERS_UNRECOGNISED_ROLE = {
    "X-User-ID": "admin-1",
    "X-User-Role": "SupremeOverlord",
    "Content-Type": "application/json",
}
