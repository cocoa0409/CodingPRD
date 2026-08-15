"""Pre-built role headers for every role in the PRD.

All four roles are opaque identities: `X-User-ID` is not tied to any persisted
entity. It is only compared against attribution anchors recorded on resources
(`recorded_by_user_id`, `sold_by_user_id`) by the segregation-of-duties checks,
so tests that exercise segregation build headers with explicit user ids via the
`make_*` builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — the canonical caller identity per role for any test whose
# outcome does not depend on a specific segregation pairing.
TEST_USERS = {
    "ranch_manager_headers": build_user_headers("u-ranch-1", "RanchManager"),
    "range_manager_headers": build_user_headers("u-range-1", "RangeManager"),
    "herd_manager_headers": build_user_headers("u-herd-1", "HerdManager"),
    "sales_agent_headers": build_user_headers("u-sale-1", "SalesAgent"),
}


def make_ranch_manager_headers(user_id: str = "u-ranch-1") -> dict:
    return build_user_headers(user_id, "RanchManager")


def make_range_manager_headers(user_id: str = "u-range-1") -> dict:
    return build_user_headers(user_id, "RangeManager")


def make_herd_manager_headers(user_id: str = "u-herd-1") -> dict:
    return build_user_headers(user_id, "HerdManager")


def make_sales_agent_headers(user_id: str = "u-sale-1") -> dict:
    return build_user_headers(user_id, "SalesAgent")
