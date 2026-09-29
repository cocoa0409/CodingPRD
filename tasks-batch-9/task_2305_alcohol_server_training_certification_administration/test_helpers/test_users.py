"""Pre-built role headers for every role the PRD declares.

Every request must carry two headers: X-User-ID, identifying the caller, and X-User-Role,
naming the caller's role. ProgramAdmin and StateRegulator identifiers are opaque operator
identifiers; Trainer, EmployerAdmin and AlcoholServer identifiers are the id of the acting
row, so ownership-gated calls must use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the two opaque operator roles, and for entity-backed roles
# only in tests that never reach an ownership check (bad payload, missing resource, or a
# role-authorisation refusal that precedes ownership).
TEST_USERS = {
    "program_admin_headers": build_user_headers("op-program-admin-1", "ProgramAdmin"),
    "state_regulator_headers": build_user_headers("op-state-regulator-1", "StateRegulator"),
    "trainer_headers": build_user_headers("unowned-trainer-1", "Trainer"),
    "employer_admin_headers": build_user_headers("unowned-employer-1", "EmployerAdmin"),
    "alcohol_server_headers": build_user_headers("unowned-server-1", "AlcoholServer"),
}


def make_program_admin_headers(user_id: str = "op-program-admin-1") -> dict:
    """ProgramAdmin: X-User-ID is an opaque operator identifier tied to no entity."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_state_regulator_headers(user_id: str = "op-state-regulator-1") -> dict:
    """StateRegulator: X-User-ID is an opaque operator identifier tied to no entity."""
    return build_user_headers(user_id, "StateRegulator")


def make_trainer_headers(trainer_id: str) -> dict:
    """Trainer: pass the acting Trainer row's id.

    Ownership checks compare the target resource's trainer reference to X-User-ID, so an
    ownership-gated call (lock roster, mark attendance, complete, cancel, open or submit an
    exam attempt) must present the real trainer id.
    """
    return build_user_headers(trainer_id, "Trainer")


def make_employer_admin_headers(employer_account_id: str) -> dict:
    """EmployerAdmin: pass the acting EmployerAccount's id.

    Ownership checks compare X-User-ID to the account identifier in the path, to an
    EmployerLocation's employer_account_id, to the owning account of a ServerAssignment's
    location, or to an Enrollment's sponsoring_employer_account_id.
    """
    return build_user_headers(employer_account_id, "EmployerAdmin")


def make_alcohol_server_headers(alcohol_server_id: str) -> dict:
    """AlcoholServer: pass the acting AlcoholServer's id.

    It must equal the alcohol_server_id carried in an enrollment request body, the
    alcohol_server_id of the enrollment being withdrawn, and the server identifier whose
    assignment listing is being read.
    """
    return build_user_headers(alcohol_server_id, "AlcoholServer")


def all_role_headers() -> dict:
    """Map of role name -> shared header set, for role-authorisation sweeps."""
    return {
        "ProgramAdmin": TEST_USERS["program_admin_headers"],
        "StateRegulator": TEST_USERS["state_regulator_headers"],
        "Trainer": TEST_USERS["trainer_headers"],
        "EmployerAdmin": TEST_USERS["employer_admin_headers"],
        "AlcoholServer": TEST_USERS["alcohol_server_headers"],
    }
