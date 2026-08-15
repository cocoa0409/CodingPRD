"""Pre-built role headers for every role in the PRD (section 2.1).

OriginatorOps is entity-backed: its X-User-ID IS the acting Originator's id,
so ownership-gated calls must use make_originator_headers(originator["id"]).
The four bank roles are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator ids used across the suite.
UNDERWRITER_USER_ID = "uw-1"
OPERATIONS_USER_ID = "ops-1"
RISK_OFFICER_USER_ID = "risk-1"
FINANCE_USER_ID = "fin-1"

# Shared constants — safe for opaque bank roles. The OriginatorOps constant is
# a fallback for tests that do not exercise ownership (e.g. 400/404 probes).
TEST_USERS = {
    "originator_ops_headers": build_user_headers("test-originator-1",
                                                 "OriginatorOps"),
    "underwriter_headers": build_user_headers(UNDERWRITER_USER_ID,
                                              "OdfiUnderwriter"),
    "operations_headers": build_user_headers(OPERATIONS_USER_ID,
                                             "OdfiOperations"),
    "risk_officer_headers": build_user_headers(RISK_OFFICER_USER_ID,
                                               "OdfiRiskOfficer"),
    "finance_headers": build_user_headers(FINANCE_USER_ID, "OdfiFinance"),
}


# Per-instance builder — REQUIRED for every ownership-gated OriginatorOps call:
# the id passed here must equal the target resource chain's originator id.
def make_originator_headers(originator_id: str) -> dict:
    """OriginatorOps headers whose X-User-ID is the given Originator id."""
    return build_user_headers(originator_id, "OriginatorOps")


def make_underwriter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OdfiUnderwriter")


def make_operations_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OdfiOperations")


def make_risk_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OdfiRiskOfficer")


def make_finance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OdfiFinance")
