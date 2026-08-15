"""Pre-built role headers for every role in the PRD.

Producer is entity-backed by ProductionCompany and CreditBuyer is
entity-backed by CreditBuyer: for ownership-gated calls, build per-instance
headers with make_producer_headers(company_id) / make_buyer_headers(buyer_id)
using the real entity id. The shared constants are fallbacks for tests that
do not exercise ownership (self-registration, bad-payload 400s, 404s).
FilmOfficeAdmin, FilmOfficeReviewer, and CPAAuditor carry opaque operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles.
    "admin_headers": build_user_headers("admin-1", "FilmOfficeAdmin"),
    "reviewer1_headers": build_user_headers("reviewer-1", "FilmOfficeReviewer"),
    "reviewer2_headers": build_user_headers("reviewer-2", "FilmOfficeReviewer"),
    "reviewer3_headers": build_user_headers("reviewer-3", "FilmOfficeReviewer"),
    "cpa1_headers": build_user_headers("cpa-1", "CPAAuditor"),
    "cpa2_headers": build_user_headers("cpa-2", "CPAAuditor"),
    # Entity-backed fallbacks — only for calls that do not exercise ownership.
    "producer_headers": build_user_headers("producer-unregistered", "Producer"),
    "buyer_headers": build_user_headers("buyer-unregistered", "CreditBuyer"),
}


def make_producer_headers(production_company_id: str) -> dict:
    """Producer identity IS the ProductionCompany id (entity-backed).

    Pass the real company id returned by registration whenever the call is
    ownership-gated (productions, applications, spend, redeem, appeal,
    seller-side transfer acts).
    """
    return build_user_headers(production_company_id, "Producer")


def make_buyer_headers(credit_buyer_id: str) -> dict:
    """CreditBuyer identity IS the CreditBuyer id (entity-backed).

    Pass the real buyer id whenever the call is ownership-gated
    (buyer-side counter / accept / cancel on a transfer).
    """
    return build_user_headers(credit_buyer_id, "CreditBuyer")


def make_reviewer_headers(reviewer_user_id: str) -> dict:
    """FilmOfficeReviewer carries an opaque operator id (never an entity id)."""
    return build_user_headers(reviewer_user_id, "FilmOfficeReviewer")


def make_admin_headers(admin_user_id: str = "admin-1") -> dict:
    """FilmOfficeAdmin carries an opaque operator id."""
    return build_user_headers(admin_user_id, "FilmOfficeAdmin")


def make_cpa_headers(cpa_user_id: str) -> dict:
    """CPAAuditor carries an opaque operator id; the same id must be used for
    every owner-gated write on the engaged audit package."""
    return build_user_headers(cpa_user_id, "CPAAuditor")
