"""Pre-built role headers for every role in the PRD.

All four roles are opaque identities: X-User-ID is not tied to any persisted
entity, and every segregation-of-duties comparison is a plain string-equality
check between two X-User-ID values (PRD section on user and role-based access
control). Shared constants are therefore safe for general use; the per-instance
builders exist so tests can pin exact identities on either side of a
segregated pair.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles; safe for any call that does not pin a
# specific segregation identity.
TEST_USERS = {
    "qa_headers": build_user_headers("test-qa-1", "QualityAssurance"),
    "environment_tech_headers": build_user_headers("test-env-tech-1", "EnvironmentTech"),
    "production_operator_headers": build_user_headers("test-prod-op-1", "ProductionOperator"),
    "material_handler_headers": build_user_headers("test-mat-handler-1", "MaterialHandler"),
}


def make_qa_headers(user_id: str) -> dict:
    """QualityAssurance headers carrying an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "QualityAssurance")


def make_environment_tech_headers(user_id: str) -> dict:
    """EnvironmentTech headers carrying an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "EnvironmentTech")


def make_production_operator_headers(user_id: str) -> dict:
    """ProductionOperator headers carrying an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "ProductionOperator")


def make_material_handler_headers(user_id: str) -> dict:
    """MaterialHandler headers carrying an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "MaterialHandler")
