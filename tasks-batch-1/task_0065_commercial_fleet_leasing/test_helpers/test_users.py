"""Pre-built role headers for every role in the PRD (commercial fleet leasing).

Roles (PRD §2.1): FleetManager, ComplianceOfficer, TelematicsGateway carry an
opaque X-User-ID. Lessee is entity_backed:Lessee — X-User-ID is the acting
Lessee.id, so use make_lessee_headers(lessee_id) for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these directly; the Lessee entry is a
# fallback only for non-ownership tests (e.g. 403/401 paths that fail before
# any ownership check).
TEST_USERS = {
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    "telematics_gateway_headers": build_user_headers(
        "test-telematics-gateway-1", "TelematicsGateway"
    ),
    "lessee_headers": build_user_headers("test-lessee-1", "Lessee"),
}


def make_lessee_headers(lessee_id: str) -> dict:
    """For the Lessee role (entity_backed:Lessee). Pass the actual Lessee.id."""
    return build_user_headers(lessee_id, "Lessee")
