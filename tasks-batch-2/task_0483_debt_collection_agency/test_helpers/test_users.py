"""Pre-built role headers for every role in the PRD (§2.1).

The five roles differ in how X-User-ID relates to persisted data. For a
``Creditor``, X-User-ID is the id of the acting Creditor entity, and ownership
checks on resources that reference a creditor compare the resource's creditor
foreign key to X-User-ID. The other four roles (``Collector``,
``ComplianceOfficer``, ``BureauOperator``, ``System``) carry an opaque identity
the server does not compare to any entity id.

Because Creditor is entity-backed, ownership-gated calls (place/recall/close on a
creditor's own account) MUST use ``make_creditor_headers(creditor["id"])`` with
the real Creditor id. The shared TEST_USERS["creditor_headers"] constant is a
fallback only for tests that do not exercise ownership (e.g. 400/403/404 paths).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   - creditor_headers: entity_backed fallback for non-ownership tests only.
#   - the other four roles are opaque, so the shared form is canonical.
TEST_USERS = {
    "creditor_headers": build_user_headers("test-creditor-1", "Creditor"),
    "collector_headers": build_user_headers("test-collector-1", "Collector"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "bureau_operator_headers": build_user_headers("test-bureau-1", "BureauOperator"),
    "system_headers": build_user_headers("test-system-1", "System"),
}


# Per-instance builder — required for the entity_backed Creditor role.
def make_creditor_headers(user_id: str) -> dict:
    """Creditor headers carrying an explicit X-User-ID. Pass the real Creditor.id
    as user_id whenever the downstream call is ownership-gated."""
    return build_user_headers(user_id, "Creditor")


def make_collector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Collector")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_bureau_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BureauOperator")


def make_system_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "System")
