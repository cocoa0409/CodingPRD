"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque AgencyAdmin / AgencyAccountant roles,
# and for Producer-role calls that are not ownership-gated.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "AgencyAdmin"),
    "accountant_headers": build_user_headers("test-accountant-1", "AgencyAccountant"),
    # Producer is entity-backed: this shared constant is only a fallback for
    # non-ownership calls (e.g. plain reads). For ownership-gated calls such as
    # acknowledging a disclosure, use make_producer_headers(producer["id"]).
    "producer_headers": build_user_headers("test-producer-1", "Producer"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """AgencyAdmin headers (opaque identity; not tied to any entity)."""
    return build_user_headers(user_id, "AgencyAdmin")


def make_accountant_headers(user_id: str = "test-accountant-1") -> dict:
    """AgencyAccountant headers (opaque identity; not tied to any entity)."""
    return build_user_headers(user_id, "AgencyAccountant")


def make_producer_headers(user_id: str) -> dict:
    """Producer headers. Per PRD §2.1, X-User-ID must be the acting Producer's
    id for ownership checks — pass the actual Producer.id whenever the call is
    ownership-gated (e.g. POST /agency/producer-disclosures/{id}/acknowledge)."""
    return build_user_headers(user_id, "Producer")
