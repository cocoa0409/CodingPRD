"""Pre-built role headers for every role in the PRD (§2.1).

Four roles carry an opaque operator identifier that the server never
compares to any entity id: ProgramDirector, RosterCoordinator,
CurriculumSpecialist and FiscalOfficer. For those, the shared constant is
the canonical form.

Two roles are entity-backed and their X-User-ID *is* an entity id:
TeachingArtist (the acting TeachingArtist.id) and SchoolLiaison (the
acting SchoolPartner.id). Ownership-gated calls for those two roles MUST
use the per-instance builders below, passing the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable opaque operator identifiers used across the suite.
PROGRAM_DIRECTOR_USER_ID = "program-director-1"
ROSTER_COORDINATOR_USER_ID = "roster-coordinator-1"
CURRICULUM_SPECIALIST_USER_ID = "curriculum-specialist-1"
FISCAL_OFFICER_USER_ID = "fiscal-officer-1"

# Distinct operator identities used for segregation-of-duties scenarios.
PROGRAM_DIRECTOR_USER_ID_ALT = "program-director-2"
FISCAL_OFFICER_USER_ID_ALT = "fiscal-officer-2"
PANELIST_1_USER_ID = "panelist-1"
PANELIST_2_USER_ID = "panelist-2"
DEMO_EVALUATOR_USER_ID = "demo-evaluator-1"
OBSERVER_USER_ID = "observer-1"

TEST_USERS = {
    # Opaque roles — the shared constant is canonical.
    "program_director_headers": build_user_headers(
        PROGRAM_DIRECTOR_USER_ID, "ProgramDirector"
    ),
    "roster_coordinator_headers": build_user_headers(
        ROSTER_COORDINATOR_USER_ID, "RosterCoordinator"
    ),
    "curriculum_specialist_headers": build_user_headers(
        CURRICULUM_SPECIALIST_USER_ID, "CurriculumSpecialist"
    ),
    "fiscal_officer_headers": build_user_headers(
        FISCAL_OFFICER_USER_ID, "FiscalOfficer"
    ),
    # Entity-backed roles — fallback for tests that do NOT exercise ownership
    # (bad payload, missing resource, role-permission checks).
    "teaching_artist_headers": build_user_headers(
        "test-teaching-artist-1", "TeachingArtist"
    ),
    "school_liaison_headers": build_user_headers(
        "test-school-liaison-1", "SchoolLiaison"
    ),
}

ROLE_HEADER_KEYS = {
    "ProgramDirector": "program_director_headers",
    "RosterCoordinator": "roster_coordinator_headers",
    "CurriculumSpecialist": "curriculum_specialist_headers",
    "TeachingArtist": "teaching_artist_headers",
    "SchoolLiaison": "school_liaison_headers",
    "FiscalOfficer": "fiscal_officer_headers",
}


# --------------------------------------------------------------------------
# Per-instance builders — mandatory for the two entity-backed roles.
# --------------------------------------------------------------------------
def make_teaching_artist_headers(artist_id: str) -> dict:
    """For TeachingArtist. Pass the real TeachingArtist.id: the PRD says
    X-User-ID is the id of the acting TeachingArtist and ownership checks
    compare a session's assigned_artist_id, a lesson plan's
    author_artist_id and a voucher's teaching_artist_id against it."""
    return build_user_headers(artist_id, "TeachingArtist")


def make_school_liaison_headers(school_partner_id: str) -> dict:
    """For SchoolLiaison. Pass the real SchoolPartner.id: the PRD says
    X-User-ID is the id of the acting SchoolPartner and ownership checks
    compare the host school of the residency behind the addressed
    resource against it."""
    return build_user_headers(school_partner_id, "SchoolLiaison")


def make_program_director_headers(user_id: str) -> dict:
    """For ProgramDirector with a chosen opaque operator identifier."""
    return build_user_headers(user_id, "ProgramDirector")


def make_roster_coordinator_headers(user_id: str) -> dict:
    """For RosterCoordinator with a chosen opaque operator identifier."""
    return build_user_headers(user_id, "RosterCoordinator")


def make_curriculum_specialist_headers(user_id: str) -> dict:
    """For CurriculumSpecialist with a chosen opaque operator identifier."""
    return build_user_headers(user_id, "CurriculumSpecialist")


def make_fiscal_officer_headers(user_id: str) -> dict:
    """For FiscalOfficer with a chosen opaque operator identifier."""
    return build_user_headers(user_id, "FiscalOfficer")


def make_headers_for_role(role: str, user_id: str) -> dict:
    """Generic builder used by role-permission parametrizations."""
    return build_user_headers(user_id, role)
