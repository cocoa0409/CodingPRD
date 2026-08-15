"""Pre-built role headers for every role in the PRD (§2.1).

All six roles carry an opaque X-User-ID (it is never a persisted entity id).
The shared constants below use the canonical per-role user ids that the
fixtures and tests interlock on; the make_*_headers builders exist for tests
that need a second identity in the same role (segregation-of-duties checks,
supplier ownership checks).
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids — referenced by name in segregation-of-duties and
# supplier-ownership assertions.
MANAGER_ID = "manager-1"
ANALYST_ID = "analyst-1"
STEWARD_ID = "steward-1"
LEAD_ID = "lead-1"
ASSURER_ID = "assurer-1"
SUPPLIER_ID = "supplier-1"

TEST_USERS = {
    "manager_headers": build_user_headers(MANAGER_ID, "SustainabilityManager"),
    "analyst_headers": build_user_headers(ANALYST_ID, "SustainabilityAnalyst"),
    "steward_headers": build_user_headers(STEWARD_ID, "SiteDataSteward"),
    "lead_headers": build_user_headers(LEAD_ID, "DisclosureLead"),
    "assurer_headers": build_user_headers(ASSURER_ID, "AssuranceProvider"),
    "supplier_headers": build_user_headers(SUPPLIER_ID, "SupplierContact"),
}

# A headers dict with no authentication material at all (PRD §2.1:
# "A request missing either header ... is rejected with ERR_UNAUTHENTICATED").
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SustainabilityManager")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SustainabilityAnalyst")


def make_steward_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SiteDataSteward")


def make_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DisclosureLead")


def make_assurer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AssuranceProvider")


def make_supplier_headers(user_id: str) -> dict:
    """SupplierContact calls whose X-User-ID must equal the engagement's
    contact_user_id (PRD §3.5) must be built with that contact id."""
    return build_user_headers(user_id, "SupplierContact")
