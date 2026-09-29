"""Pre-built role headers for every role the PRD declares.

The `X-User-ID` values of the opaque roles carry the PRD's declared prefixes:
`lc-` for the liquidation consultant, `rc-` for the retailer controller, `co-`
for the compliance officer and `so-` for the system operator.  The store
manager is backed by a store, so its `X-User-ID` is the acting store's `id` and
must be built per instance with `make_store_manager_headers()`.
"""
from prd_bench_local_runner.testing import build_user_headers

LIQUIDATION_CONSULTANT_ID = "lc-1"
SECOND_LIQUIDATION_CONSULTANT_ID = "lc-2"
RETAILER_CONTROLLER_ID = "rc-1"
SECOND_RETAILER_CONTROLLER_ID = "rc-2"
COMPLIANCE_OFFICER_ID = "co-1"
SECOND_COMPLIANCE_OFFICER_ID = "co-2"
SYSTEM_OPERATOR_ID = "so-1"

# Shared constants — safe for the opaque roles, and for tests that do not
# exercise store ownership.
TEST_USERS = {
    "consultant_headers": build_user_headers(
        LIQUIDATION_CONSULTANT_ID, "LiquidationConsultant"),
    "second_consultant_headers": build_user_headers(
        SECOND_LIQUIDATION_CONSULTANT_ID, "LiquidationConsultant"),
    "controller_headers": build_user_headers(
        RETAILER_CONTROLLER_ID, "RetailerController"),
    "second_controller_headers": build_user_headers(
        SECOND_RETAILER_CONTROLLER_ID, "RetailerController"),
    "compliance_headers": build_user_headers(
        COMPLIANCE_OFFICER_ID, "ComplianceOfficer"),
    "second_compliance_headers": build_user_headers(
        SECOND_COMPLIANCE_OFFICER_ID, "ComplianceOfficer"),
    "system_operator_headers": build_user_headers(
        SYSTEM_OPERATOR_ID, "SystemOperator"),
    # Fallback only: never valid for an ownership-gated store call.
    "store_manager_headers": build_user_headers("sm-unbound", "StoreManager"),
}


def make_consultant_headers(user_id=LIQUIDATION_CONSULTANT_ID) -> dict:
    """Headers for the LiquidationConsultant, whose identity is opaque."""
    return build_user_headers(user_id, "LiquidationConsultant")


def make_controller_headers(user_id=RETAILER_CONTROLLER_ID) -> dict:
    """Headers for the RetailerController, whose identity is opaque."""
    return build_user_headers(user_id, "RetailerController")


def make_compliance_headers(user_id=COMPLIANCE_OFFICER_ID) -> dict:
    """Headers for the ComplianceOfficer, whose identity is opaque."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_system_operator_headers(user_id=SYSTEM_OPERATOR_ID) -> dict:
    """Headers for the SystemOperator, whose identity is opaque."""
    return build_user_headers(user_id, "SystemOperator")


def make_store_manager_headers(store_id: str) -> dict:
    """Headers for a StoreManager.

    The StoreManager's `X-User-ID` is the acting store's own `id`; pass the real
    store id whenever the call is scoped to that store.
    """
    return build_user_headers(store_id, "StoreManager")
