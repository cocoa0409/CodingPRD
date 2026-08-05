"""Pre-built role headers for every role in the PRD (Section 2.1).

- TaxAdmin and Auditor are opaque identities: X-User-ID is not tied to any
  persisted entity, so the shared constants are the canonical form.
- Operator is entity_backed:Operator: X-User-ID must equal the id of the acting
  Operator record. Ownership checks compare a resource's operator_id (directly
  or transitively) to X-User-ID, so ownership-gated Operator calls (file, amend,
  submit appeal, provide-info) MUST use make_operator_headers(operator_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (TaxAdmin, Auditor) and for tests
# that never exercise Operator ownership.
TEST_USERS = {
    "taxadmin_headers": build_user_headers("taxadmin-1", "TaxAdmin"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    # Operator fallback — only valid where ownership is not enforced.
    "operator_headers": build_user_headers("operator-unowned", "Operator"),
}


def make_taxadmin_headers(user_id: str = "taxadmin-1") -> dict:
    """TaxAdmin headers with a specific opaque X-User-ID."""
    return build_user_headers(user_id, "TaxAdmin")


def make_auditor_headers(user_id: str = "auditor-1") -> dict:
    """Auditor headers with a specific opaque X-User-ID."""
    return build_user_headers(user_id, "Auditor")


def make_operator_headers(operator_id: str) -> dict:
    """Operator headers whose X-User-ID equals the owned Operator.id.

    Mandatory for every ownership-gated Operator write (file/amend a return,
    submit an appeal, provide appeal info)."""
    return build_user_headers(operator_id, "Operator")


def anonymous_headers() -> dict:
    """Headers with NO X-User-Role, for unauthenticated-request tests."""
    return {"X-User-ID": "anon", "Content-Type": "application/json"}
