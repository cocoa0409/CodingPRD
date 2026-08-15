"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque operator identifiers: the server never compares
X-User-ID against any entity's id (PRD §2.1), so shared constants are the
canonical form. The make_*_headers builders exist for segregation-of-duties
tests that must control the exact X-User-ID string (PRD §2.11).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_director_headers": build_user_headers("pd-1", "ProgramDirector"),
    "utility_analyst_headers": build_user_headers("ua-1", "UtilityAnalyst"),
    "utility_analyst_alt_headers": build_user_headers("ua-2", "UtilityAnalyst"),
    "field_supervisor_headers": build_user_headers("fs-1", "FieldSupervisor"),
    "field_supervisor_alt_headers": build_user_headers("fs-2", "FieldSupervisor"),
    "meter_technician_headers": build_user_headers("mt-1", "MeterTechnician"),
    "investigator_headers": build_user_headers("inv-1", "Investigator"),
    "regulator_liaison_headers": build_user_headers("rl-1", "RegulatorLiaison"),
}


def make_program_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramDirector")


def make_utility_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UtilityAnalyst")


def make_field_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldSupervisor")


def make_meter_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MeterTechnician")


def make_investigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Investigator")


def make_regulator_liaison_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatorLiaison")
