"""Pre-built role headers for every role in the PRD (§2.1).

Four of five roles are opaque operator identities (Shipper, Driver,
ComplianceOfficer, PlatformAdmin): X-User-ID is not tied to a persisted record,
so the shared-constant form is canonical for them. Shipper ownership of
cancel/withdraw is enforced by comparing X-User-ID to a stored
shipper_user_id/filed_by_user_id, so ownership tests build per-id Shipper headers
with make_shipper_headers().

Carrier is the one entity-backed role: X-User-ID is the id of the acting Carrier
record. Ownership-gated carrier calls therefore use make_carrier_headers(carrier_id)
threaded with the real Carrier.id created during setup.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for opaque roles and for non-ownership tests.
TEST_USERS = {
    "shipper_headers": build_user_headers("shipper-op-1", "Shipper"),
    "carrier_headers": build_user_headers("carrier-op-1", "Carrier"),
    "driver_headers": build_user_headers("driver-op-1", "Driver"),
    "compliance_officer_headers": build_user_headers("co-op-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
}


def make_carrier_headers(user_id: str) -> dict:
    """Carrier headers carrying an explicit X-User-ID.

    Carrier is entity_backed: pass the actual Carrier.id whenever the call is
    ownership-gated against the resource's carrier foreign key.
    """
    return build_user_headers(user_id, "Carrier")


def make_shipper_headers(user_id: str) -> dict:
    """Shipper headers carrying an explicit X-User-ID.

    Shipper is opaque, but cancel/withdraw ownership compares X-User-ID against a
    stored shipper_user_id / filed_by_user_id; pass the owning operator id.
    """
    return build_user_headers(user_id, "Shipper")


def make_driver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Driver")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
