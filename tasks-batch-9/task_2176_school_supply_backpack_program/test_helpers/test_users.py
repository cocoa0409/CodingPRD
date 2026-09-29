"""Pre-built operator identity headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operators: X-User-ID is not tied to any persisted entity, so these
# shared constants are the canonical form for ProgramDirector, WarehouseLead
# and DonorRelations.  For the two entity-backed roles the shared constant is a
# fallback usable only where no ownership check applies (401/403/404 probes and
# read-only calls); ownership-gated calls must use the per-instance builders.
TEST_USERS = {
    "program_director_headers": build_user_headers("pd-1", "ProgramDirector"),
    "program_director_alt_headers": build_user_headers("pd-2", "ProgramDirector"),
    "warehouse_lead_headers": build_user_headers("wl-1", "WarehouseLead"),
    "donor_relations_headers": build_user_headers("dr-1", "DonorRelations"),
    "school_liaison_headers": build_user_headers("sl-unknown", "SchoolLiaison"),
    "site_coordinator_headers": build_user_headers("sc-unknown", "SiteCoordinator"),
}


def make_school_liaison_headers(school_id: str) -> dict:
    """SchoolLiaison is entity-backed by School: X-User-ID is the School's id."""
    return build_user_headers(school_id, "SchoolLiaison")


def make_site_coordinator_headers(site_id: str) -> dict:
    """SiteCoordinator is entity-backed by CollectionSite: X-User-ID is the site's id."""
    return build_user_headers(site_id, "SiteCoordinator")


def make_program_director_headers(user_id: str) -> dict:
    """ProgramDirector is opaque; the id is only recorded, never compared."""
    return build_user_headers(user_id, "ProgramDirector")


def make_warehouse_lead_headers(user_id: str) -> dict:
    """WarehouseLead is opaque; the id is only recorded, never compared."""
    return build_user_headers(user_id, "WarehouseLead")
