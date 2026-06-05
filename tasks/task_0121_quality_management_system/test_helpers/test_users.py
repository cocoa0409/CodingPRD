"""Pre-built role headers for every role in the PRD.

All five roles are entity_backed:
  - QualityEngineer, QualityManager, Inspector, Auditor -> entity_backed:Personnel
  - SupplierUser -> entity_backed:Supplier

The shared TEST_USERS constants are safe ONLY for:
  - genesis/operator calls whose X-User-ID need not resolve (POST /personnel,
    POST /suppliers, POST /_clock/set_current_utc), and
  - tests that do not exercise ownership/SoD (e.g. 400 bad-payload, 404 missing
    resource, 403 forbidden-role).

For ownership/SoD-gated calls, ALWAYS thread the real entity id via the
make_<role>_headers(user_id) builder.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Operator/genesis caller — X-User-ID need not resolve. Used to create
    # Personnel and Suppliers and to drive the clock.
    "manager_headers": build_user_headers("test-manager-genesis", "QualityManager"),
    "engineer_headers": build_user_headers("test-engineer-shared", "QualityEngineer"),
    "inspector_headers": build_user_headers("test-inspector-shared", "Inspector"),
    "auditor_headers": build_user_headers("test-auditor-shared", "Auditor"),
    "supplier_user_headers": build_user_headers("test-supplier-shared", "SupplierUser"),
}


def make_manager_headers(user_id: str) -> dict:
    """QualityManager (entity_backed:Personnel). Pass the Personnel.id."""
    return build_user_headers(user_id, "QualityManager")


def make_engineer_headers(user_id: str) -> dict:
    """QualityEngineer (entity_backed:Personnel). Pass the Personnel.id."""
    return build_user_headers(user_id, "QualityEngineer")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector (entity_backed:Personnel). Pass the Personnel.id."""
    return build_user_headers(user_id, "Inspector")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor (entity_backed:Personnel). Pass the Personnel.id (the lead auditor's)."""
    return build_user_headers(user_id, "Auditor")


def make_supplier_user_headers(supplier_id: str) -> dict:
    """SupplierUser (entity_backed:Supplier). Pass the Supplier.id."""
    return build_user_headers(supplier_id, "SupplierUser")
