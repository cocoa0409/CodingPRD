"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque operator identifiers: `X-User-ID` is never tied to the
`id` of any persisted entity. The shared constants below are canonical; the
per-user builders exist for ownership and segregation-of-duties tests that need
two distinct ForwarderAgent or DGInspector identities.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import DG_INSPECTOR_USER, FWD_USER_1

TEST_USERS = {
    "capacity_controller_headers": build_user_headers("cc-1", "CapacityController"),
    "forwarder_agent_headers": build_user_headers(FWD_USER_1, "ForwarderAgent"),
    "ramp_operator_headers": build_user_headers("ramp-1", "RampOperator"),
    "dg_inspector_headers": build_user_headers(DG_INSPECTOR_USER, "DGInspector"),
    "customs_officer_headers": build_user_headers("customs-1", "CustomsOfficer"),
    "claims_adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
}


def make_capacity_controller_headers(user_id: str = "cc-1") -> dict:
    return build_user_headers(user_id, "CapacityController")


def make_forwarder_headers(user_id: str) -> dict:
    """ForwarderAgent whose X-User-ID is recorded as booking.created_by_user_id;
    pass the same id for every ownership-gated call on that booking."""
    return build_user_headers(user_id, "ForwarderAgent")


def make_ramp_operator_headers(user_id: str = "ramp-1") -> dict:
    return build_user_headers(user_id, "RampOperator")


def make_dg_inspector_headers(user_id: str) -> dict:
    """DGInspector identity; must differ from the booking creator's id for any
    declaration check (segregation of duties, PRD §3.3)."""
    return build_user_headers(user_id, "DGInspector")


def make_customs_officer_headers(user_id: str = "customs-1") -> dict:
    return build_user_headers(user_id, "CustomsOfficer")


def make_claims_adjuster_headers(user_id: str = "adj-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")
