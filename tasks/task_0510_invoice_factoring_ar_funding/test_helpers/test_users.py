"""Pre-built role headers for every role in the PRD.

All four roles use an opaque X-User-ID that the server does not tie to any
persisted entity (PRD §2.1). The X-User-ID does matter for the
segregation-of-duties check at funding: the recorded credit_decision_user_id
of a client/debtor must differ from the funding X-User-ID. The shared
constants therefore use distinct, stable user ids per role so that, by
default, the underwriter who approves credit (uw_1) differs from the funding
officer who funds (fo_1).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles, distinct ids per role.
TEST_USERS = {
    "admin_headers": build_user_headers("admin_1", "PlatformAdmin"),
    "underwriter_headers": build_user_headers("uw_1", "UnderwritingOfficer"),
    "underwriter2_headers": build_user_headers("uw_2", "UnderwritingOfficer"),
    "funding_headers": build_user_headers("fo_1", "FundingOfficer"),
    "collections_headers": build_user_headers("co_1", "CollectionsOfficer"),
}


# Per-id builders — for tests that need to control the acting X-User-ID
# (e.g., the segregation-of-duties case where the funder reuses the
# underwriter's id).
def make_admin_headers(user_id: str = "admin_1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_underwriter_headers(user_id: str = "uw_1") -> dict:
    return build_user_headers(user_id, "UnderwritingOfficer")


def make_funding_headers(user_id: str = "fo_1") -> dict:
    return build_user_headers(user_id, "FundingOfficer")


def make_collections_headers(user_id: str = "co_1") -> dict:
    return build_user_headers(user_id, "CollectionsOfficer")
