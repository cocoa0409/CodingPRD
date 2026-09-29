"""Pre-built role headers for every role named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Six of the seven roles carry an opaque identity, so a shared constant is the
# canonical form for them. PlantSupervisor is entity-backed: use the builder
# below with the acting Supervisor row's id.
TEST_USERS = {
    "director_headers": build_user_headers("user-director-1", "LaborRelationsDirector"),
    "director_two_headers": build_user_headers("user-director-2", "LaborRelationsDirector"),
    "analyst_headers": build_user_headers("user-analyst-1", "HRDataAnalyst"),
    "counsel_headers": build_user_headers("user-counsel-1", "EmploymentCounsel"),
    "counsel_two_headers": build_user_headers("user-counsel-2", "EmploymentCounsel"),
    "trainer_headers": build_user_headers("user-trainer-1", "SupervisorTrainer"),
    "board_headers": build_user_headers("user-board-1", "BoardAgent"),
    "union_headers": build_user_headers("user-union-1", "UnionRepresentative"),
    # Fallback for PlantSupervisor tests that do not exercise self-scoping.
    "supervisor_headers": build_user_headers("user-supervisor-1", "PlantSupervisor"),
}

DIRECTOR = TEST_USERS["director_headers"]
DIRECTOR_TWO = TEST_USERS["director_two_headers"]
ANALYST = TEST_USERS["analyst_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
COUNSEL_TWO = TEST_USERS["counsel_two_headers"]
TRAINER = TEST_USERS["trainer_headers"]
BOARD = TEST_USERS["board_headers"]
UNION = TEST_USERS["union_headers"]


def make_plant_supervisor_headers(supervisor_id: str) -> dict:
    """Headers for a PlantSupervisor acting as themselves.

    PlantSupervisor identity is the id of the acting Supervisor row, so pass the
    real Supervisor.id whenever the call is self-scoped.
    """
    return build_user_headers(supervisor_id, "PlantSupervisor")


def make_director_headers(user_id: str) -> dict:
    """Headers for a LaborRelationsDirector with a caller-chosen user identity."""
    return build_user_headers(user_id, "LaborRelationsDirector")


def make_counsel_headers(user_id: str) -> dict:
    """Headers for EmploymentCounsel with a caller-chosen user identity.

    Used by the segregation-of-duties rule, where the reviewing user identity
    must differ from the recorded message author.
    """
    return build_user_headers(user_id, "EmploymentCounsel")


def make_headers(user_id: str, role: str) -> dict:
    return build_user_headers(user_id, role)
