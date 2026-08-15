"""Pre-built role headers for every role in the PRD (PRD 2.1 / 4).

UnitClerk is entity-backed: its X-User-ID must be the id of the Unit it acts
for. Use make_unit_clerk_headers(unit_id) with the real Unit id for every
ownership-gated call (cart-run dispute/recount/reconcile, complaint filing).
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Two distinct LinenManager identities: invoice finalization is
    # segregation-of-duties gated against the creating manager.
    "linen_manager_headers": build_user_headers("lm-1", "LinenManager"),
    "linen_manager_2_headers": build_user_headers("lm-2", "LinenManager"),
    "evs_operator_headers": build_user_headers("evs-1", "EVSOperator"),
    "laundry_vendor_headers": build_user_headers("ven-1", "LaundryVendor"),
    "infection_control_officer_headers": build_user_headers(
        "ico-1", "InfectionControlOfficer"
    ),
    # Fallback for non-ownership calls only; never use for a call whose
    # target resource is gated on unit ownership.
    "unit_clerk_headers": build_user_headers("clerk-unowned", "UnitClerk"),
}


def make_linen_manager_headers(user_id: str = "lm-1") -> Dict[str, str]:
    return build_user_headers(user_id, "LinenManager")


def make_evs_operator_headers(user_id: str = "evs-1") -> Dict[str, str]:
    return build_user_headers(user_id, "EVSOperator")


def make_laundry_vendor_headers(user_id: str = "ven-1") -> Dict[str, str]:
    return build_user_headers(user_id, "LaundryVendor")


def make_infection_control_officer_headers(
    user_id: str = "ico-1",
) -> Dict[str, str]:
    return build_user_headers(user_id, "InfectionControlOfficer")


def make_unit_clerk_headers(unit_id: str) -> Dict[str, str]:
    """UnitClerk is entity-backed by Unit: pass the acting unit's id."""
    return build_user_headers(unit_id, "UnitClerk")
