"""Pre-built role headers for every role in the PRD (§2.1).

Three roles carry an opaque identity (Underwriter, ClaimsAdjudicator,
SystemOperator); their X-User-ID is not tied to any persisted entity, so the
shared-constant form is canonical for them. The Policyholder role is
entity-backed: X-User-ID must be the id of the acting Policyholder entity, so
ownership-gated calls MUST use make_policyholder_headers(policyholder_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for opaque roles, and for tests that do not exercise
# Policyholder ownership (e.g. a Policyholder hitting a forbidden op, or any
# 401/404 path where identity does not gate success).
TEST_USERS = {
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "claims_adjudicator_headers": build_user_headers("test-adjudicator-1", "ClaimsAdjudicator"),
    "system_operator_headers": build_user_headers("test-operator-1", "SystemOperator"),
    # Fallback only — never use for an ownership-gated Policyholder call.
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
}


# Per-instance builders.
def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    """Underwriter (opaque identity)."""
    return build_user_headers(user_id, "Underwriter")


def make_claims_adjudicator_headers(user_id: str = "test-adjudicator-1") -> dict:
    """ClaimsAdjudicator (opaque identity)."""
    return build_user_headers(user_id, "ClaimsAdjudicator")


def make_system_operator_headers(user_id: str = "test-operator-1") -> dict:
    """SystemOperator (opaque identity)."""
    return build_user_headers(user_id, "SystemOperator")


def make_policyholder_headers(user_id: str) -> dict:
    """Policyholder (entity_backed:Policyholder). Pass the actual Policyholder.id
    as user_id whenever the call is ownership-gated (file/submit/income-report/
    disability-proof on a claim whose policy the policyholder owns)."""
    return build_user_headers(user_id, "Policyholder")
