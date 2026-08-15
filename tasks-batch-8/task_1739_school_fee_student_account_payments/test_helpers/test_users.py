"""Pre-built role headers for every role in the PRD (§2.1).

All three roles use opaque X-User-ID identifiers never compared against entity
ids, so shared constants are canonical for every role. Distinct user ids are
still needed where segregation-of-duties rules compare recorded operator
identifiers to one another (waiver review, write-off) — use the builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "bookkeeper_headers": build_user_headers("bk-1", "Bookkeeper"),
    "family_headers": build_user_headers("fam-1", "FamilyMember"),
    "superintendent_headers": build_user_headers("supt-1", "Superintendent"),
}


def make_bookkeeper_headers(user_id: str = "bk-1") -> dict:
    """Bookkeeper headers with a specific operator id (used where SoD compares ids)."""
    return build_user_headers(user_id, "Bookkeeper")


def make_family_headers(user_id: str = "fam-1") -> dict:
    """FamilyMember headers with a specific operator id (submitter id is recorded)."""
    return build_user_headers(user_id, "FamilyMember")


def make_superintendent_headers(user_id: str = "supt-1") -> dict:
    """Superintendent headers with a specific operator id."""
    return build_user_headers(user_id, "Superintendent")
