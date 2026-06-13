"""Pre-built role headers for every role in the PRD (§2.1).

FrontDesk, BillingClerk, and PracticeAdmin carry opaque identities — the shared
constant is the canonical form for them. Provider is entity_backed:Provider, so
ownership-gated calls (finalize exam, sign SOAP, complete) must use
make_provider_headers(provider_id) with the real Provider.id; the shared
constant is only a fallback for tests that are rejected before the ownership
check (e.g. forbidden-role / not-found).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque roles — shared constant is canonical
    "frontdesk_headers": build_user_headers("frontdesk-operator-1", "FrontDesk"),
    "billing_headers": build_user_headers("billing-operator-1", "BillingClerk"),
    "admin_headers": build_user_headers("admin-operator-1", "PracticeAdmin"),
    # entity_backed:Provider — fallback only for non-ownership tests
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# ---------------------------------------------------------------------------
def make_provider_headers(provider_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the real Provider.id as the
    user id whenever the call is ownership-gated (finalize exam, sign SOAP,
    propose/activate/discontinue/regress plan, add phase, complete)."""
    return build_user_headers(provider_id, "Provider")


def make_frontdesk_headers(user_id: str = "frontdesk-operator-1") -> dict:
    return build_user_headers(user_id, "FrontDesk")


def make_billing_headers(user_id: str = "billing-operator-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_admin_headers(user_id: str = "admin-operator-1") -> dict:
    return build_user_headers(user_id, "PracticeAdmin")


def make_anonymous_headers() -> dict:
    """Headers with no X-User-ID / X-User-Role — for ERR_UNAUTHENTICATED tests."""
    return {"Content-Type": "application/json"}
