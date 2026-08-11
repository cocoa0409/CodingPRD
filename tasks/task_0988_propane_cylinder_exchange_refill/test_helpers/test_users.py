"""Pre-built role headers for every role in the PRD (§2.1).

Identity model (PRD §2.1):
- PlatformAdmin, SiteClerk, ComplianceOfficer carry an opaque X-User-ID.
- Driver, Technician, HostSiteManager are entity-backed: X-User-ID must equal the
  acting entity's `id` whenever the call is ownership-gated (driver on own runs,
  technician as record author/confirmer, host-site manager on own site). Use the
  per-instance builders below for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "platform_admin_2_headers": build_user_headers("admin-9", "PlatformAdmin"),
    "site_clerk_headers": build_user_headers("clerk-1", "SiteClerk"),
    "site_clerk_2_headers": build_user_headers("clerk-2", "SiteClerk"),
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers("officer-2", "ComplianceOfficer"),
    # Entity-backed roles — shared constants are a fallback for non-ownership
    # tests only (e.g., RBAC denial where the role itself is rejected).
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "host_site_manager_headers": build_user_headers("test-manager-1", "HostSiteManager"),
}


def make_driver_headers(driver_id: str) -> dict:
    """For Driver (entity-backed). Pass the actual Driver.id as driver_id
    whenever the call is ownership-gated (arrive/complete/self reads)."""
    return build_user_headers(driver_id, "Driver")


def make_technician_headers(technician_id: str) -> dict:
    """For Technician (entity-backed). Pass the actual Technician.id so the
    server records it as technician_id / confirmer_technician_id."""
    return build_user_headers(technician_id, "Technician")


def make_host_site_manager_headers(site_id: str) -> dict:
    """For HostSiteManager (entity-backed). Pass the actual HostSite.id so the
    site-ownership comparison succeeds."""
    return build_user_headers(site_id, "HostSiteManager")


def make_clerk_headers(clerk_id: str) -> dict:
    """SiteClerk is opaque, but clerk_id is recorded for segregation-of-duties
    checks; use a distinct id per acting clerk in SoD scenarios."""
    return build_user_headers(clerk_id, "SiteClerk")


def make_admin_headers(admin_id: str) -> dict:
    """PlatformAdmin is opaque; use a distinct id when SoD compares actors."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_officer_headers(officer_id: str) -> dict:
    """ComplianceOfficer is opaque; use a distinct id when SoD compares actors."""
    return build_user_headers(officer_id, "ComplianceOfficer")
