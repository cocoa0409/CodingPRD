"""Pre-built identity headers for every role the PRD declares.

Five of the six roles carry an opaque operator identifier, so a fixed canonical
user id per role is enough. ApplicantContact is different: its identity is the
Applicant row itself, so X-User-ID must be the real Applicant.id. Ownership
checks compare X-User-ID against the owning Applicant.id, therefore any
ApplicantContact call must be made with ``make_applicant_contact_headers()``
built from the applicant that was actually created, never with a placeholder.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --- canonical opaque operator identifiers ---------------------------------
REVIEWER_1 = "rev-1"
REVIEWER_2 = "rev-2"
AUDITOR_1 = "aud-1"
AUDITOR_2 = "aud-2"
DECISION_MAKER_1 = "dm-1"
DECISION_MAKER_2 = "dm-2"
LAB_TECH_1 = "lab-1"
LAB_TECH_2 = "lab-2"
ADMIN_1 = "admin-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "reviewer_headers": build_user_headers(REVIEWER_1, Role.CERTIFICATION_REVIEWER),
    "reviewer_2_headers": build_user_headers(REVIEWER_2, Role.CERTIFICATION_REVIEWER),
    "auditor_headers": build_user_headers(AUDITOR_1, Role.FIELD_AUDITOR),
    "auditor_2_headers": build_user_headers(AUDITOR_2, Role.FIELD_AUDITOR),
    "decision_maker_headers": build_user_headers(
        DECISION_MAKER_1, Role.CERTIFICATION_DECISION_MAKER
    ),
    "decision_maker_2_headers": build_user_headers(
        DECISION_MAKER_2, Role.CERTIFICATION_DECISION_MAKER
    ),
    "lab_technician_headers": build_user_headers(LAB_TECH_1, Role.LAB_TECHNICIAN),
    "lab_technician_2_headers": build_user_headers(LAB_TECH_2, Role.LAB_TECHNICIAN),
    "admin_headers": build_user_headers(ADMIN_1, Role.PROGRAM_ADMINISTRATOR),
}


def make_applicant_contact_headers(applicant_id: str) -> Dict[str, str]:
    """Headers for the ApplicantContact of ``applicant_id``.

    The ApplicantContact identity is backed by the Applicant entity, so the
    identifier in the header has to be the applicant's own id for ownership
    checks to resolve to that applicant.
    """
    return build_user_headers(applicant_id, Role.APPLICANT_CONTACT)


def make_reviewer_headers(user_id: str = REVIEWER_1) -> Dict[str, str]:
    """Headers for an arbitrary CertificationReviewer operator id."""
    return build_user_headers(user_id, Role.CERTIFICATION_REVIEWER)


def make_auditor_headers(user_id: str = AUDITOR_1) -> Dict[str, str]:
    """Headers for an arbitrary FieldAuditor operator id."""
    return build_user_headers(user_id, Role.FIELD_AUDITOR)


def make_decision_maker_headers(user_id: str = DECISION_MAKER_1) -> Dict[str, str]:
    """Headers for an arbitrary CertificationDecisionMaker operator id."""
    return build_user_headers(user_id, Role.CERTIFICATION_DECISION_MAKER)


def make_lab_technician_headers(user_id: str = LAB_TECH_1) -> Dict[str, str]:
    """Headers for an arbitrary LabTechnician operator id."""
    return build_user_headers(user_id, Role.LAB_TECHNICIAN)


def make_admin_headers(user_id: str = ADMIN_1) -> Dict[str, str]:
    """Headers for a ProgramAdministrator operator id."""
    return build_user_headers(user_id, Role.PROGRAM_ADMINISTRATOR)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Generic role/identifier header builder."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
