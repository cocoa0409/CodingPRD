"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are entity-backed: when X-User-Role is Debtor/Creditor/Trustee,
X-User-ID is the id of the acting Debtor/Creditor/Trustee, and ownership checks
compare resource foreign keys to it. For those roles, tests that exercise
ownership MUST use the per-instance make_*_headers(entity_id) builders with the
real entity's id. BankruptcyAdmin is opaque — X-User-ID is not tied to any
persisted entity — so its shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque admin role, and for tests that do NOT
# exercise ownership (e.g. 401/403/404/422 paths, or list reads by an admin).
TEST_USERS = {
    # opaque role: shared constant is canonical.
    "admin_headers": build_user_headers("test-admin-1", "BankruptcyAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "debtor_headers": build_user_headers("test-debtor-1", "Debtor"),
    "creditor_headers": build_user_headers("test-creditor-1", "Creditor"),
    "trustee_headers": build_user_headers("test-trustee-1", "Trustee"),
}


# Per-instance builders — required for every entity_backed role. Pass the actual
# entity id so ownership / segregation-of-duties checks resolve correctly.
def make_debtor_headers(debtor_id: str) -> dict:
    """For Debtor (entity_backed:Debtor). Pass the real Debtor.id."""
    return build_user_headers(debtor_id, "Debtor")


def make_creditor_headers(creditor_id: str) -> dict:
    """For Creditor (entity_backed:Creditor). Pass the real Creditor.id."""
    return build_user_headers(creditor_id, "Creditor")


def make_trustee_headers(trustee_id: str) -> dict:
    """For Trustee (entity_backed:Trustee). Pass the real Trustee.id — the
    meeting-hold check compares X-User-ID to Meeting341.trustee_id."""
    return build_user_headers(trustee_id, "Trustee")
