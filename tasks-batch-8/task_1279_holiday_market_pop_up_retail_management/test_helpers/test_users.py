"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. VendorRole is entity-backed: for ownership-gated calls use
# make_vendor_headers(vendor["id"]) instead of the shared constant.
TEST_USERS = {
    "market_operator_headers": build_user_headers("test-operator-1", "MarketOperator"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "vendor_headers": build_user_headers("test-vendor-1", "VendorRole"),
    "jury_member_headers": build_user_headers("test-juror-1", "JuryMember"),
    "jury_chair_headers": build_user_headers("test-jurychair-1", "JuryChair"),
    "utility_crew_headers": build_user_headers("test-utility-1", "UtilityCrew"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
}


def make_vendor_headers(user_id: str) -> dict:
    """For VendorRole: X-User-ID must equal the acting Vendor.id whenever the
    call is ownership-gated (application submit/withdraw, settlement create,
    load-slot check-in, renewal accept/decline)."""
    return build_user_headers(user_id, "VendorRole")


def make_juror_headers(juror_id: str) -> dict:
    """For JuryMember: X-User-ID is recorded as juror_id on each score; use a
    distinct id per scoring juror (a juror cannot score the same application
    twice)."""
    return build_user_headers(juror_id, "JuryMember")


def make_operator_headers(user_id: str) -> dict:
    """For MarketOperator (opaque identity)."""
    return build_user_headers(user_id, "MarketOperator")
