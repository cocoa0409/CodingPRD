"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Anonymous principal: the two self-registration endpoints accept no headers at all.
ANONYMOUS_HEADERS: dict = {}

# Shared constants — safe for opaque roles (CaseWorker, ProgramAdmin, FraudInvestigator),
# and for tests that do not exercise entity ownership.
TEST_USERS = {
    "anonymous_headers": ANONYMOUS_HEADERS,
    # Opaque operator roles — X-User-ID is never compared to any entity id.
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "caseworker_headers": build_user_headers("cw-generic-1", "CaseWorker"),
    "fraud_headers": build_user_headers("fraud-1", "FraudInvestigator"),
    # entity_backed roles — shared constant is a fallback for NON-ownership tests only.
    "tenant_headers": build_user_headers("tenant-shared", "Tenant"),
    "landlord_headers": build_user_headers("landlord-shared", "Landlord"),
}


# ---- Per-instance builders ----

def make_tenant_headers(user_id: str) -> dict:
    """Tenant (entity_backed:Tenant). Pass the actual Tenant.id for ownership-gated calls."""
    return build_user_headers(user_id, "Tenant")


def make_landlord_headers(user_id: str) -> dict:
    """Landlord (entity_backed:Landlord). Pass the actual Landlord.id for ownership-gated calls."""
    return build_user_headers(user_id, "Landlord")


def make_caseworker_headers(user_id: str) -> dict:
    """CaseWorker (opaque). X-User-ID is recorded (approved_by_cw_id / issued_by_cw_id)
    and compared only for the segregation-of-duties check."""
    return build_user_headers(user_id, "CaseWorker")


def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_fraud_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FraudInvestigator")
