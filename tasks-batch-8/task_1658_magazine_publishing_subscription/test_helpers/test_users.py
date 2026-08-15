"""Pre-built role headers for every role in the PRD (§2.1).

All five roles have opaque identity: X-User-ID is an opaque operator
identifier that is never compared against any entity's id, so the shared
constants below are the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "publishing_director_headers": build_user_headers("test-director-1", "PublishingDirector"),
    "production_manager_headers": build_user_headers("test-production-1", "ProductionManager"),
    "circulation_manager_headers": build_user_headers("test-circulation-1", "CirculationManager"),
    "fulfillment_manager_headers": build_user_headers("test-fulfillment-1", "FulfillmentManager"),
    "postal_compliance_officer_headers": build_user_headers("test-postal-1", "PostalComplianceOfficer"),
}

# Sentinel for requests with no operator context headers at all (PRD §2.1).
ANONYMOUS_HEADERS: dict = {}
