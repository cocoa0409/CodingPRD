"""
Pre-built auth headers for every role of PRD §2.1, plus the segregation-of-duties
pairs the PRD forces tests to keep distinct.

Six roles carry an opaque identity, so a fixed operator string is enough for them.
`DepotManager` is the one entity-backed role — "When X-User-Role is DepotManager,
X-User-ID is the id of the acting Depot" — so its headers can only be built once a
depot exists. Never reuse a constant for a DepotManager call: use
make_depot_manager_headers(depot_id).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_DEPOT_MANAGER,
    ROLE_GROUND_CONTROL_ENGINEER,
    ROLE_LOGISTICS_PLANNER,
    ROLE_MINE_PLANNER,
    ROLE_QUALITY_LAB,
)

# ─── Opaque-identity operators (PRD §2.1) ─────────────

MINE_PLANNER_USER_ID = "mine-planner-1"
GROUND_CONTROL_USER_ID = "ground-control-eng-1"
GROUND_CONTROL_ALT_USER_ID = "ground-control-eng-2"
LAB_TECH_USER_ID = "lab-tech-1"
LAB_LEAD_USER_ID = "lab-lead-2"
LOGISTICS_USER_ID = "logistics-planner-1"
CONTRACT_ADMIN_USER_ID = "contract-admin-1"
CONTRACT_ADMIN_ALT_USER_ID = "contract-admin-2"
COMPLIANCE_USER_ID = "compliance-officer-1"

MINE_PLANNER = build_user_headers(MINE_PLANNER_USER_ID, ROLE_MINE_PLANNER)
GROUND_CONTROL = build_user_headers(GROUND_CONTROL_USER_ID, ROLE_GROUND_CONTROL_ENGINEER)
# A second engineer, for cases that must not collide with the recorded inspector.
GROUND_CONTROL_ALT = build_user_headers(
    GROUND_CONTROL_ALT_USER_ID, ROLE_GROUND_CONTROL_ENGINEER
)

# Two distinct QualityLab operators: "the X-User-ID deciding quality control on a
# treatment batch must differ from the X-User-ID recorded as that batch's creator".
LAB_TECH = build_user_headers(LAB_TECH_USER_ID, ROLE_QUALITY_LAB)
LAB_LEAD = build_user_headers(LAB_LEAD_USER_ID, ROLE_QUALITY_LAB)

LOGISTICS = build_user_headers(LOGISTICS_USER_ID, ROLE_LOGISTICS_PLANNER)

# Two distinct ContractAdministrators: the deciding X-User-ID "must not equal the
# submitted_by_user_id".
CONTRACT_ADMIN = build_user_headers(CONTRACT_ADMIN_USER_ID, ROLE_CONTRACT_ADMINISTRATOR)
CONTRACT_ADMIN_ALT = build_user_headers(
    CONTRACT_ADMIN_ALT_USER_ID, ROLE_CONTRACT_ADMINISTRATOR
)

COMPLIANCE = build_user_headers(COMPLIANCE_USER_ID, ROLE_COMPLIANCE_OFFICER)

# A ComplianceOfficer whose id equals the ground-control inspector's, used to trip
# the second segregation-of-duties rule on a compliance action citing an inspection.
COMPLIANCE_AS_INSPECTOR = build_user_headers(
    GROUND_CONTROL_USER_ID, ROLE_COMPLIANCE_OFFICER
)


def make_depot_manager_headers(depot_id: str) -> Dict[str, str]:
    """
    Headers for the DepotManager of `depot_id`.

    PRD §2.1: "ownership checks on any resource that references a Depot compare the
    resource's depot foreign-key field to X-User-ID". Passing the wrong depot's id
    here is exactly what ERR_DEPOT_NOT_OWNED reports.
    """
    return build_user_headers(depot_id, ROLE_DEPOT_MANAGER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user/role pair, for authorization and identity-recording tests."""
    return build_user_headers(user_id, role)


# ─── Malformed identity headers (PRD §2.1, stage 1 of §2.6) ───

NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

MISSING_USER_ID = {"X-User-Role": ROLE_MINE_PLANNER, "Content-Type": "application/json"}

MISSING_ROLE = {"X-User-ID": MINE_PLANNER_USER_ID, "Content-Type": "application/json"}

EMPTY_USER_ID = build_user_headers("", ROLE_MINE_PLANNER)

UNKNOWN_ROLE = build_user_headers("someone-1", "SafetyAuditor")

# Convenient map for role-matrix tests over the six opaque roles.
OPAQUE_ROLE_HEADERS = {
    ROLE_MINE_PLANNER: MINE_PLANNER,
    ROLE_GROUND_CONTROL_ENGINEER: GROUND_CONTROL,
    ROLE_QUALITY_LAB: LAB_TECH,
    ROLE_LOGISTICS_PLANNER: LOGISTICS,
    ROLE_CONTRACT_ADMINISTRATOR: CONTRACT_ADMIN,
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE,
}
