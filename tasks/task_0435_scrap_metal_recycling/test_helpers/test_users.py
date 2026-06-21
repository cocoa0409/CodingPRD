"""Pre-built role headers for every role in the PRD.

All five roles use an opaque X-User-ID (PRD §2.1): the identifier is not tied to
any persisted entity and the server never compares it to an entity id for
ownership. The one place X-User-ID carries downstream meaning is the
segregation-of-duties check on payout creation, where the acting PayoutClerk's id
must differ from the WeighMaster id recorded in theft_hold_released_by. Tests that
exercise that rule build per-id headers with make_*_headers().
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — every role is opaque, so the shared form is canonical.
TEST_USERS = {
    "weigh_master_headers": build_user_headers("weigh-master-1", "WeighMaster"),
    "payout_clerk_headers": build_user_headers("payout-clerk-1", "PayoutClerk"),
    "yard_manager_headers": build_user_headers("yard-manager-1", "YardManager"),
    "settlement_accountant_headers": build_user_headers("settlement-accountant-1", "SettlementAccountant"),
    "compliance_officer_headers": build_user_headers("compliance-officer-1", "ComplianceOfficer"),
}


# Per-id builders — used by segregation-of-duties tests that must control the
# exact X-User-ID a WeighMaster (hold-clearer) or PayoutClerk (payout-approver)
# acts under.
def make_weigh_master_headers(user_id: str) -> dict:
    """WeighMaster headers carrying an explicit X-User-ID."""
    return build_user_headers(user_id, "WeighMaster")


def make_payout_clerk_headers(user_id: str) -> dict:
    """PayoutClerk headers carrying an explicit X-User-ID."""
    return build_user_headers(user_id, "PayoutClerk")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_yard_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "YardManager")


def make_settlement_accountant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SettlementAccountant")
