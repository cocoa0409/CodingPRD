"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the five opaque staff roles, and for tests whose
# outcome does not depend on the caller owning the subject resource.
TEST_USERS = {
    "privacy_admin_headers": build_user_headers("pa-1", "PrivacyAdmin"),
    "data_steward_headers": build_user_headers("ds-1", "DataSteward"),
    "business_owner_headers": build_user_headers("bo-1", "BusinessOwner"),
    "business_owner_2_headers": build_user_headers("bo-2", "BusinessOwner"),
    "legal_counsel_headers": build_user_headers("lc-1", "LegalCounsel"),
    "legal_counsel_2_headers": build_user_headers("lc-2", "LegalCounsel"),
    "legal_counsel_9_headers": build_user_headers("lc-9", "LegalCounsel"),
    "vendor_manager_headers": build_user_headers("vm-1", "VendorManager"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
}


def make_consumer_headers(user_id: str) -> dict:
    """For Consumer (entity_backed:Consumer). Pass the actual Consumer.id as
    user_id whenever the call is ownership-gated (file or read own requests)."""
    return build_user_headers(user_id, "Consumer")


def make_business_owner_headers(user_id: str) -> dict:
    """BusinessOwner headers with a caller-chosen X-User-ID — needed because the
    assessment submit records the caller id for the segregation-of-duties check."""
    return build_user_headers(user_id, "BusinessOwner")


def make_legal_counsel_headers(user_id: str) -> dict:
    """LegalCounsel headers with a caller-chosen X-User-ID — the reviewer id is
    compared to the assessment's submitted_by_user_id on every decision action."""
    return build_user_headers(user_id, "LegalCounsel")
