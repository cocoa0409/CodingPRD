"""Header builders for the five declared roles.

Two of the five roles are opaque operator identities, so a constant header
dict is enough for them.  The other three carry the ``id`` of a persisted row
in ``X-User-ID``, so a test must mint their headers from the entity it just
created — never from a shared constant — or ownership and identity checks
cannot be exercised faithfully.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_MENTOR,
    ROLE_NOVICE_TEACHER,
    ROLE_PROGRAM_ADMIN,
    ROLE_SITE_INDUCTION_LEAD,
    ROLE_STATE_OFFICER,
)

# --- Opaque operator identifiers ----------------------------------------
# For ProgramAdmin and StateCredentialingOfficer, X-User-ID is an operator
# identifier not tied to any persisted entity.  Several distinct identifiers
# are needed because four operations refuse a caller who produced the
# evidence being judged.
PROGRAM_OFFICE_1 = "u-program-office-1"
PROGRAM_OFFICE_2 = "u-program-office-2"
PREPARER_1 = "u-preparer-1"
APPROVER_1 = "u-approver-1"
PAYROLL_PREP_1 = "u-payroll-prep-1"
STATE_OFFICER_1 = "u-state-officer-1"
STATE_OFFICER_2 = "u-state-officer-2"

ADMIN = build_user_headers(PROGRAM_OFFICE_1, ROLE_PROGRAM_ADMIN)
ADMIN_2 = build_user_headers(PROGRAM_OFFICE_2, ROLE_PROGRAM_ADMIN)
PREPARER = build_user_headers(PREPARER_1, ROLE_PROGRAM_ADMIN)
APPROVER = build_user_headers(APPROVER_1, ROLE_PROGRAM_ADMIN)
PAYROLL_PREP = build_user_headers(PAYROLL_PREP_1, ROLE_PROGRAM_ADMIN)
STATE_OFFICER = build_user_headers(STATE_OFFICER_1, ROLE_STATE_OFFICER)
STATE_OFFICER_ALT = build_user_headers(STATE_OFFICER_2, ROLE_STATE_OFFICER)


def make_admin_headers(user_id: str = PROGRAM_OFFICE_1) -> dict:
    """ProgramAdmin headers under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_state_officer_headers(user_id: str = STATE_OFFICER_1) -> dict:
    """StateCredentialingOfficer headers under an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_STATE_OFFICER)


def make_site_lead_headers(site_id: str) -> dict:
    """SiteInductionLead headers whose X-User-ID is the acting Site's id."""
    return build_user_headers(site_id, ROLE_SITE_INDUCTION_LEAD)


def make_mentor_headers(mentor_id: str) -> dict:
    """Mentor headers whose X-User-ID is the acting Mentor's id."""
    return build_user_headers(mentor_id, ROLE_MENTOR)


def make_novice_headers(novice_id: str) -> dict:
    """NoviceTeacher headers whose X-User-ID is the acting NoviceTeacher's id."""
    return build_user_headers(novice_id, ROLE_NOVICE_TEACHER)


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role string, including undeclared ones."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = PROGRAM_OFFICE_1) -> dict:
    """Headers carrying an identity but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = PROGRAM_OFFICE_1) -> dict:
    """Headers carrying an empty X-User-Role."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_without_user_id(role: str) -> dict:
    """Headers carrying a role but no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
