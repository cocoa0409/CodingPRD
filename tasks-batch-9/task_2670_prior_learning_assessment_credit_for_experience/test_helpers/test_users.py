"""Request identities.

PRD S2.1: "Every request must carry two headers: ``X-User-ID``, identifying the
acting principal, and ``X-User-Role``, declaring the capacity in which that
principal is acting."

Three of the six roles are opaque operator identities whose ``X-User-ID`` "is an
opaque operator identifier not tied to any persisted entity", so a fixed string
is enough. The other three are entity-backed: ``Student`` and
``FacultyAssessor`` resolve ``X-User-ID`` to a real row's ``id``, and
``AppealReviewer`` resolves it to a ``FacultyAssessor`` row. Those must be built
per-row with the ``make_*_headers`` helpers below, because "The same error is
returned when the acting role is backed by a persisted entity and ``X-User-ID``
does not resolve to an existing row of that entity."
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --------------------------------------------------------------------------
# Opaque operator identities (PRD S2.1)
# --------------------------------------------------------------------------
COORDINATOR_USER_ID = "op-coordinator-001"
REGISTRAR_USER_ID = "op-registrar-001"
OFFICER_REVIEWER_USER_ID = "op-officer-reviewer-001"
OFFICER_APPROVER_USER_ID = "op-officer-approver-001"

COORDINATOR = build_user_headers(COORDINATOR_USER_ID, Role.PLA_COORDINATOR)
REGISTRAR = build_user_headers(REGISTRAR_USER_ID, Role.REGISTRAR)

# Segregation of duties within the ArticulationOfficer role (PRD S3.2) needs two
# distinct operator identifiers: the reviewer and a different approver.
OFFICER_REVIEWER = build_user_headers(OFFICER_REVIEWER_USER_ID, Role.ARTICULATION_OFFICER)
OFFICER_APPROVER = build_user_headers(OFFICER_APPROVER_USER_ID, Role.ARTICULATION_OFFICER)

# Convenience alias for the many officer calls that carry no duty constraint.
OFFICER = OFFICER_REVIEWER


# --------------------------------------------------------------------------
# Entity-backed identities (PRD S2.1)
# --------------------------------------------------------------------------
def make_student_headers(student_id: str) -> Dict[str, str]:
    """Headers for the ``Student`` whose row ``id`` is ``student_id``."""
    return build_user_headers(student_id, Role.STUDENT)


def make_assessor_headers(assessor_id: str) -> Dict[str, str]:
    """Headers for the ``FacultyAssessor`` whose row ``id`` is ``assessor_id``."""
    return build_user_headers(assessor_id, Role.FACULTY_ASSESSOR)


def make_reviewer_headers(assessor_id: str) -> Dict[str, str]:
    """Headers for an ``AppealReviewer`` backed by a ``FacultyAssessor`` row."""
    return build_user_headers(assessor_id, Role.APPEAL_REVIEWER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity, for RBAC probes that need an unexpected pairing."""
    return build_user_headers(user_id, role)


TEST_USERS = {
    "coordinator": COORDINATOR,
    "registrar": REGISTRAR,
    "officer_reviewer": OFFICER_REVIEWER,
    "officer_approver": OFFICER_APPROVER,
}
