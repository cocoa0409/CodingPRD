"""Pre-built role headers for every role in the PRD.

All six roles use opaque operator identifiers (PRD section 2.1): X-User-ID is
never compared against an entity id, only against recorded author/initiator/
executor fields for segregation of duties. Shared constants are therefore the
canonical form; the make_* builders exist for tests that need a second user id
under the same role (for example a different quality engineer re-executing a
rejected validation phase).
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids. Segregation-of-duties tests rely on these strings.
QE_ALICE = "qe-alice"
QE_CAROL = "qe-carol"
QM_BOB = "qm-bob"
PO_1 = "po-1"
SQE_1 = "sqe-1"
RA_1 = "ra-1"
ADMIN_1 = "admin-1"

TEST_USERS = {
    "quality_engineer_headers": build_user_headers(QE_ALICE, "QualityEngineer"),
    "quality_manager_headers": build_user_headers(QM_BOB, "QualityManager"),
    "production_operator_headers": build_user_headers(PO_1, "ProductionOperator"),
    "supplier_quality_engineer_headers": build_user_headers(SQE_1, "SupplierQualityEngineer"),
    "regulatory_affairs_headers": build_user_headers(RA_1, "RegulatoryAffairs"),
    "qms_admin_headers": build_user_headers(ADMIN_1, "QMSAdmin"),
}


def make_quality_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityEngineer")


def make_quality_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityManager")


def make_production_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionOperator")


def make_supplier_quality_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplierQualityEngineer")


def make_regulatory_affairs_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatoryAffairs")


def make_qms_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QMSAdmin")
