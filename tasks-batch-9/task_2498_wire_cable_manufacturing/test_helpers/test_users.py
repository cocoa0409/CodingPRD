"""Pre-built role headers for every role in the PRD (§2.1).

Seven of the eight roles are opaque: ``X-User-ID`` carries an arbitrary staff
identifier and only ``X-User-Role`` is interpreted. ``Customer`` is
entity-backed — its ``X-User-ID`` must be the ``id`` of a real Customer row, so
ownership-gated calls MUST use ``make_customer_headers(customer["id"])``.

Two rules make the QualityEngineer ids load-bearing rather than cosmetic:
segregation of duties is keyed on ``X-User-ID`` against every test operator on
the lot, and ``operator_user_id`` / ``released_by_user_id`` are stamped from the
acting header. Fixtures therefore pin distinct ids for the tester (``qe-001``),
the releaser (``qe-002``) and the dispositioner (``qe-003``).
"""

from prd_bench_local_runner.testing import build_user_headers

# Pinned QualityEngineer identities — kept distinct so the duty split passes.
QE_TESTER_USER_ID = "qe-001"
QE_RELEASER_USER_ID = "qe-002"
QE_DISPOSITIONER_USER_ID = "qe-003"

# Pinned PlantAdmin identities for the same reason.
ADMIN_TESTER_USER_ID = "admin-qc"
ADMIN_RELEASER_USER_ID = "admin-rel"


# Shared constants — safe for the seven opaque roles, and for tests that do not
# exercise Customer ownership.
TEST_USERS = {
    "plant_admin_headers": build_user_headers("test-plant-admin-1", "PlantAdmin"),
    "procurement_buyer_headers": build_user_headers(
        "test-procurement-buyer-1", "ProcurementBuyer"
    ),
    "process_engineer_headers": build_user_headers(
        "test-process-engineer-1", "ProcessEngineer"
    ),
    "quality_engineer_headers": build_user_headers(QE_TESTER_USER_ID, "QualityEngineer"),
    "certification_officer_headers": build_user_headers(
        "test-certification-officer-1", "CertificationOfficer"
    ),
    "shipping_clerk_headers": build_user_headers("test-shipping-clerk-1", "ShippingClerk"),
    "billing_analyst_headers": build_user_headers(
        "test-billing-analyst-1", "BillingAnalyst"
    ),
    # entity_backed role: this shared constant is a fallback for tests that do
    # NOT exercise ownership (e.g. proving the role holds no write operations).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role, which the PRD declares entity-backed.

    Pass the actual Customer row's ``id`` — the platform resolves the caller's
    own account, orders and shipments from it.
    """
    return build_user_headers(customer_id, "Customer")


def make_quality_engineer_headers(user_id: str) -> dict:
    """QualityEngineer headers with an explicit acting identity.

    Use ``QE_TESTER_USER_ID`` when recording tests, ``QE_RELEASER_USER_ID`` when
    releasing, and ``QE_DISPOSITIONER_USER_ID`` when dispositioning.
    """
    return build_user_headers(user_id, "QualityEngineer")


def make_plant_admin_headers(user_id: str) -> dict:
    """PlantAdmin headers with an explicit acting identity."""
    return build_user_headers(user_id, "PlantAdmin")


def make_headers(role: str, user_id: str) -> dict:
    """Generic escape hatch for parametrized role/identity families."""
    return build_user_headers(user_id, role)


# Convenience aliases used pervasively by fixtures.
ADMIN = TEST_USERS["plant_admin_headers"]
BUYER = TEST_USERS["procurement_buyer_headers"]
ENGINEER = TEST_USERS["process_engineer_headers"]
QE_TESTER = make_quality_engineer_headers(QE_TESTER_USER_ID)
QE_RELEASER = make_quality_engineer_headers(QE_RELEASER_USER_ID)
QE_DISPOSITIONER = make_quality_engineer_headers(QE_DISPOSITIONER_USER_ID)
CERT_OFFICER = TEST_USERS["certification_officer_headers"]
CLERK = TEST_USERS["shipping_clerk_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]

# Both auth headers omitted — used to probe the header-presence rung.
NO_AUTH_HEADERS: dict = {"Content-Type": "application/json"}
