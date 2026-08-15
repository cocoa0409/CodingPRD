"""Pre-built role headers for every role in the PRD (§2.1).

ProducerRep is entity-backed: its X-User-ID must equal the owning
ProducerCompany.id, so ownership-gated calls must use
make_producer_rep_headers(company_id) with the real company id.
UnionRep / FundTrustee / Arbitrator / PlatformAdmin are opaque operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Fallback for non-ownership ProducerRep calls (e.g. company registration).
    "producer_rep_headers": build_user_headers("producer-rep-registration", "ProducerRep"),
    # Opaque roles — canonical shared constants.
    "union_rep_headers": build_user_headers("ur_1", "UnionRep"),
    "union_rep_2_headers": build_user_headers("ur_2", "UnionRep"),
    "union_rep_3_headers": build_user_headers("ur_3", "UnionRep"),
    "fund_trustee_headers": build_user_headers("ft_1", "FundTrustee"),
    "fund_trustee_2_headers": build_user_headers("ft_2", "FundTrustee"),
    "fund_trustee_9_headers": build_user_headers("ft_9", "FundTrustee"),
    "arbitrator_headers": build_user_headers("arb_1", "Arbitrator"),
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
}


def make_producer_rep_headers(company_id: str) -> dict:
    """ProducerRep is entity-backed by ProducerCompany: pass the company's id
    whenever the call is ownership-gated (all production-side workflows)."""
    return build_user_headers(company_id, "ProducerRep")


def make_union_rep_headers(user_id: str) -> dict:
    """UnionRep is opaque; distinct user ids matter for segregation of duties."""
    return build_user_headers(user_id, "UnionRep")


def make_fund_trustee_headers(user_id: str) -> dict:
    """FundTrustee is opaque; distinct user ids matter for segregation of duties."""
    return build_user_headers(user_id, "FundTrustee")


def make_arbitrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Arbitrator")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
