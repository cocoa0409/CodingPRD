"""Pre-built role headers for every role in the PRD (§2.1).

Five roles: LegalOps, ReviewLead, Reviewer, Producer (opaque operator identities)
and Custodian (entity-backed: X-User-ID is the acting Custodian entity's id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the four opaque operator roles, and for Custodian
# tests whose success does NOT depend on owning the subject acknowledgement
# (e.g. a forbidden-role rejection, or a not-owner check).
TEST_USERS = {
    "legalops_headers": build_user_headers("legalops-1", "LegalOps"),
    "reviewlead_headers": build_user_headers("reviewlead-1", "ReviewLead"),
    "reviewer_headers": build_user_headers("reviewer-1", "Reviewer"),
    "producer_headers": build_user_headers("producer-1", "Producer"),
    # entity_backed:Custodian — shared constant is a fallback for non-ownership
    # tests only. Ownership-gated acknowledge calls MUST use
    # make_custodian_headers(custodian_id).
    "custodian_headers": build_user_headers("custodian-fallback-1", "Custodian"),
}


def make_legalops_headers(user_id: str = "legalops-1") -> dict:
    """LegalOps is an opaque operator; any stable id works."""
    return build_user_headers(user_id, "LegalOps")


def make_reviewlead_headers(user_id: str = "reviewlead-1") -> dict:
    return build_user_headers(user_id, "ReviewLead")


def make_reviewer_headers(user_id: str = "reviewer-1") -> dict:
    """Reviewer is opaque; the X-User-ID is recorded on the review's
    reviewer_user_id and later drives segregation-of-duties enforcement."""
    return build_user_headers(user_id, "Reviewer")


def make_producer_headers(user_id: str = "producer-1") -> dict:
    """Producer is opaque; the X-User-ID is compared against reviewer_user_id
    at produce time for segregation of duties."""
    return build_user_headers(user_id, "Producer")


def make_custodian_headers(custodian_id: str) -> dict:
    """For Custodian (entity_backed:Custodian). Pass the actual Custodian.id as
    X-User-ID whenever the call is ownership-gated (acknowledge own notice,
    read own acknowledgements)."""
    return build_user_headers(custodian_id, "Custodian")
