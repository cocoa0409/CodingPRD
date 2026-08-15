"""Pre-built role headers for every role in the PRD.

All four roles (FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep) are
opaque identities per PRD §2.1: X-User-ID is not tied to any persisted entity.
Distinct user ids still matter because segregation-of-duties checks compare the
acting X-User-ID against operator identifiers recorded on resources
(reported_by_user_id, requested_by_user_id, recorded_by_user_id,
acknowledged_by_user_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical form for these opaque roles.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "FundraiserAdmin"),
    "coordinator_headers": build_user_headers("coord-1", "GroupCoordinator"),
    "treasurer_headers": build_user_headers("treas-1", "Treasurer"),
    "supplier_rep_headers": build_user_headers("supp-1", "SupplierRep"),
}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "FundraiserAdmin")


def make_coordinator_headers(user_id: str = "coord-1") -> dict:
    return build_user_headers(user_id, "GroupCoordinator")


def make_treasurer_headers(user_id: str = "treas-1") -> dict:
    return build_user_headers(user_id, "Treasurer")


def make_supplier_rep_headers(user_id: str = "supp-1") -> dict:
    return build_user_headers(user_id, "SupplierRep")
