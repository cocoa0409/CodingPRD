"""Pre-built role headers for every role in the PRD.

Two role families:
  - opaque roles (PlatformAdmin, QaValidator, FinanceOfficer, Anonymous): the
    X-User-ID is not tied to any persisted entity, so a shared constant is the
    canonical form.
  - entity_backed roles (ClientManager -> ClientAccount, Shopper -> Shopper):
    ownership checks compare X-User-ID to a real entity id, so callers MUST use
    the per-instance builders below with the actual entity's id whenever the call
    is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (e.g. 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "qa_validator_headers": build_user_headers("test-qa-1", "QaValidator"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "client_manager_headers": build_user_headers("test-client-1", "ClientManager"),
    "shopper_headers": build_user_headers("test-shopper-1", "Shopper"),
}


# --- Per-instance builders -------------------------------------------------
def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin (opaque). The id is not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_qa_validator_headers(user_id: str = "test-qa-1") -> dict:
    """QaValidator (opaque). The id is recorded as validated_by_user_id but never
    compared to an entity id for ownership."""
    return build_user_headers(user_id, "QaValidator")


def make_finance_officer_headers(user_id: str = "test-finance-1") -> dict:
    """FinanceOfficer (opaque). The id is compared against an assignment's
    validated_by_user_id for separation-of-duties, not for ownership."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """Anonymous (opaque). Used for public self-registration."""
    return build_user_headers(user_id, "Anonymous")


def make_client_manager_headers(client_id: str) -> dict:
    """ClientManager (entity_backed:ClientAccount). Pass the actual ClientAccount.id
    as user_id whenever the call is ownership-gated (locations/scripts/waves/etc.)."""
    return build_user_headers(client_id, "ClientManager")


def make_shopper_headers(shopper_id: str) -> dict:
    """Shopper (entity_backed:Shopper). Pass the actual Shopper.id as user_id
    whenever the call is ownership-gated (accept/evidence/scorecard/submit/etc.)."""
    return build_user_headers(shopper_id, "Shopper")
