"""Pre-built role headers for every role in the PRD (§2.1).

Five of the seven roles are opaque operator identities, so a shared constant is
the canonical form for them. `Applicant` and `Contractor` are entity-backed:
`X-User-ID` is the id of the acting row, so ownership-gated calls MUST use the
per-instance builders below with the real entity id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used throughout the fixtures.
INTAKE_SPECIALIST_USER_ID = "is-1"
REHAB_SPECIALIST_USER_ID = "rs-1"
SECOND_REHAB_SPECIALIST_USER_ID = "rs-2"
INSPECTOR_USER_ID = "insp-1"
SECOND_INSPECTOR_USER_ID = "insp-2"
LOAN_OFFICER_USER_ID = "lo-1"
PROGRAM_MANAGER_USER_ID = "pm-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque operator roles — the shared constant is the canonical form.
    "intake_specialist_headers": build_user_headers(
        INTAKE_SPECIALIST_USER_ID, "IntakeSpecialist"
    ),
    "rehab_specialist_headers": build_user_headers(
        REHAB_SPECIALIST_USER_ID, "RehabSpecialist"
    ),
    "second_rehab_specialist_headers": build_user_headers(
        SECOND_REHAB_SPECIALIST_USER_ID, "RehabSpecialist"
    ),
    "inspector_headers": build_user_headers(INSPECTOR_USER_ID, "Inspector"),
    "second_inspector_headers": build_user_headers(
        SECOND_INSPECTOR_USER_ID, "Inspector"
    ),
    "loan_officer_headers": build_user_headers(LOAN_OFFICER_USER_ID, "LoanOfficer"),
    "program_manager_headers": build_user_headers(
        PROGRAM_MANAGER_USER_ID, "ProgramManager"
    ),
    # Entity-backed roles — these shared constants are only for tests that do
    # not exercise ownership (role-authorization and 404 probes).
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_applicant_headers(user_id: str) -> Dict[str, str]:
    """For the entity-backed `Applicant` role: pass the acting Applicant row's id."""
    return build_user_headers(user_id, "Applicant")


def make_contractor_headers(user_id: str) -> Dict[str, str]:
    """For the entity-backed `Contractor` role: pass the acting Contractor row's id."""
    return build_user_headers(user_id, "Contractor")


def make_intake_specialist_headers(user_id: str) -> Dict[str, str]:
    """Opaque operator identity for an `IntakeSpecialist`."""
    return build_user_headers(user_id, "IntakeSpecialist")


def make_rehab_specialist_headers(user_id: str) -> Dict[str, str]:
    """Opaque operator identity for a `RehabSpecialist`."""
    return build_user_headers(user_id, "RehabSpecialist")


def make_inspector_headers(user_id: str) -> Dict[str, str]:
    """Opaque operator identity for an `Inspector`."""
    return build_user_headers(user_id, "Inspector")


def make_loan_officer_headers(user_id: str) -> Dict[str, str]:
    """Opaque operator identity for a `LoanOfficer`."""
    return build_user_headers(user_id, "LoanOfficer")


def make_program_manager_headers(user_id: str) -> Dict[str, str]:
    """Opaque operator identity for a `ProgramManager`."""
    return build_user_headers(user_id, "ProgramManager")


ALL_ROLE_NAMES = [
    "Applicant",
    "Contractor",
    "IntakeSpecialist",
    "RehabSpecialist",
    "Inspector",
    "LoanOfficer",
    "ProgramManager",
]

# Every operator role that may read a collection endpoint (PRD §4).
OPERATOR_READ_HEADERS = [
    TEST_USERS["intake_specialist_headers"],
    TEST_USERS["rehab_specialist_headers"],
    TEST_USERS["inspector_headers"],
    TEST_USERS["loan_officer_headers"],
    TEST_USERS["program_manager_headers"],
]
