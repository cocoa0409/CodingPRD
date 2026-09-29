"""Pre-built request headers for each role, plus the named actor identities.

Every request carries X-User-ID and X-User-Role. The CustomerRep identity is
entity backed: its X-User-ID is the id of the Customer it acts for, so those
headers must be built per customer at call time.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --- Named actor ids -------------------------------------------------------
PLANT_MANAGER_ID = "pm-1"
PLANT_MANAGER_2_ID = "pm-2"
SCHEDULER_ID = "ps-1"
SCHEDULER_2_ID = "ps-2"
BATCH_TECH_ID = "bt-1"
BATCH_TECH_2_ID = "bt-2"
MOLD_ENGINEER_ID = "me-1"
MOLD_ENGINEER_2_ID = "me-2"

# Quality engineers are deliberately distinct people so that the two-person
# controls can be exercised: qe-1 signs risk, qe-2 approves, qe-3 inspects,
# qe-4 releases rework, qe-5 investigates complaints.
QE_RISK_SIGNER_ID = "qe-1"
QE_APPROVER_ID = "qe-2"
QE_INSPECTOR_ID = "qe-3"
QE_RELEASER_ID = "qe-4"
QE_INVESTIGATOR_ID = "qe-5"

WAREHOUSE_ID = "wo-1"
WAREHOUSE_2_ID = "wo-2"


# --- Header bundles --------------------------------------------------------
PLANT_MANAGER = build_user_headers(PLANT_MANAGER_ID, Role.PLANT_MANAGER)
PLANT_MANAGER_2 = build_user_headers(PLANT_MANAGER_2_ID, Role.PLANT_MANAGER)
SCHEDULER = build_user_headers(SCHEDULER_ID, Role.PLANT_SCHEDULER)
SCHEDULER_2 = build_user_headers(SCHEDULER_2_ID, Role.PLANT_SCHEDULER)
BATCH_TECH = build_user_headers(BATCH_TECH_ID, Role.BATCH_HOUSE_TECH)
BATCH_TECH_2 = build_user_headers(BATCH_TECH_2_ID, Role.BATCH_HOUSE_TECH)
MOLD_ENGINEER = build_user_headers(MOLD_ENGINEER_ID, Role.MOLD_ENGINEER)
MOLD_ENGINEER_2 = build_user_headers(MOLD_ENGINEER_2_ID, Role.MOLD_ENGINEER)

QE_RISK_SIGNER = build_user_headers(QE_RISK_SIGNER_ID, Role.QUALITY_ENGINEER)
QE_APPROVER = build_user_headers(QE_APPROVER_ID, Role.QUALITY_ENGINEER)
QE_INSPECTOR = build_user_headers(QE_INSPECTOR_ID, Role.QUALITY_ENGINEER)
QE_RELEASER = build_user_headers(QE_RELEASER_ID, Role.QUALITY_ENGINEER)
QE_INVESTIGATOR = build_user_headers(QE_INVESTIGATOR_ID, Role.QUALITY_ENGINEER)

WAREHOUSE = build_user_headers(WAREHOUSE_ID, Role.WAREHOUSE_OPERATOR)
WAREHOUSE_2 = build_user_headers(WAREHOUSE_2_ID, Role.WAREHOUSE_OPERATOR)


def customer_rep(customer_id: str) -> dict:
    """Headers for the CustomerRep acting for the given customer."""
    return build_user_headers(customer_id, Role.CUSTOMER_REP)


def headers_for(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user id and role pair."""
    return build_user_headers(user_id, role)


def quality_engineer(user_id: str) -> dict:
    """Headers for an arbitrary QualityEngineer identity."""
    return build_user_headers(user_id, Role.QUALITY_ENGINEER)


def headers_without_user_id(role: str) -> dict:
    """Headers that carry a role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> dict:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> dict:
    """Headers that carry a user id but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


# One representative header bundle per role, for role-sweep assertions.
HEADERS_BY_ROLE = {
    Role.PLANT_MANAGER: PLANT_MANAGER,
    Role.PLANT_SCHEDULER: SCHEDULER,
    Role.BATCH_HOUSE_TECH: BATCH_TECH,
    Role.MOLD_ENGINEER: MOLD_ENGINEER,
    Role.QUALITY_ENGINEER: QE_INSPECTOR,
    Role.WAREHOUSE_OPERATOR: WAREHOUSE,
}
