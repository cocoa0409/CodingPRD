"""Pre-built role headers for every role in the PRD (Section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (BoxOffice, Promoter, GateScanner) and for
# tests that do not exercise Buyer ownership (e.g. 401/403/404 on missing resources).
TEST_USERS = {
    # Buyer is entity_backed:Buyer — this shared constant is a fallback for
    # non-ownership tests only; ownership-gated calls MUST use make_buyer_headers(id).
    "buyer_headers": build_user_headers("test-buyer-generic", "Buyer"),
    "box_office_headers": build_user_headers("test-box-office", "BoxOffice"),
    "promoter_headers": build_user_headers("prm_1", "Promoter"),
    "gate_scanner_headers": build_user_headers("test-gate-scanner", "GateScanner"),
    # An unknown/unrecognized role, for ERR_UNAUTHENTICATED tests.
    "unknown_role_headers": build_user_headers("test-nobody", "Nobody"),
}


def make_buyer_headers(user_id: str) -> dict:
    """Buyer (entity_backed:Buyer). Pass the actual Buyer.id as user_id whenever the
    call is ownership-gated (holds, orders, pay, refunds, transfers, own reads)."""
    return build_user_headers(user_id, "Buyer")


def make_promoter_headers(user_id: str = "prm_1") -> dict:
    """Promoter (opaque). X-User-ID is recorded as Event.promoter_id at create but is
    never resolved against a persisted record."""
    return build_user_headers(user_id, "Promoter")
