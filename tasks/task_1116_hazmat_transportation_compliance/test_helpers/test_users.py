"""Pre-built role headers for every role in the PRD (§2.1).

All three roles carry identity: opaque — X-User-ID is never compared against a
persisted entity id. It IS, however, recorded on Shipment.classified_by_user_id
and ShippingPaper.certified_by_user_id, and the certification step rejects the
request when the two coincide (SoD, PRD §3.4). Tests therefore use distinct
named officer headers for the classify vs certify steps.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise SoD.
TEST_USERS = {
    "carrier_admin_headers": build_user_headers("carrier-admin-1", "CarrierAdmin"),
    "officer_a_headers": build_user_headers("officer-a", "ShipperComplianceOfficer"),
    "officer_b_headers": build_user_headers("officer-b", "ShipperComplianceOfficer"),
    "regulator_headers": build_user_headers("regulator-1", "Regulator"),
}


# Per-user builders — required whenever a test needs a specific X-User-ID
# (e.g., segregation-of-duties scenarios at shipping-paper certification).
def make_carrier_admin_headers(user_id: str) -> dict:
    """CarrierAdmin headers with a caller-chosen opaque user id."""
    return build_user_headers(user_id, "CarrierAdmin")


def make_officer_headers(user_id: str) -> dict:
    """ShipperComplianceOfficer headers with a caller-chosen opaque user id.

    The id is recorded as classified_by_user_id / certified_by_user_id and the
    two must differ for SoD-sensitive flows.
    """
    return build_user_headers(user_id, "ShipperComplianceOfficer")


def make_regulator_headers(user_id: str) -> dict:
    """Regulator headers with a caller-chosen opaque user id."""
    return build_user_headers(user_id, "Regulator")
