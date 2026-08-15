"""Pre-built role headers for every role in the PRD.

MasterServicer and SpecialServicer are opaque identities: X-User-ID is not
tied to any persisted entity (it is only recorded in attribution fields such
as reviewed_by_user_id / appraised_by_user_id / waived_by_user_id, where
segregation-of-duties checks later compare against it). Borrower is
entity-backed by Borrower and Inspector is entity-backed by Inspector:
X-User-ID must be the acting entity's id for any ownership-gated call.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "master_servicer_headers": build_user_headers("ms_user_1", "MasterServicer"),
    "master_servicer_headers_2": build_user_headers("ms_user_2", "MasterServicer"),
    "special_servicer_headers": build_user_headers("ss_user_1", "SpecialServicer"),
    "special_servicer_headers_2": build_user_headers("ss_user_2", "SpecialServicer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only (e.g. role-denial checks where the role gate fires first).
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


def make_master_servicer_headers(user_id: str = "ms_user_1") -> dict:
    """MasterServicer is opaque; pick distinct ids when segregation-of-duties
    comparisons against recorded reviewer/appraiser identities matter."""
    return build_user_headers(user_id, "MasterServicer")


def make_special_servicer_headers(user_id: str = "ss_user_1") -> dict:
    """SpecialServicer is opaque; pick an id different from the recorded
    reviewer/appraiser whenever a covenant waiver must pass the SoD gate."""
    return build_user_headers(user_id, "SpecialServicer")


def make_borrower_headers(borrower_id: str) -> dict:
    """For Borrower (entity_backed:Borrower). Pass the acting Borrower.id
    whenever the call is ownership-gated (loan-chain writes and reads)."""
    return build_user_headers(borrower_id, "Borrower")


def make_inspector_headers(inspector_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the acting Inspector.id
    whenever the call is ownership-gated (completing an assigned inspection,
    reading the inspector's own schedule)."""
    return build_user_headers(inspector_id, "Inspector")
