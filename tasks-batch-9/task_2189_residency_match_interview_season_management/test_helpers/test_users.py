"""Identity headers for the eight roles declared by PRD §2.1.

Three roles are opaque — their caller identity is not a stored resource, so a
fixed user id is fine for every call:

  * ``NrmpAdmin``
  * ``ProgramCoordinator``
  * ``ComplianceOfficer``

Five roles are entity-backed — the caller id must be the ``id`` of a stored
resource, so tests must mint headers from the created entity:

  * ``ProgramDirector``, ``Reviewer``, ``Interviewer``, ``CommitteeMember``
    all resolve to a ``FacultyMember`` id
  * ``Applicant`` resolves to an ``Applicant`` id
"""

from prd_bench_local_runner.testing import build_user_headers

# ----------------------------------------------------------------------
# Opaque-role headers — safe to share across a whole test
# ----------------------------------------------------------------------
TEST_USERS = {
    "nrmp_admin_headers": build_user_headers("test-nrmp-admin-1", "NrmpAdmin"),
    "program_coordinator_headers": build_user_headers(
        "test-coordinator-1", "ProgramCoordinator"
    ),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
}

NRMP_ADMIN_HEADERS = TEST_USERS["nrmp_admin_headers"]
PROGRAM_COORDINATOR_HEADERS = TEST_USERS["program_coordinator_headers"]
COMPLIANCE_OFFICER_HEADERS = TEST_USERS["compliance_officer_headers"]


# ----------------------------------------------------------------------
# Entity-backed role headers — the user id must be a stored resource id
# ----------------------------------------------------------------------
def make_program_director_headers(faculty_member_id: str) -> dict:
    """Headers acting as the ``ProgramDirector`` who *is* this faculty member."""
    return build_user_headers(faculty_member_id, "ProgramDirector")


def make_reviewer_headers(faculty_member_id: str) -> dict:
    """Headers acting as the ``Reviewer`` who *is* this faculty member."""
    return build_user_headers(faculty_member_id, "Reviewer")


def make_interviewer_headers(faculty_member_id: str) -> dict:
    """Headers acting as the ``Interviewer`` who *is* this faculty member."""
    return build_user_headers(faculty_member_id, "Interviewer")


def make_committee_member_headers(faculty_member_id: str) -> dict:
    """Headers acting as the ``CommitteeMember`` who *is* this faculty member."""
    return build_user_headers(faculty_member_id, "CommitteeMember")


def make_applicant_headers(applicant_id: str) -> dict:
    """Headers acting as the ``Applicant`` who *is* this applicant record."""
    return build_user_headers(applicant_id, "Applicant")


# ----------------------------------------------------------------------
# Opaque-role header factories (for tests that need a distinct caller id)
# ----------------------------------------------------------------------
def make_nrmp_admin_headers(user_id: str = "test-nrmp-admin-1") -> dict:
    return build_user_headers(user_id, "NrmpAdmin")


def make_program_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "ProgramCoordinator")


def make_compliance_officer_headers(user_id: str = "test-compliance-officer-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
