"""Pre-built role headers for every role the PRD recognises.

Two of the six roles are entity-backed: for `StationGroupNegotiator` the
`X-User-ID` header is the acting Station's id, and for `DistributorRep` it is
the acting Distributor's id. Ownership-gated calls MUST therefore use the
per-instance builders below with a real entity id; the shared constants are
only safe for calls where no ownership comparison can succeed anyway.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "carriage_admin_headers": build_user_headers("admin-1", "CarriageAdmin"),
    "group_counsel_headers": build_user_headers("counsel-1", "GroupCounsel"),
    "second_group_counsel_headers": build_user_headers("counsel-2", "GroupCounsel"),
    "network_representative_headers": build_user_headers(
        "netrep-1", "NetworkRepresentative"
    ),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    # Entity-backed roles: fallbacks for tests that never pass an ownership check.
    "station_group_negotiator_headers": build_user_headers(
        "station-negotiator-1", "StationGroupNegotiator"
    ),
    "distributor_rep_headers": build_user_headers(
        "distributor-rep-1", "DistributorRep"
    ),
}

ACCEPTING_COUNSEL_USER_ID = "counsel-1"
EXECUTING_COUNSEL_USER_ID = "counsel-2"


def make_station_negotiator_headers(station_id: str) -> dict:
    """Headers for a StationGroupNegotiator acting as the given Station."""
    return build_user_headers(station_id, "StationGroupNegotiator")


def make_distributor_rep_headers(distributor_id: str) -> dict:
    """Headers for a DistributorRep acting as the given Distributor."""
    return build_user_headers(distributor_id, "DistributorRep")


def make_group_counsel_headers(user_id: str) -> dict:
    """Headers for a GroupCounsel identified by an opaque counsel identifier."""
    return build_user_headers(user_id, "GroupCounsel")


def make_carriage_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "CarriageAdmin")


def make_network_representative_headers(user_id: str = "netrep-1") -> dict:
    return build_user_headers(user_id, "NetworkRepresentative")


def make_compliance_officer_headers(user_id: str = "compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
