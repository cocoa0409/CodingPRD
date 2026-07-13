"""Pre-built role headers for every role in the PRD (Section 2.1).

Two forms are emitted:

- Shared constants in TEST_USERS — safe for opaque roles (Dispatcher, Driver,
  PlatformAdmin, Anonymous) and for tests that never exercise ownership.
- Per-instance builders for the two entity_backed roles (Donor, PartnerAdmin):
  their X-User-ID must equal the acting entity's id whenever the call is
  ownership-gated, so fixtures MUST thread the real id through these builders.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # entity_backed roles — shared constants are a fallback for NON-ownership
    # tests only (e.g. 404-on-missing-resource). Ownership-gated calls MUST use
    # the per-instance builders below with the real entity id.
    "donor_headers": build_user_headers("test-donor-1", "Donor"),
    "partner_admin_headers": build_user_headers("test-partner-admin-1", "PartnerAdmin"),
}


def make_donor_headers(donor_id: str) -> dict:
    """For Donor (entity_backed:Donor). Pass the acting Donor.id; ownership
    checks compare a request/plan/item/invoice's owning donor to X-User-ID."""
    return build_user_headers(donor_id, "Donor")


def make_partner_admin_headers(partner_id: str) -> dict:
    """For PartnerAdmin (entity_backed:CharityPartner). Pass the acting
    CharityPartner.id; ownership checks compare the target's partner_id."""
    return build_user_headers(partner_id, "PartnerAdmin")
