"""Pre-built role headers for every role in the PRD.

FacultyProposer, CurriculumCommittee, FacultySenate, and Registrar are
opaque identities: X-User-ID is not tied to any persisted entity (though a
proposal's stored proposer_id is compared to X-User-ID by raw string
equality, so proposer calls must reuse the same user id string).
DepartmentChair is entity-backed: X-User-ID is the id of the acting
Department, so every ownership-gated chair call MUST be built with
make_chair_headers(<Department.id>).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    COMMITTEE_USER_ID,
    DEFAULT_PROPOSER_ID,
    REGISTRAR_USER_ID,
    SENATE_USER_ID,
)

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "proposer_headers": build_user_headers(DEFAULT_PROPOSER_ID, "FacultyProposer"),
    # entity_backed role: fallback for non-ownership tests only.
    "chair_headers": build_user_headers("test-chair-1", "DepartmentChair"),
    "committee_headers": build_user_headers(COMMITTEE_USER_ID, "CurriculumCommittee"),
    "senate_headers": build_user_headers(SENATE_USER_ID, "FacultySenate"),
    "registrar_headers": build_user_headers(REGISTRAR_USER_ID, "Registrar"),
}


def make_proposer_headers(user_id: str = DEFAULT_PROPOSER_ID) -> dict:
    """FacultyProposer is opaque, but a proposal's stored proposer_id is
    compared to X-User-ID by raw string equality — author operations must
    reuse the same user id that created the proposal."""
    return build_user_headers(user_id, "FacultyProposer")


def make_chair_headers(department_id: str) -> dict:
    """For DepartmentChair (entity-backed by Department). Pass the acting
    Department.id whenever the call is ownership-gated (dept-stage decisions,
    teach-out commit, cross-listing create/approve/reject/rescind)."""
    return build_user_headers(department_id, "DepartmentChair")


def make_committee_headers(user_id: str = COMMITTEE_USER_ID) -> dict:
    return build_user_headers(user_id, "CurriculumCommittee")


def make_senate_headers(user_id: str = SENATE_USER_ID) -> dict:
    return build_user_headers(user_id, "FacultySenate")


def make_registrar_headers(user_id: str = REGISTRAR_USER_ID) -> dict:
    return build_user_headers(user_id, "Registrar")
