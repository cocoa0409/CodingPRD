"""Pre-built role headers for every role in the PRD.

Provider and Payer are entity_backed: their X-User-ID must equal a real
Provider.id / Payer.id for ownership checks to pass. Use the make_*_headers
builders with the actual entity id whenever a call is ownership-gated.
ExternalReviewer and Anonymous are opaque: a shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "payer_headers": build_user_headers("test-payer-1", "Payer"),
    # opaque roles: shared constant is the canonical form.
    "external_reviewer_headers": build_user_headers("test-iro-1", "ExternalReviewer"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_provider_headers(user_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id."""
    return build_user_headers(user_id, "Provider")


def make_payer_headers(user_id: str) -> dict:
    """For Payer (entity_backed:Payer). Pass the actual Payer.id."""
    return build_user_headers(user_id, "Payer")


def make_external_reviewer_headers(user_id: str = "test-iro-1") -> dict:
    """For ExternalReviewer (opaque). Identifier is not tied to any entity."""
    return build_user_headers(user_id, "ExternalReviewer")
