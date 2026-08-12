"""Pre-built role headers for every role in the PRD (§2.1).

Grower and Applicator are entity-backed roles: X-User-ID must be the id of the
acting Customer / Applicator whenever an ownership or assignment check runs.
Use make_grower_headers(customer_id) / make_applicator_headers(applicator_id)
for those calls. The shared constants in TEST_USERS are safe for opaque roles
and for calls whose outcome does not depend on ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "agronomist_headers": build_user_headers("test-agronomist-1", "Agronomist"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "admin_headers": build_user_headers("test-admin-1", "CoopAdmin"),
    # Entity-backed roles — fallback only for non-ownership calls
    # (e.g. expecting ERR_FORBIDDEN / ERR_VALIDATION before ownership runs).
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
    "applicator_headers": build_user_headers("test-applicator-1", "Applicator"),
}


def make_grower_headers(customer_id: str) -> dict:
    """Grower is entity-backed by Customer: pass the acting Customer.id."""
    return build_user_headers(customer_id, "Grower")


def make_applicator_headers(applicator_id: str) -> dict:
    """Applicator is entity-backed by Applicator: pass the acting Applicator.id."""
    return build_user_headers(applicator_id, "Applicator")
