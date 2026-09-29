"""Role headers.

Per PRD 2.1, `ProgramAdmin`, `QualityCoordinator` and `Surveyor` carry an opaque
`X-User-ID` that is never compared to any entity id, so fixed constants are fine.
`LabDirector` and `Operator` carry the `id` of the acting `Operator` row, so those
headers must be built per operator with `make_operator_headers()` /
`make_lab_director_headers()`.
"""

from prd_bench_local_runner.testing import build_user_headers

PROGRAM_ADMIN_USER_ID = "program-admin-1"
QUALITY_COORDINATOR_USER_ID = "quality-coordinator-1"
SURVEYOR_ALPHA_USER_ID = "surveyor-alpha"
SURVEYOR_BETA_USER_ID = "surveyor-beta"

TEST_USERS = {
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_USER_ID, "ProgramAdmin"),
    "quality_coordinator_headers": build_user_headers(
        QUALITY_COORDINATOR_USER_ID, "QualityCoordinator"
    ),
    "surveyor_headers": build_user_headers(SURVEYOR_ALPHA_USER_ID, "Surveyor"),
    "surveyor_beta_headers": build_user_headers(SURVEYOR_BETA_USER_ID, "Surveyor"),
}


def make_operator_headers(operator_id: str) -> dict:
    """Headers for an `Operator` actor whose X-User-ID is that operator row's id."""
    return build_user_headers(operator_id, "Operator")


def make_lab_director_headers(operator_id: str) -> dict:
    """Headers for a `LabDirector` actor whose X-User-ID is that operator row's id."""
    return build_user_headers(operator_id, "LabDirector")


def make_surveyor_headers(user_id: str) -> dict:
    """Headers for a `Surveyor` actor with an arbitrary opaque identifier."""
    return build_user_headers(user_id, "Surveyor")
