"""Auth identities for every role in PRD 2.1.

PRD 2.1: "Every request carries the headers X-User-ID and X-User-Role."
Twelve of the thirteen roles use an opaque identity: the server never resolves
their X-User-ID against a stored row, so any stable string works. The single
exception is CustomerWitness, whose "X-User-ID header must be the id of a
stored WitnessParty row" -- so CustomerWitness headers can only be built once
a witness party exists, via ``make_customer_witness_headers``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CONTRACT_ADMIN,
    ROLE_CUSTOMER_REVIEWER,
    ROLE_CUSTOMER_WITNESS,
    ROLE_DESIGN_ENGINEER,
    ROLE_FIELD_SERVICE_ENGINEER,
    ROLE_LOGISTICS_COORDINATOR,
    ROLE_MATERIALS_PLANNER,
    ROLE_PLANT_ADMIN,
    ROLE_QUALITY_ENGINEER,
    ROLE_SALES_ENGINEER,
    ROLE_TEST_ENGINEER,
    ROLE_WITNESS_COORDINATOR,
)

# --- Opaque user ids ------------------------------------------------------
USER_PLANT_ADMIN = "u-plant-admin-1"
USER_SALES_1 = "u-sales-1"
USER_SALES_2 = "u-sales-2"
USER_DESIGN_1 = "u_de_1"
USER_DESIGN_2 = "u_de_2"
USER_CONTRACT_ADMIN = "u-contract-1"
USER_CONTRACT_ADMIN_2 = "u-contract-2"
USER_MATERIALS_PLANNER = "u-materials-1"
USER_TEST_ENGINEER = "u_te_1"
USER_TEST_ENGINEER_2 = "u_te_2"
USER_WITNESS_COORDINATOR = "u-witness-coord-1"
USER_REVIEWER_1 = "u-reviewer-1"
USER_REVIEWER_2 = "u-reviewer-2"
USER_QUALITY_1 = "u_qe_1"
USER_QUALITY_2 = "u_qe_2"
USER_QUALITY_7 = "u_qe_7"
USER_COMPLIANCE_1 = "u_co_1"
USER_COMPLIANCE_2 = "u_co_2"
USER_LOGISTICS = "u-logistics-1"
USER_FIELD_1 = "u_fs_1"
USER_FIELD_2 = "u_fs_2"

# --- Ready-made headers for the twelve opaque-identity roles --------------
PLANT_ADMIN = build_user_headers(USER_PLANT_ADMIN, ROLE_PLANT_ADMIN)
SALES_ENGINEER = build_user_headers(USER_SALES_1, ROLE_SALES_ENGINEER)
SALES_ENGINEER_OTHER = build_user_headers(USER_SALES_2, ROLE_SALES_ENGINEER)
DESIGN_ENGINEER = build_user_headers(USER_DESIGN_1, ROLE_DESIGN_ENGINEER)
CONTRACT_ADMIN = build_user_headers(USER_CONTRACT_ADMIN, ROLE_CONTRACT_ADMIN)
MATERIALS_PLANNER = build_user_headers(USER_MATERIALS_PLANNER, ROLE_MATERIALS_PLANNER)
TEST_ENGINEER = build_user_headers(USER_TEST_ENGINEER, ROLE_TEST_ENGINEER)
WITNESS_COORDINATOR = build_user_headers(
    USER_WITNESS_COORDINATOR, ROLE_WITNESS_COORDINATOR
)
CUSTOMER_REVIEWER = build_user_headers(USER_REVIEWER_1, ROLE_CUSTOMER_REVIEWER)
QUALITY_ENGINEER = build_user_headers(USER_QUALITY_1, ROLE_QUALITY_ENGINEER)
COMPLIANCE_OFFICER = build_user_headers(USER_COMPLIANCE_1, ROLE_COMPLIANCE_OFFICER)
LOGISTICS_COORDINATOR = build_user_headers(USER_LOGISTICS, ROLE_LOGISTICS_COORDINATOR)
FIELD_SERVICE_ENGINEER = build_user_headers(
    USER_FIELD_1, ROLE_FIELD_SERVICE_ENGINEER
)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary opaque user id under an arbitrary role."""
    return build_user_headers(user_id, role)


def make_customer_witness_headers(witness_party_id: str) -> Dict[str, str]:
    """Headers for the one entity-backed role of PRD 2.1.

    PRD 2.1: "For the CustomerWitness role the X-User-ID header must be the id
    of a stored WitnessParty row"; an unresolvable value is rejected with
    ERR_UNKNOWN_ROLE, and a value naming a different party than the one an
    assignment belongs to is rejected with ERR_WITNESS_IDENTITY_MISMATCH. Each
    CustomerWitness call therefore threads the live party id of the identity it
    is acting as, never a shared constant.
    """
    return build_user_headers(witness_party_id, ROLE_CUSTOMER_WITNESS)
