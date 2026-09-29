"""Pre-built request headers for each role.

Operator roles carry an opaque ``X-User-ID`` that is never compared to any
entity id. The two entity-backed roles must carry the id of the row they act
as, so their headers are always built per call site.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers used throughout the suite.
PROGRAM_DIRECTOR_USER_ID = "pd-1"
INTAKE_SPECIALIST_USER_ID = "intake-1"
SECOND_INTAKE_SPECIALIST_USER_ID = "intake-2"
JOB_COACH_USER_ID = "coach-1"
SECOND_JOB_COACH_USER_ID = "coach-2"
CASE_MANAGER_USER_ID = "cm-1"
SECOND_CASE_MANAGER_USER_ID = "cm-2"
FUNDER_ANALYST_USER_ID = "funder-1"
SUPERVISOR_USER_ID = "sup-1"


def make_program_director_headers(user_id: str = PROGRAM_DIRECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PROGRAM_DIRECTOR)


def make_intake_specialist_headers(
    user_id: str = INTAKE_SPECIALIST_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.INTAKE_SPECIALIST)


def make_job_coach_headers(user_id: str = JOB_COACH_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.JOB_COACH)


def make_case_manager_headers(user_id: str = CASE_MANAGER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.CASE_MANAGER)


def make_funder_analyst_headers(user_id: str = FUNDER_ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.FUNDER_ANALYST)


def make_referral_partner_headers(referral_partner_id: str) -> Dict[str, str]:
    """Headers for the acting ReferralPartner row, whose id is X-User-ID."""
    return build_user_headers(referral_partner_id, Role.REFERRAL_PARTNER)


def make_employer_partner_headers(employer_id: str) -> Dict[str, str]:
    """Headers for the acting Employer row, whose id is X-User-ID."""
    return build_user_headers(employer_id, Role.EMPLOYER_PARTNER)


PROGRAM_DIRECTOR = make_program_director_headers()
INTAKE_SPECIALIST = make_intake_specialist_headers()
JOB_COACH = make_job_coach_headers()
CASE_MANAGER = make_case_manager_headers()
FUNDER_ANALYST = make_funder_analyst_headers()

# Only the five operator roles have a stable, entity-independent identity.
TEST_USERS = {
    Role.PROGRAM_DIRECTOR: PROGRAM_DIRECTOR,
    Role.INTAKE_SPECIALIST: INTAKE_SPECIALIST,
    Role.JOB_COACH: JOB_COACH,
    Role.CASE_MANAGER: CASE_MANAGER,
    Role.FUNDER_ANALYST: FUNDER_ANALYST,
}


def headers_without_role(user_id: str = PROGRAM_DIRECTOR_USER_ID) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = Role.PROGRAM_DIRECTOR) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(
    role: str = "Auditor", user_id: str = PROGRAM_DIRECTOR_USER_ID
) -> Dict[str, str]:
    """Headers whose X-User-Role is not one of the seven declared roles."""
    return build_user_headers(user_id, role)
