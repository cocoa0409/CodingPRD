"""Pre-built role headers for every role in the PRD (§2.1).

FinanceAdmin, Approver, and CardholderEmployee are entity-backed: their
X-User-ID is the id of the acting Employee, compared against resource employee
foreign keys for ownership and segregation-of-duties checks. Ownership-gated and
segregation-of-duties calls MUST therefore use the per-instance builder with the
actual Employee.id (make_<role>_headers(employee_id)).

Auditor is opaque: its X-User-ID is an operator identifier not tied to any
persisted entity, so the shared constant is its canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# - FinanceAdmin: company/policy/card/GL setup and money machinery are NOT
#   ownership-gated, so the shared admin constant is the canonical form for
#   nearly all admin calls.
# - Approver / CardholderEmployee shared constants are fallbacks for tests that
#   do NOT exercise ownership/segregation (e.g. role-permission rejection,
#   missing-resource paths). Ownership/segregation calls use the per-instance
#   builders below with the real Employee.id.
# - Auditor: opaque, canonical form.
TEST_USERS = {
    "finance_admin_headers": build_user_headers("test-admin-1", "FinanceAdmin"),
    "approver_headers": build_user_headers("test-approver-1", "Approver"),
    "cardholder_headers": build_user_headers("test-cardholder-1", "CardholderEmployee"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_finance_admin_headers(user_id: str = "test-admin-1") -> dict:
    """FinanceAdmin (entity_backed:Employee). Most admin ops are not
    ownership-gated, so the default user_id is acceptable for them."""
    return build_user_headers(user_id, "FinanceAdmin")


def make_approver_headers(user_id: str) -> dict:
    """Approver (entity_backed:Employee). Pass the actual approver Employee.id;
    segregation-of-duties compares this id against the resource's requester/
    claimant/cardholder employee id."""
    return build_user_headers(user_id, "Approver")


def make_cardholder_headers(user_id: str) -> dict:
    """CardholderEmployee (entity_backed:Employee). Pass the actual cardholder
    Employee.id; ownership checks (resubmit, submit/revise claim) compare this
    id against the resource's owning employee field."""
    return build_user_headers(user_id, "CardholderEmployee")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    """Auditor is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "Auditor")


def make_role_headers(role: str, user_id: str) -> dict:
    """Generic helper: build headers for an arbitrary role string."""
    return build_user_headers(user_id, role)


# Headers carrying no user context at all (no X-User-ID / X-User-Role).
NO_CONTEXT_HEADERS: dict = {"Content-Type": "application/json"}
