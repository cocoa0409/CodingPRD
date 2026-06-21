"""Pre-built role headers for every role in the Parking & Permit PRD.

FacilityAdmin and EnforcementOfficer carry opaque operator identifiers never
compared to any entity id, so their shared-constant headers are canonical.
Motorist and Merchant are entity-backed: ownership checks compare X-User-ID to
the resource's motorist_id / merchant_id, so consumers MUST use the per-instance
builders make_motorist_headers(motorist_id) / make_merchant_headers(merchant_id)
whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque roles — shared constants are the canonical form.
    "facility_admin_headers": build_user_headers("test-admin-1", "FacilityAdmin"),
    "enforcement_officer_headers": build_user_headers("test-officer-1", "EnforcementOfficer"),
    # entity-backed roles — shared constants are a fallback for non-ownership tests
    # (e.g. role-authorization 403 checks where the request never reaches an
    # ownership comparison). Never use these where ownership is enforced.
    "motorist_headers": build_user_headers("test-motorist-1", "Motorist"),
    "merchant_headers": build_user_headers("test-merchant-1", "Merchant"),
}


def make_facility_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For FacilityAdmin (opaque). user_id is recorded for audit only."""
    return build_user_headers(user_id, "FacilityAdmin")


def make_enforcement_officer_headers(user_id: str = "test-officer-1") -> dict:
    """For EnforcementOfficer (opaque). user_id is recorded for audit only."""
    return build_user_headers(user_id, "EnforcementOfficer")


def make_motorist_headers(user_id: str) -> dict:
    """For Motorist (entity_backed:Motorist). Pass the actual Motorist.id as
    user_id whenever the call is ownership-gated (permit request, waitlist join,
    cancel, appeal submit, citation pay)."""
    return build_user_headers(user_id, "Motorist")


def make_merchant_headers(user_id: str) -> dict:
    """For Merchant (entity_backed:Merchant). Pass the actual Merchant.id as
    user_id whenever the call is ownership-gated (validation issue)."""
    return build_user_headers(user_id, "Merchant")
