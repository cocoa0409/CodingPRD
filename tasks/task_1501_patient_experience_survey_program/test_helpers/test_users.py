"""Pre-built role headers for every role in the PRD (§2.1).

ProgramAdmin and DataSteward are opaque roles: the server does not compare
their X-User-ID to any entity's id, so the shared constants are canonical.

VendorOperator and UnitManager are entity-backed (their X-User-ID is the id
of the acting SurveyVendor / CareUnit): any ownership-gated call MUST build
headers with the actual entity id via make_vendor_headers(vendor_id) /
make_unit_manager_headers(unit_id). The shared constants for those two roles
are fallbacks for non-ownership tests only (e.g., RBAC denial checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "steward_headers": build_user_headers("test-steward-1", "DataSteward"),
    # Entity-backed roles — fallback for non-ownership tests only.
    "vendor_headers": build_user_headers("test-vendor-1", "VendorOperator"),
    "unit_manager_headers": build_user_headers("test-unit-1", "UnitManager"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ProgramAdmin is opaque; any identifier works."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_steward_headers(user_id: str = "test-steward-1") -> dict:
    """DataSteward is opaque; any identifier works."""
    return build_user_headers(user_id, "DataSteward")


def make_vendor_headers(user_id: str) -> dict:
    """VendorOperator is entity_backed:SurveyVendor. Pass the actual
    SurveyVendor.id as user_id whenever the call is ownership-gated
    (response intake, mark-undeliverable)."""
    return build_user_headers(user_id, "VendorOperator")


def make_unit_manager_headers(user_id: str) -> dict:
    """UnitManager is entity_backed:CareUnit. Pass the actual CareUnit.id as
    user_id whenever the call is ownership-gated (ticket create/acknowledge/
    resolve)."""
    return build_user_headers(user_id, "UnitManager")
