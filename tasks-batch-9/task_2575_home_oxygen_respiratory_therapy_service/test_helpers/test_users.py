"""Pre-built role headers for the seven roles named in PRD §2.1.

All seven roles carry **opaque** identities: the accompanying ``X-User-ID`` is an
opaque operator identifier that is never compared against any row's ``id``, so a
shared per-role constant is the canonical form.  The one place ``X-User-ID``
carries decision weight is segregation of duties on certificate approval, which
is why distinct submitter / signer / auditor identifiers are provided below and
why ``make_headers`` exists for tests that need a further distinct operator.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers, one per role.
USER_IDS = {
    "BranchManager": "u-mgr-1",
    "IntakeCoordinator": "u-intake-1",
    "Physician": "u-phys-1",
    "ComplianceAuditor": "u-audit-1",
    "RespiratoryTherapist": "u-rt-1",
    "DeliveryDriver": "u-drv-1",
    "BillingSpecialist": "u-bill-1",
}

ROLE_NAMES = [
    "IntakeCoordinator",
    "Physician",
    "ComplianceAuditor",
    "RespiratoryTherapist",
    "DeliveryDriver",
    "BranchManager",
    "BillingSpecialist",
]

TEST_USERS = {
    "branch_manager_headers": build_user_headers("u-mgr-1", "BranchManager"),
    "intake_coordinator_headers": build_user_headers("u-intake-1", "IntakeCoordinator"),
    "physician_headers": build_user_headers("u-phys-1", "Physician"),
    "compliance_auditor_headers": build_user_headers("u-audit-1", "ComplianceAuditor"),
    "respiratory_therapist_headers": build_user_headers("u-rt-1", "RespiratoryTherapist"),
    "delivery_driver_headers": build_user_headers("u-drv-1", "DeliveryDriver"),
    "billing_specialist_headers": build_user_headers("u-bill-1", "BillingSpecialist"),
}

# Convenience aliases used throughout the suite.
BRANCH_MANAGER = TEST_USERS["branch_manager_headers"]
INTAKE_COORDINATOR = TEST_USERS["intake_coordinator_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
COMPLIANCE_AUDITOR = TEST_USERS["compliance_auditor_headers"]
RESPIRATORY_THERAPIST = TEST_USERS["respiratory_therapist_headers"]
DELIVERY_DRIVER = TEST_USERS["delivery_driver_headers"]
BILLING_SPECIALIST = TEST_USERS["billing_specialist_headers"]

# Headers keyed by the exact role name, for role-matrix probes.
HEADERS_BY_ROLE = {
    "IntakeCoordinator": INTAKE_COORDINATOR,
    "Physician": PHYSICIAN,
    "ComplianceAuditor": COMPLIANCE_AUDITOR,
    "RespiratoryTherapist": RESPIRATORY_THERAPIST,
    "DeliveryDriver": DELIVERY_DRIVER,
    "BranchManager": BRANCH_MANAGER,
    "BillingSpecialist": BILLING_SPECIALIST,
}


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary opaque operator identifier under ``role``.

    Needed where the acting operator identifier itself is the subject of the
    assertion — segregation of duties on certificate approval.
    """
    return build_user_headers(user_id, role)


def make_compliance_auditor_headers(user_id: str) -> dict:
    """A ComplianceAuditor acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "ComplianceAuditor")


def make_intake_coordinator_headers(user_id: str) -> dict:
    """An IntakeCoordinator acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "IntakeCoordinator")


def make_physician_headers(user_id: str) -> dict:
    """A Physician acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "Physician")


def headers_without_auth() -> dict:
    """Headers carrying no auth at all, for the unauthenticated probes."""
    return {"Content-Type": "application/json"}
