"""Pre-built role headers for every role in the PRD (section 2.1).

NurseAdmin, FloatCoordinator, and Regulator are opaque roles: X-User-ID is an
operator identifier the server never compares to any entity id, so the shared
constants are the canonical form.

ChargeNurse and StaffNurse are entity-backed roles: X-User-ID is the id of the
acting Nurse. Any ownership-gated call (StaffNurse accept/decline) MUST use
make_staff_nurse_headers(nurse_id) with the real nurse id; fixtures thread a
real charge-qualified nurse's id through make_charge_nurse_headers for the
same reason.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "nurse_admin_headers": build_user_headers("test-admin-1", "NurseAdmin"),
    "float_coordinator_headers": build_user_headers("test-float-coord-1",
                                                    "FloatCoordinator"),
    "regulator_headers": build_user_headers("test-regulator-1", "Regulator"),
    # Entity-backed roles — fallback for non-ownership tests only.
    "charge_nurse_headers": build_user_headers("test-charge-1", "ChargeNurse"),
    "staff_nurse_headers": build_user_headers("test-staff-1", "StaffNurse"),
}


def make_nurse_admin_headers(user_id: str) -> dict:
    """NurseAdmin (opaque). user_id may be any operator identifier."""
    return build_user_headers(user_id, "NurseAdmin")


def make_charge_nurse_headers(user_id: str) -> dict:
    """ChargeNurse (entity-backed: Nurse). Pass a real charge-qualified
    nurse's id as user_id."""
    return build_user_headers(user_id, "ChargeNurse")


def make_staff_nurse_headers(user_id: str) -> dict:
    """StaffNurse (entity-backed: Nurse). Pass the assignment's nurse_id as
    user_id whenever the call is ownership-gated (accept/decline/claim)."""
    return build_user_headers(user_id, "StaffNurse")


def make_float_coordinator_headers(user_id: str) -> dict:
    """FloatCoordinator (opaque). user_id may be any operator identifier."""
    return build_user_headers(user_id, "FloatCoordinator")


def make_regulator_headers(user_id: str) -> dict:
    """Regulator (opaque). user_id may be any operator identifier."""
    return build_user_headers(user_id, "Regulator")
