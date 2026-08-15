"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. The GiftOfficer role is entity-backed: its shared constant is a
# fallback for non-ownership tests only (e.g., 404 probes); ownership-gated
# calls MUST use make_gift_officer_headers(<Fundraiser.id>).
TEST_USERS = {
    "gift_officer_headers": build_user_headers("test-gift-officer-1", "GiftOfficer"),
    "researcher_headers": build_user_headers("res-1", "ProspectResearcher"),
    "director_headers": build_user_headers("dir-1", "AdvancementDirector"),
    "director2_headers": build_user_headers("dir-2", "AdvancementDirector"),
    "vp_headers": build_user_headers("vp-1", "VPAdvancement"),
    "vp2_headers": build_user_headers("vp-2", "VPAdvancement"),
    "dro_headers": build_user_headers("dro-1", "DonorRelationsOfficer"),
    "finance_headers": build_user_headers("fin-1", "FinanceSteward"),
}


def make_gift_officer_headers(user_id: str) -> dict:
    """For GiftOfficer (entity_backed:Fundraiser). Pass the actual Fundraiser.id
    whenever the call is ownership-gated (moves, proposals, agreements, pledges)."""
    return build_user_headers(user_id, "GiftOfficer")


def make_researcher_headers(user_id: str) -> dict:
    """ProspectResearcher is opaque; any stable operator id works."""
    return build_user_headers(user_id, "ProspectResearcher")


def make_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AdvancementDirector")


def make_vp_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VPAdvancement")


def make_dro_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DonorRelationsOfficer")


def make_finance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceSteward")
