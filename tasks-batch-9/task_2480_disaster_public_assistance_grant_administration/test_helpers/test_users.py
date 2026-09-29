"""Pre-built role headers for every role named in the PRD.

`ApplicantAgent` is the one role whose identity is an actual `Applicant` row:
its `X-User-ID` must be the applicant's `id`, or every ownership check rejects
the request.  Use `make_applicant_agent_headers(applicant_id)` for anything
ownership-gated; the shared `TEST_USERS["applicant_agent_headers"]` constant is
only safe for calls that never resolve an owning applicant (missing-header and
unknown-role probes).
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable operator identifiers for the opaque roles.
ADMIN_USER_ID = "admin-1"
SPECIALIST_USER_ID = "spec-1"
GRANTS_OFFICER_USER_ID = "officer-1"
SECOND_GRANTS_OFFICER_USER_ID = "officer-2"
ADJUDICATOR_USER_ID = "adjudicator-1"
SECOND_ADJUDICATOR_USER_ID = "adjudicator-2"
AUDITOR_USER_ID = "auditor-1"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "specialist_headers": build_user_headers(SPECIALIST_USER_ID, "ProgramSpecialist"),
    "grants_officer_headers": build_user_headers(GRANTS_OFFICER_USER_ID, "GrantsOfficer"),
    "second_grants_officer_headers": build_user_headers(
        SECOND_GRANTS_OFFICER_USER_ID, "GrantsOfficer"
    ),
    "adjudicator_headers": build_user_headers(ADJUDICATOR_USER_ID, "AppealsAdjudicator"),
    "second_adjudicator_headers": build_user_headers(
        SECOND_ADJUDICATOR_USER_ID, "AppealsAdjudicator"
    ),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "StateAuditor"),
    # entity_backed role: fallback constant for non-ownership probes only.
    "applicant_agent_headers": build_user_headers("applicant-agent-1", "ApplicantAgent"),
}


def make_applicant_agent_headers(applicant_id: str) -> dict:
    """Headers for the agent of one specific applicant.

    Pass the real `Applicant.id`; the platform resolves the acting applicant
    from `X-User-ID`.
    """
    return build_user_headers(applicant_id, "ApplicantAgent")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_specialist_headers(user_id: str = SPECIALIST_USER_ID) -> dict:
    return build_user_headers(user_id, "ProgramSpecialist")


def make_grants_officer_headers(user_id: str = GRANTS_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "GrantsOfficer")


def make_adjudicator_headers(user_id: str = ADJUDICATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "AppealsAdjudicator")


def make_auditor_headers(user_id: str = AUDITOR_USER_ID) -> dict:
    return build_user_headers(user_id, "StateAuditor")
