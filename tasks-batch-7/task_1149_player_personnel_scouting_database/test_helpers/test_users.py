"""Pre-built role headers for every role in the PRD (§2.1).

AreaScout and ScoutingDirector are entity-backed by Scout: X-User-ID must be
the id of an existing Scout row whose `level` matches the role. MedicalStaff
and GeneralManager are opaque.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for non-ownership tests of
# entity-backed roles (e.g. 404s, 400s, or calls where no Scout identity is
# exercised by the endpoint under test).
TEST_USERS = {
    "area_scout_headers": build_user_headers("test-area-scout-1", "AreaScout"),
    "scouting_director_headers": build_user_headers(
        "test-scouting-director-1", "ScoutingDirector"
    ),
    "medical_staff_headers": build_user_headers("test-medical-staff-1", "MedicalStaff"),
    "general_manager_headers": build_user_headers(
        "test-general-manager-1", "GeneralManager"
    ),
}


def make_area_scout_headers(user_id: str) -> dict:
    """AreaScout is entity-backed: user_id must be the id of a Scout with level AREA."""
    return build_user_headers(user_id, "AreaScout")


def make_scouting_director_headers(user_id: str) -> dict:
    """ScoutingDirector is entity-backed: user_id must be the id of a Scout with level DIRECTOR."""
    return build_user_headers(user_id, "ScoutingDirector")


def make_medical_staff_headers(user_id: str = "test-medical-staff-1") -> dict:
    """MedicalStaff is opaque; user_id is not tied to any persisted entity."""
    return build_user_headers(user_id, "MedicalStaff")


def make_general_manager_headers(user_id: str = "test-general-manager-1") -> dict:
    """GeneralManager is opaque; user_id is not tied to any persisted entity."""
    return build_user_headers(user_id, "GeneralManager")
