"""Pre-built role headers for every role in the PRD.

VendorCoordinator, ORScheduler, SterileProcessingTech, and ORCirculatorNurse
are opaque identities: X-User-ID is not tied to any persisted entity (the
server may record it, e.g. as verified_by_user_id). VendorRep is
entity-backed: X-User-ID must be the acting VendorRep entity's id, so
ownership-gated calls MUST use make_vendor_rep_headers(rep["id"]).

Several coordinator personas (coord-1/coord-2/coord-3) exist so that
segregation-of-duties scenarios can pick distinct verifier / reconciler /
waver identities.
"""
from prd_bench_local_runner.testing import build_user_headers

COORD_1 = "coord-1"
COORD_2 = "coord-2"
COORD_3 = "coord-3"
SCHEDULER_1 = "sched-1"
TECH_1 = "tech-1"
NURSE_1 = "nurse-1"

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership (400-on-bad-payload, 404-on-missing-resource,
# wrong-role checks).
TEST_USERS = {
    "coordinator_headers": build_user_headers(COORD_1, "VendorCoordinator"),
    "scheduler_headers": build_user_headers(SCHEDULER_1, "ORScheduler"),
    "tech_headers": build_user_headers(TECH_1, "SterileProcessingTech"),
    "nurse_headers": build_user_headers(NURSE_1, "ORCirculatorNurse"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only — never use it for check-in / pickup / dispute / pass-self.
    "vendor_rep_headers": build_user_headers("test-rep-1", "VendorRep"),
}


def make_coordinator_headers(user_id: str = COORD_1) -> dict:
    """VendorCoordinator is opaque; distinct ids anchor segregation of duties."""
    return build_user_headers(user_id, "VendorCoordinator")


def make_scheduler_headers(user_id: str = SCHEDULER_1) -> dict:
    return build_user_headers(user_id, "ORScheduler")


def make_tech_headers(user_id: str = TECH_1) -> dict:
    return build_user_headers(user_id, "SterileProcessingTech")


def make_nurse_headers(user_id: str = NURSE_1) -> dict:
    return build_user_headers(user_id, "ORCirculatorNurse")


def make_vendor_rep_headers(rep_id: str) -> dict:
    """For VendorRep (entity_backed:VendorRep). Pass the actual VendorRep.id
    whenever the call is ownership-gated (check-in, pickup, dispute, pass)."""
    return build_user_headers(rep_id, "VendorRep")
