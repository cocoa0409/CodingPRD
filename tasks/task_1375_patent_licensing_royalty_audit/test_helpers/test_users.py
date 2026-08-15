"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. The Licensee role is entity-backed: any ownership-gated call must
# use make_licensee_headers(<actual Licensee.id>) instead of the shared constant.
TEST_USERS = {
    "analyst_headers": build_user_headers("ana-default-1", "LicensingAnalyst"),
    "counsel_headers": build_user_headers("counsel-default-1", "LegalCounsel"),
    "finance_headers": build_user_headers("fin-default-1", "FinanceOfficer"),
    "ipadmin_headers": build_user_headers("ipadmin-1", "IPAdmin"),
    # Fallback for non-ownership tests only; never use for licensee-scoped calls.
    "licensee_headers": build_user_headers("test-licensee-1", "Licensee"),
}


def make_analyst_headers(user_id: str) -> dict:
    """LicensingAnalyst is an opaque role; any stable identifier works."""
    return build_user_headers(user_id, "LicensingAnalyst")


def make_licensee_headers(user_id: str) -> dict:
    """Licensee is entity-backed: pass the actual Licensee.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Licensee")


def make_counsel_headers(user_id: str) -> dict:
    """LegalCounsel is an opaque role; distinct user ids drive SoD checks."""
    return build_user_headers(user_id, "LegalCounsel")


def make_finance_headers(user_id: str) -> dict:
    """FinanceOfficer is an opaque role; distinct user ids drive SoD checks."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_ipadmin_headers(user_id: str) -> dict:
    """IPAdmin is an opaque role operating the logical clock."""
    return build_user_headers(user_id, "IPAdmin")
