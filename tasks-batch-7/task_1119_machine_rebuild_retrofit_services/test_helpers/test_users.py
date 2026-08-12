"""Pre-built role headers for every role in the PRD (§2.1).

Only the Customer role is entity-backed: its X-User-ID must be the id of the
acting Customer record, so ownership-gated calls must be built per customer via
make_customer_headers(). The other eight roles carry opaque operator
identifiers; shared constants are canonical for them. For identity-bound writes
(submit by the recording assessor, declare-ready by the assigned engineer,
session logging by the assigned trainer, recording by the scheduling inspector,
RE fabrication/validation) use the make_*_headers builders with the opaque id
that the record pins.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # Opaque roles: shared constants are the canonical form.
    "assessor_headers": build_user_headers("assessor-1", "Assessor"),
    "pm_headers": build_user_headers("pm-1", "ProjectManager"),
    "engineer_headers": build_user_headers("eng-1", "RebuildEngineer"),
    "inspector_headers": build_user_headers("qi-1", "QualityInspector"),
    "trainer_headers": build_user_headers("tr-1", "Trainer"),
    "logistics_headers": build_user_headers("log-1", "LogisticsCoordinator"),
    "warranty_admin_headers": build_user_headers("wa-1", "WarrantyAdministrator"),
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}

# Convenient module-level aliases for the opaque roles.
ASSESSOR = TEST_USERS["assessor_headers"]
PM = TEST_USERS["pm_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
TRAINER = TEST_USERS["trainer_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]
ADMIN = TEST_USERS["admin_headers"]


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: pass the actual Customer.id as user_id for
    every ownership-gated call (quote approval, claim filing, window booking,
    trade-in accept/decline)."""
    return build_user_headers(user_id, "Customer")


def make_assessor_headers(user_id: str) -> dict:
    """Assessor identity is recorded as assessment.assessor_id; submissions
    compare against it."""
    return build_user_headers(user_id, "Assessor")


def make_engineer_headers(user_id: str) -> dict:
    """RebuildEngineer identity is pinned as project.assigned_engineer_id at
    decision time or re-job fabricated_by_id at fabrication time."""
    return build_user_headers(user_id, "RebuildEngineer")


def make_inspector_headers(user_id: str) -> dict:
    """QualityInspector identity is recorded as acceptance test inspector_id or
    re-job validated_by_id."""
    return build_user_headers(user_id, "QualityInspector")


def make_trainer_headers(user_id: str) -> dict:
    """Trainer identity is recorded as training record trainer_id; session
    logging and documentation delivery compare against it."""
    return build_user_headers(user_id, "Trainer")
