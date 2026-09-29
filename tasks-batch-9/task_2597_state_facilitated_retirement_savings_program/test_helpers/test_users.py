"""
Identities used by the test suite.

The API recognises exactly five roles. Three of them are opaque: a program
administrator, a compliance officer and a recordkeeper may carry any stable
identifier, so fixed header dicts are provided for them (several distinct
identifiers per role, because separation-of-duties rules compare the actor of
one step against the actor of another).

Two roles are entity backed. An employer acts with the `X-User-ID` of its own
employer row, and a participant acts with the `X-User-ID` of its own participant
row. Those identifiers only exist after the row has been created, so they are
always built inside the test through `make_employer_headers()` /
`make_participant_headers()`. Reusing a fixed constant for those two roles is
what produces spurious cross-tenant refusals.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers

# --- role names, exactly as the API expects them in X-User-Role ---------
ROLE_PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_RECORDKEEPER = "Recordkeeper"
ROLE_EMPLOYER = "Employer"
ROLE_PARTICIPANT = "Participant"

ALL_ROLES = [
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RECORDKEEPER,
    ROLE_EMPLOYER,
    ROLE_PARTICIPANT,
]

# --- opaque identities ---------------------------------------------------
ADMIN_USER_ID = "admin-1"
ADMIN_REVIEWER_USER_ID = "admin-reviewer-1"
OFFICER_A_USER_ID = "officer-a"
OFFICER_B_USER_ID = "officer-b"
OFFICER_C_USER_ID = "officer-c"
OFFICER_ASSESSOR_USER_ID = "officer-assessor-1"
RECORDKEEPER_USER_ID = "recordkeeper-1"
RECORDKEEPER_2_USER_ID = "recordkeeper-2"

# The actor the API records for anything it does on its own initiative.
SYSTEM_ACTOR = "SYSTEM"

ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMINISTRATOR)
ADMIN_REVIEWER = build_user_headers(ADMIN_REVIEWER_USER_ID, ROLE_PROGRAM_ADMINISTRATOR)
OFFICER = build_user_headers(OFFICER_A_USER_ID, ROLE_COMPLIANCE_OFFICER)
OFFICER_A = build_user_headers(OFFICER_A_USER_ID, ROLE_COMPLIANCE_OFFICER)
OFFICER_B = build_user_headers(OFFICER_B_USER_ID, ROLE_COMPLIANCE_OFFICER)
OFFICER_C = build_user_headers(OFFICER_C_USER_ID, ROLE_COMPLIANCE_OFFICER)
OFFICER_ASSESSOR = build_user_headers(OFFICER_ASSESSOR_USER_ID, ROLE_COMPLIANCE_OFFICER)
RECORDKEEPER = build_user_headers(RECORDKEEPER_USER_ID, ROLE_RECORDKEEPER)
RECORDKEEPER_2 = build_user_headers(RECORDKEEPER_2_USER_ID, ROLE_RECORDKEEPER)


# --- entity backed identities -------------------------------------------
def make_employer_headers(employer_id: str) -> Headers:
    """Headers for the employer whose own row is `employer_id`."""
    return build_user_headers(employer_id, ROLE_EMPLOYER)


def make_participant_headers(participant_id: str) -> Headers:
    """Headers for the participant whose own row is `participant_id`."""
    return build_user_headers(participant_id, ROLE_PARTICIPANT)


def make_headers(user_id: str, role: str) -> Headers:
    """Headers for an arbitrary identifier and role string."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Headers:
    """Headers that carry a role but no user identifier."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Headers:
    """Headers whose user identifier is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Headers:
    """Headers that carry a user identifier but no role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
