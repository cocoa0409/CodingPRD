"""Pre-built role headers for every role in the PRD (§2.1).

The Driver role is entity-backed: when X-User-Role is Driver, X-User-ID is the
id of the acting Driver record, and ownership checks compare a resource's
driver_id to X-User-ID. Ownership-gated Driver calls MUST therefore use
make_driver_headers(driver["id"]) with the real Driver id — never the shared
constant. The other three roles are opaque operator identities, so their shared
constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "clerk_headers": build_user_headers("clerk-op-1", "CourtClerk"),
    "hearing_officer_headers": build_user_headers("hearing-op-1", "HearingOfficer"),
    "dmv_headers": build_user_headers("dmv-op-1", "DmvAdmin"),
    # Driver is entity_backed: this shared constant is a fallback for
    # non-ownership tests only (e.g. a 403 forbidden-role check). Ownership-gated
    # Driver calls must use make_driver_headers(driver_id).
    "driver_headers": build_user_headers("driver-fallback-1", "Driver"),
}


def make_driver_headers(driver_id: str) -> dict:
    """Headers for a Driver acting on their own resources.

    Pass the actual Driver.id as driver_id so ownership checks
    (X-User-ID == Citation.driver_id) pass.
    """
    return build_user_headers(driver_id, "Driver")


def make_clerk_headers(user_id: str = "clerk-op-1") -> dict:
    return build_user_headers(user_id, "CourtClerk")


def make_hearing_officer_headers(user_id: str = "hearing-op-1") -> dict:
    return build_user_headers(user_id, "HearingOfficer")


def make_dmv_headers(user_id: str = "dmv-op-1") -> dict:
    return build_user_headers(user_id, "DmvAdmin")
