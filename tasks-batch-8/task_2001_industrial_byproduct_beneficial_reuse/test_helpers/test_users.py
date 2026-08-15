"""Pre-built role headers for every role in the PRD (§2.1).

Generator and Offtaker are entity-backed roles: X-User-ID must be the id of the
acting organization. Use the per-instance builders with the real entity id for
any ownership-gated call; the shared constants are fallbacks for tests that do
not exercise ownership (400/404 paths, opaque roles).
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identities (PRD §2.1: never compared to any entity id,
# except that ComplianceOfficer ids are compared against each other for
# segregation of duties on eligibility adjudication).
BROKER_OPS_USER_ID = "broker-ops-1"
CO_FILE_USER_ID = "co_file"
CO_APPR_USER_ID = "co_appr"
PLATFORM_ADMIN_USER_ID = "platform-admin-1"

TEST_USERS = {
    # entity_backed fallbacks — NOT usable for ownership-gated calls.
    "generator_headers": build_user_headers("test-generator-1", "Generator"),
    "offtaker_headers": build_user_headers("test-offtaker-1", "Offtaker"),
    # opaque roles — canonical shared form.
    "broker_ops_headers": build_user_headers(BROKER_OPS_USER_ID, "BrokerOps"),
    "compliance_officer_file_headers": build_user_headers(
        CO_FILE_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_approve_headers": build_user_headers(
        CO_APPR_USER_ID, "ComplianceOfficer"
    ),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
}


def make_generator_headers(user_id: str) -> dict:
    """Generator is entity-backed: pass the actual Generator.id as user_id."""
    return build_user_headers(user_id, "Generator")


def make_offtaker_headers(user_id: str) -> dict:
    """Offtaker is entity-backed: pass the actual Offtaker.id as user_id."""
    return build_user_headers(user_id, "Offtaker")


def make_broker_ops_headers(user_id: str = BROKER_OPS_USER_ID) -> dict:
    return build_user_headers(user_id, "BrokerOps")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
